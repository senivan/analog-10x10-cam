"""Reproduce component/reference acquisition, retention and bandwidth comparisons."""

import argparse
from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from camera.cli import save_capture
from camera.controller.timing import START
from camera.optics.scenes import frames
from camera.sensor.config import Config
from camera.simulation.acquire import acquire
from experiments.run import plot, ac_bench, cutoff


def pedestal(root: Path):
    """Measure gate-opening steps and offset transmission on one quarter-lit pixel."""
    rows = []
    for model in ("reference", "components"):
        for cds in (True, False):
            for offset in (-0.05, 0, 0.05):
                cfg = Config(rows=1, cols=1, model=model, cds=cds, reset_offset=offset)
                r = acquire(
                    cfg,
                    [(0.0, np.full((1, 1), 0.25))],
                    root / "decks" / f"pedestal_{model}_{cds}_{offset}.cir",
                )
                close = START + cfg.exposure
                reset = START - 5e-6 if model == "components" else START

                def step(node, t):
                    a, b = np.interp(
                        [t - 50e-9, t + 100e-9], r.traces["time"], r.traces[node]
                    )
                    return 1000 * (b - a)

                rows.append(
                    (
                        offset * 1000,
                        f'{model} {"CDS" if cds else "bypass"}',
                        r.volts.item(),
                        step("pd0", reset),
                        step("x0.hs", close),
                    )
                )
    plot(
        root,
        "pedestal",
        (
            "reset offset (mV)",
            "model",
            "ADC (V)",
            "reset-opening step (mV)",
            "hold-opening step (mV)",
        ),
        rows,
    )


def storage_tradeoff(root: Path):
    """A full 16-row column reveals the trade between acquisition and bus loading."""
    rows = []
    for capacitance in (1e-9, 2.2e-9, 4.7e-9):
        cfg = Config(
            model="components", rows=16, cols=1, hold=capacitance, probe_row=15
        )
        r = acquire(
            cfg,
            frames("checkerboard", cfg),
            root / "decks" / f"column_hold_{capacitance:g}.cir",
        )
        close = START + cfg.exposure
        pd = np.interp(close, r.traces["time"], r.traces["pd15"])
        stored = np.interp(close + 1e-6, r.traces["time"], r.traces["x15.hs"])
        rows.append(
            (
                capacitance * 1e9,
                "16 rows",
                (r.volts[-2, 0] - r.volts[0, 0]) * 1e3,
                (stored - pd) * 1e3,
                r.volts[-1, 0] - r.volts[-2, 0],
            )
        )
    plot(
        root,
        "column_hold",
        (
            "storage (nF)",
            "bank",
            "late minus first dark (mV)",
            "bright hold minus cathode (mV)",
            "late bright–dark contrast (V)",
        ),
        rows,
    )


def run(root: Path, rows: int = 4, cols: int = 8):
    root.mkdir(parents=True, exist_ok=True)
    pedestal(root)
    storage_tradeoff(root)
    exposure, storage, gain, settling, quality, modes = [], [], [], [], [], []
    images = []
    for model in ("reference", "components"):
        base = Config(model=model, rows=1, cols=1)

        def capture(cfg, name, seq=None, scene="uniform"):
            return acquire(
                cfg,
                frames(scene, cfg) if seq is None else seq,
                root / "decks" / f"{model}_{name}.cir",
            )

        for ms in (1, 3, 6, 10, 15, 25, 50):
            cfg = replace(base, exposure=ms * 1e-3)
            r = capture(cfg, f"exp{ms}")
            end = START + cfg.exposure
            pd = np.interp(end, r.traces["time"], r.traces["pd0"])
            held = np.interp(end + 1e-6, r.traces["time"], r.traces["x0.hs"])
            exposure.append((ms, model, pd, r.volts.item(), 1e3 * (held - pd)))
        for g in (1, 2, 4, 8, 16):
            d = ac_bench(replace(base, gain=g), root / "decks" / f"{model}_ac{g}.cir")
            f = d["frequency"].real
            pg = abs(d["pga"] / d["cds"])
            gain.append(
                (
                    g,
                    model,
                    pg[0],
                    cutoff(f, pg) / 1e3,
                    cutoff(f, abs(d["adc"] / d["pga"])) / 1e3,
                )
            )
        for slot in (3e-6, 10e-6, 40e-6, 100e-6):
            cfg = replace(base, rows=2, cols=3, slot=slot)
            # Select the last pixel. Its immediate predecessor is bright.
            cfg = replace(cfg, probe_row=1, probe_col=2)
            seq = [(0.0, np.array([[0, 1, 0], [0, 1, 0]]))]
            r = capture(cfg, f"speed{slot}", seq)
            t = r.traces["time"]
            first = r.samples[-1] - 0.9 * slot
            window = np.r_[first, t[(t > first) & (t < r.samples[-1])], r.samples[-1]]
            bus = np.interp(window, t, r.traces["bs"])
            outside = np.flatnonzero(abs(bus - bus[-1]) > 0.001)
            ns = (window[outside[-1] + 1] - first) * 1e9 if len(outside) else 0
            settling.append(
                (slot * 1e6, model, ns, 1000 * (r.volts[-1, -1] - r.volts[0, 0]))
            )
        for position in (0, 1, 3, 5):
            cfg = replace(
                base, rows=6, cols=1, probe_row=position, slot=0.0005, leakage=1e10
            )
            r = capture(cfg, f"hold{position}", [(0.0, np.full((6, 1), 0.25))])
            held = r.traces[f"x{position}.hs"]
            t = r.traces["time"]
            t0 = START + cfg.exposure + 1e-6
            v0, v1 = np.interp(
                [t0, r.samples[position] - 0.9 * cfg.slot - 50e-9], t, held
            )
            storage.append((position, model, 1000 * (v0 - v1), r.volts[position, 0]))
        cfg = replace(base, rows=rows, cols=cols)
        source = frames("horizontal", cfg)
        r = capture(cfg, "image", source)
        directory = root / model
        directory.mkdir(exist_ok=True)
        save_capture(directory, cfg, r)
        images.append(r.codes)
        # Fixed full-scale calibration for both cameras, without fitting each frame.
        target = 0.1 + source[0][1] * (0.45 * 45e-9 * 0.01 / 104e-12)
        quality.append(
            (
                1,
                model,
                100 * (int(r.codes.max()) - int(r.codes.min())) / 4095,
                np.sqrt(np.mean((r.volts - target) ** 2)) * 1000,
            )
        )
        for comp in (False, True):
            for light in (0, 0.25, 0.5, 1):
                c = replace(base, compressed=comp)
                r = capture(c, f"mode{comp}_{light}", [(0.0, np.array([[light]]))])
                modes.append(
                    (
                        light * 45,
                        model + (" compressed" if comp else " linear"),
                        r.volts.item(),
                    )
                )
    for name, headings, measurements in [
        (
            "exposure",
            (
                "exposure (ms)",
                "model",
                "integration node (V)",
                "ADC (V)",
                "hold minus cathode (mV)",
            ),
            exposure,
        ),
        (
            "storage",
            ("readout row", "model", "pre-select droop (mV)", "ADC (V)"),
            storage,
        ),
        (
            "gain",
            (
                "setting",
                "model",
                "gain (V/V)",
                "PGA bandwidth (kHz)",
                "filter bandwidth (kHz)",
            ),
            gain,
        ),
        (
            "settling",
            ("pixel slot (μs)", "model", "bus within 1 mV (ns)", "dark residual (mV)"),
            settling,
        ),
        (
            "quality",
            (
                "gain setting",
                "model",
                "ADC span used (%)",
                "RMS vs nominal calibration (mV)",
            ),
            quality,
        ),
        ("compression", ("power (nW)", "mode", "ADC voltage (V)"), modes),
    ]:
        plot(root, name, headings, measurements)
    fig, axes = plt.subplots(1, 2, figsize=(7, 2.5), layout="constrained")
    for ax, im, label in zip(axes, images, ("Reference", "Components")):
        ax.imshow(im, vmin=0, vmax=4095, cmap="gray", interpolation="nearest")
        ax.set_title(label)
        ax.set_axis_off()
    fig.savefig(root / "frames.png", dpi=140)
    plt.close(fig)
    cfg = Config(
        rows=3,
        cols=5,
        channels=2,
        model="components",
        probe_row=2,
        probe_col=4,
        tolerance=0.01,
    )
    seq = frames("moving", cfg)
    mono = acquire(cfg, seq, root / "decks" / "monolithic.cir")
    split = acquire(
        replace(cfg, partitioned=True), seq, root / "decks" / "partition.cir"
    )
    diff = split.volts - mono.volts
    rows = [(i, "bank − monolithic", v * 1e6) for i, v in enumerate(diff.flat)]
    plot(root, "partition", ("row-major pixel", "configuration", "error (μV)"), rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output", nargs="?", type=Path, default=Path("results/phase2/comparison")
    )
    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--cols", type=int, default=8)
    args = parser.parse_args()
    run(args.output, args.rows, args.cols)
