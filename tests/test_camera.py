from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from camera.adc.ideal import quantize
from camera.controller.timing import START
from camera.optics.scenes import frames, scene
from camera.sensor.config import Config
from camera.simulation.acquire import acquire
from experiments.run import ac_bench, cutoff


@pytest.fixture
def single(tmp_path):
    cfg = Config(rows=1, cols=1, leakage=1e9, slot=0.001)
    return cfg, acquire(cfg, frames("uniform", cfg), tmp_path / "pixel.cir")


def test_integrator_storage(single):
    cfg, r = single
    t = r.traces["time"]
    at = lambda node, t0: np.interp(t0, t, r.traces[node])
    swing = cfg.full_power * cfg.responsivity * cfg.exposure / (cfg.cint + 4e-12)
    # 1 mV budget includes deterministic dark, bias and off-state current.
    assert at("pd0", START) - at("pd0", START + cfg.exposure) == pytest.approx(
        swing, abs=0.001
    )
    # RC acquisition at one time constant following the 1.7 V gate crossing.
    switch_on = 5e-6 + 20e-9 * 1.7 / 3.3
    initial = at("x0.hr", 5e-6)
    target = at("pd0", 5e-6) + 100e-6
    assert at("x0.hr", switch_on + 100e-9) == pytest.approx(
        target + (initial - target) * np.exp(-1), abs=0.04
    )
    begin = START + cfg.exposure + 50e-9
    dt = r.samples.item() - begin
    v0 = at("x0.hs", begin)
    expected = v0 * (-np.expm1(-dt / (cfg.leakage * cfg.hold)))
    assert v0 - at("x0.hs", begin + dt) == pytest.approx(expected, abs=2e-6)


@pytest.mark.parametrize("gain", [1, 2, 4, 8, 16])
def test_amplifiers(tmp_path, gain):
    cfg = Config(gain=gain)
    d = ac_bench(cfg, tmp_path / "ac.cir")
    f = d["frequency"].real
    pga = abs(d["pga"] / d["cds"])
    assert abs(d["cds"][0]) == pytest.approx(1, rel=0.001)
    assert pga[0] == pytest.approx(gain, rel=0.001)
    assert cutoff(f, pga) == pytest.approx(4e6 / gain, rel=0.02)
    assert cutoff(f, abs(d["adc"] / d["pga"])) == pytest.approx(
        1 / (2 * np.pi * cfg.filter_tau), rel=0.02
    )


@pytest.mark.parametrize("size", [2, 10])
def test_scan_and_adc_provenance(tmp_path, size):
    cfg = Config(rows=size, cols=size)
    inputs = frames("checkerboard", cfg)
    r = acquire(cfg, inputs, tmp_path / "camera.cir")
    expected = cfg.black + inputs[0][
        1
    ] * cfg.full_power * cfg.responsivity * cfg.exposure / (cfg.cint + 4e-12)
    np.testing.assert_allclose(r.volts, expected, atol=0.001)
    sampled = np.interp(r.samples, r.traces["time"], r.traces["adc"])
    np.testing.assert_array_equal(
        r.codes.ravel(), quantize(sampled, cfg.bits, cfg.adc_range)
    )


def test_global_shutter_and_cds(tmp_path):
    cfg = Config(rows=2, cols=2)
    static = frames("horizontal", cfg)
    changed = static + [(START + cfg.exposure + 100e-9, 1 - static[0][1])]
    a = acquire(cfg, static, tmp_path / "static.cir")
    b = acquire(cfg, changed, tmp_path / "changed.cir")
    np.testing.assert_allclose(a.volts, b.volts, atol=cfg.adc_range / 4096 / 4)
    shifted = replace(cfg, reset_offset=-0.05)
    c = acquire(shifted, static, tmp_path / "cds.cir")
    d = acquire(replace(shifted, cds=False), static, tmp_path / "nom.cir")
    np.testing.assert_allclose(a.volts, c.volts, atol=0.0005)
    np.testing.assert_allclose(d.volts - c.volts, 0.05, atol=0.001)


@pytest.mark.parametrize("bits", [8, 10, 12])
def test_adc(bits):
    span = 3.3
    lsb = span / 2**bits
    v = np.array([-1, 0, 0.99 * lsb, 1.01 * lsb, span, 4])
    assert quantize(v, bits, span).tolist() == [0, 0, 0, 1, 2**bits - 1, 2**bits - 1]


def test_optics(tmp_path):
    name = tmp_path / "input.png"
    Image.fromarray(np.array([[[128, 128, 128], [255, 0, 0]]], dtype=np.uint8)).save(
        name
    )
    np.testing.assert_allclose(scene(str(name), (1, 2)), [[0.21586, 0.2126]], atol=1e-5)
    assert len(frames("moving", Config())) == 5


def test_gain_and_compressor_limits(tmp_path):
    cfg = Config(rows=1, cols=1, gain=8)
    seq = frames("uniform", cfg)
    linear = acquire(cfg, seq, tmp_path / "saturated.cir")
    compressed = acquire(
        replace(cfg, compressed=True), seq, tmp_path / "compression.cir"
    )
    assert 4.9 < linear.volts.item() < cfg.supply
    assert linear.codes.item() == 4095
    assert 0.4 < compressed.volts.item() < 0.8


def test_moving_exposure(tmp_path):
    cfg = Config(rows=2, cols=5)
    seq = frames("moving", cfg)
    r = acquire(cfg, seq, tmp_path / "motion.cir")
    # Four equal exposure intervals. The fifth position arrives at shutter closure.
    mean = np.mean([frame for _, frame in seq[:4]], axis=0)
    swing = cfg.full_power * cfg.responsivity * cfg.exposure / (cfg.cint + 4e-12)
    np.testing.assert_allclose(r.volts, cfg.black + swing * mean, atol=0.001)


def test_divider(tmp_path):
    from camera.simulation.backend import simulate

    result = simulate(
        "2 V divider\nV1 supply 0 2\nR1 supply out 1k\nR2 out 0 1k\n.save v(out)\n.op\n.end\n",
        tmp_path / "divider.cir",
    )
    assert result["out"].item() == pytest.approx(1)
