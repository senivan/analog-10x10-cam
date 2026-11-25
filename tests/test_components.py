from dataclasses import replace
import json

import numpy as np
import pytest

from camera.adc.ideal import quantize
from camera.circuits.components import columns, timing_for
from camera.controller.timing import START
from camera.optics.scenes import frames
from camera.sensor.config import Config
from camera.simulation.acquire import acquire, build
from experiments.components import run
from experiments.run import ac_bench, cutoff


def test_models(tmp_path):
    m = run(tmp_path)
    assert 300 < m["on_ohm"] <= 500  # specified max at 5 V gate, 0.1 V drain
    assert m["dark_pA"] == pytest.approx(70, abs=0.2)
    assert m["junction_pF"] == pytest.approx(3, abs=0.03)
    assert 0.99 < m["follower_dc_gain"] < 1.01
    assert 2e6 < m["follower_bw_Hz"] < 6e6
    assert 0.6 < m["forward_10mA_V"] < 1.0


def test_rectangular_addressing_and_partition(tmp_path):
    cfg = Config(
        model="components",
        rows=2,
        cols=5,
        channels=2,
        probe_row=1,
        probe_col=4,
        tolerance=0.01,
    )
    light = np.array([[0, 0.22, 0.44, 0.66, 0.88], [1, 0.78, 0.56, 0.34, 0.12]])
    seq = [(0.0, light)]
    r = acquire(cfg, seq, tmp_path / "mono.cir")
    s = acquire(replace(cfg, partitioned=True), seq, tmp_path / "split.cir")
    # All nodes within a bank retain their state. Independent adaptive grids can
    # differ slightly at the interpolated aperture (quarter of an ADC bin).
    np.testing.assert_allclose(r.volts, s.volts, atol=cfg.adc_range / 4096 / 4, rtol=0)
    np.testing.assert_array_equal(r.samples, s.samples)
    assert np.all(np.diff(r.volts[0]) > 0.3)
    assert np.all(np.diff(r.volts[1]) < -0.3)
    assert "pd9" in r.traces and "pd0" not in r.traces
    for row in range(cfg.rows):
        for bank in range(cfg.channels):
            cols = columns(cfg, bank)
            schedule = r.samples.reshape(cfg.rows, cfg.cols)[row, cols]
            expected = (
                timing_for(cfg).read + (row * 3 + np.arange(len(cols)) + 0.9) * cfg.slot
            )
            np.testing.assert_allclose(schedule, expected, atol=1e-14, rtol=0)
    assert len(json.loads((tmp_path / "split.banks.json").read_text())) == 2
    samples = r.samples.reshape(cfg.rows, -1)[:, 3:5]
    native = np.interp(samples, r.traces["time"], r.traces["adc"])
    np.testing.assert_array_equal(
        r.codes[:, 3:5], quantize(native, cfg.bits, cfg.adc_range)
    )


def test_global_shutter_retention_and_settling(tmp_path):
    cfg = Config(
        rows=3, cols=1, model="components", probe_row=2, leakage=1e10, slot=0.0005
    )
    seq = [(0.0, np.array([[0.0], [1.0], [0.0]]))]
    r = acquire(cfg, seq, tmp_path / "static.cir")
    close = START + cfg.exposure
    flash = acquire(cfg, seq + [(close + 1e-6, 1 - seq[0][1])], tmp_path / "flash.cir")
    # Finite switch isolation and gate capacitance remain in the circuit.
    np.testing.assert_allclose(
        r.volts, flash.volts, atol=cfg.adc_range / 4096 / 2, rtol=0
    )
    t = r.traces["time"]
    start, end = close + 1e-6, r.samples[-1] - 0.9 * cfg.slot - 0.1e-6
    a, b = np.interp([start, end], t, r.traces["x2.hs"])
    expected = a * (-np.expm1(-(end - start) / (cfg.leakage * cfg.hold)))
    # Two reverse biased 10 pA junctions add ~20 uV/ms to the shunt loss.
    assert a - b == pytest.approx(expected, abs=60e-6)
    fast = acquire(replace(cfg, slot=3e-6), seq, tmp_path / "fast.cir")
    assert fast.volts[-1, 0] - r.volts[-1, 0] > 0.1


def test_gain_and_saturation(tmp_path):
    cfg = Config(model="components", rows=1, cols=1, gain=8)
    d = ac_bench(cfg, tmp_path / "gain.cir")
    gain = np.abs(d["pga"] / d["cds"])
    assert gain[0] == pytest.approx(8, rel=0.01)
    assert cutoff(d["frequency"].real, abs(d["adc"] / d["pga"])) == pytest.approx(
        79577, rel=0.06
    )
    r = acquire(cfg, frames("uniform", cfg), tmp_path / "clip.cir")
    assert r.codes.item() == 4095
    curved = acquire(
        replace(cfg, compressed=True), frames("uniform", cfg), tmp_path / "diode.cir"
    )
    assert 0.5 < curved.volts.item() < 0.9


def test_deck_and_model_boundaries():
    cfg = Config(model="components", rows=4, cols=8, channels=3)
    net = build(cfg, frames("point", cfg), timing_for(cfg))
    assert net.count(" vp vn pixel ci=") == 32
    assert net.count(" filtered adc chain") == 3
    assert net.count(" 33\n") == 3 * (3 + 4) + 8
    assert ".model gate sw" not in net.lower() and "bfollower" not in net.lower()
    assert net.count(".save ") == 1 and "v(adc2)" in net
    with pytest.raises(ValueError):
        replace(cfg, channels=9)
    with pytest.raises(ValueError):
        replace(cfg, probe_col=8)


def test_identical_bank_reuse_and_probe(tmp_path):
    cfg = Config(
        model="components",
        rows=2,
        cols=6,
        channels=6,
        partitioned=True,
        probe_row=1,
        probe_col=3,
    )
    r = acquire(cfg, frames("checkerboard", cfg), tmp_path / "scan.cir")
    manifest = json.loads((tmp_path / "scan.banks.json").read_text())
    decks = [bank["deck"] for bank in manifest]
    assert (
        len(set(decks)) == 3
    )  # Two optical patterns and one extra diagnostic save list.
    assert decks[0] == decks[2] == decks[4]
    assert decks[1] == decks[5]
    assert "pd9" in r.traces
    np.testing.assert_array_equal(r.codes[:, 0], r.codes[:, 4])
    np.testing.assert_array_equal(r.codes[:, 1], r.codes[:, 5])
    assert r.codes[0, 0] < r.codes[0, 1] and r.codes[1, 0] > r.codes[1, 1]
