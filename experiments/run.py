"""Reproduce the report with python -m experiments.run [output_directory]."""

import csv
from dataclasses import replace
from pathlib import Path
import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.integrate import trapezoid
from scipy.interpolate import interp1d

from camera.adc.ideal import quantize
from camera.circuits.frontend import amplifier, frontend
from camera.circuits.pixel import MODELS
from camera.cli import save_capture
from camera.controller.timing import START
from camera.optics.scenes import frames
from camera.sensor.config import Config
from camera.simulation.acquire import acquire
from camera.simulation.backend import simulate


def plot(root, name, columns, rows, *, logx=False):
    """First two columns are sweep coordinate and series name."""
    with (root / f"{name}.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    fig, axes = plt.subplots(
        1, len(columns) - 2, figsize=(5 * (len(columns) - 2), 3.5), squeeze=False
    )
    for j, ax in enumerate(axes.flat, 2):
        for group in dict.fromkeys(row[1] for row in rows):
            subset = [row for row in rows if row[1] == group]
            ax.plot(
                [r[0] for r in subset], [r[j] for r in subset], ".-", label=str(group)
            )
        if logx:
            ax.set_xscale("log")
        ax.set(xlabel=columns[0], ylabel=columns[j])
        ax.legend(fontsize=8)
        ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(root / f"{name}.png", dpi=120)
    plt.close(fig)


def ac_bench(cfg, path):
    if cfg.model == "components":
        from camera.circuits.components import afe
        from camera.circuits.models import library

        deck = (
            "Component small-signal bench\n"
            + library()
            + afe(cfg)
            + f"""
Vbr br 0 DC 3 AC 1
Vbs bs 0 2.98
Vnom nominal 0 {cfg.reset}
Vblack black 0 {cfg.black}
Vhigh high 0 9
Vplus vp 0 7.5
Vminus vn 0 -7.5
Xafe br bs nominal black high vp vn cds pga filtered adc chain
.temp {cfg.temperature}
.save v(cds) v(pga) v(adc)
.ac dec 24 100 100meg
.end
"""
        )
        return simulate(deck, path)
    # Unipolar common-mode point with headroom even at gain 16.
    deck = (
        "Front end small signal bench\n"
        + MODELS
        + str(amplifier())
        + frontend(cfg)
        + """
Vdd vdd 0 5
Vr br 0 DC 3 AC 1
Vs bs 0 2.98
.save v(cds) v(pga) v(adc)
.ac dec 24 100 100meg
.end
"""
    )
    return simulate(deck, path)


def cutoff(freq, magnitude):
    idx = np.flatnonzero(magnitude < magnitude[0] / np.sqrt(2))[0]
    window = slice(idx - 1, idx + 1)
    return float(
        np.exp(
            interp1d(magnitude[window], np.log(freq[window]))(magnitude[0] / np.sqrt(2))
        )
    )


def run(root: Path, image_config: Config | None = None):
    decks = root / "decks"
    decks.mkdir(parents=True, exist_ok=True)
    image_config = image_config or Config()
    base = Config(rows=1, cols=1, model=image_config.model)
    summary = []

    def capture(name, cfg, level=1.0, sequence=None):
        if sequence is None:
            sequence = [(0.0, np.full((cfg.rows, cfg.cols), level))]
        return acquire(cfg, sequence, decks / f"{name}.cir")

    rows = []
    for cap in (50e-12, 100e-12, 220e-12):
        for ms in (1, 3, 5, 10, 15, 25, 50, 1000):
            cfg = replace(base, cint=cap, exposure=ms / 1000)
            r = capture(f"integration_{cap}_{ms}", cfg)
            rows.append(
                (
                    ms,
                    f"{cap*1e12:g} pF",
                    np.interp(START + cfg.exposure, r.traces["time"], r.traces["pd0"]),
                    r.volts.item(),
                    cfg.full_power
                    * cfg.responsivity
                    * cfg.exposure
                    / (
                        cap
                        + (
                            4e-12
                            if cfg.model == "reference"
                            else 11.73e-12 / np.sqrt(1 + cfg.reset / 0.7)
                        )
                    ),
                )
            )
    plot(
        root,
        "01_03_04_integration",
        (
            "exposure (ms)",
            "integration C",
            "diode cathode (V)",
            "ADC input (V)",
            "ideal unclamped swing (V)",
        ),
        rows,
        logx=True,
    )
    summary.append(
        f"100 pF, 10 ms full light gives {rows[11][3]:.5f} V at the ADC. At 1 s it gives {rows[15][3]:.5f} V."
    )

    rows = []
    for temp, mode in [(27, False), (0, True), (27, True), (50, True)]:
        for level in (0, 0.01, 0.03, 0.1, 0.25, 0.5, 0.75, 1):
            cfg = replace(base, temperature=temp, compressed=mode)
            r = capture(f"power_{temp}_{mode}_{level}", cfg, level)
            rows.append(
                (
                    45 * level,
                    f'{"diode" if mode else "linear"} {temp} °C',
                    r.volts.item(),
                )
            )
    plot(
        root,
        "02_power_compression",
        ("power (nW/pixel)", "mode", "ADC input (V)"),
        rows,
    )
    summary.append(
        f"Full light, diode mode gives {rows[15][2]:.4f}, {rows[23][2]:.4f}, {rows[31][2]:.4f} V at 0, 27, 50 °C."
    )

    rows = []
    for leakage in (1e8, 1e10, 1e12):
        for slot in (40e-6, 1e-3, 10e-3):
            cfg = replace(base, slot=slot, leakage=leakage)
            r = capture(f"hold_{leakage}_{slot}", cfg, 0.25)
            t = r.traces["time"]
            a, b = np.interp(
                [START + cfg.exposure + 50e-9, r.samples[0]], t, r.traces["x0.hs"]
            )
            dt = r.samples[0] - (START + cfg.exposure + 50e-9)
            rows.append(
                (
                    dt * 1000,
                    f"{leakage:g} Ω",
                    (a - b) * 1000,
                    1000 * a * (-np.expm1(-dt / (cfg.hold * leakage))),
                )
            )
    plot(
        root,
        "05_storage",
        ("hold time (ms)", "leakage R", "measured droop (mV)", "ideal RC droop (mV)"),
        rows,
        logx=True,
    )

    dark_reference = capture("dark_baseline", base, 0.0).volts.item()
    rows = []
    for tau in (1e-6, 2e-6, 5e-6):
        for slot in (2e-6, 5e-6, 10e-6, 20e-6, 40e-6):
            cfg = replace(base, rows=2, cols=2, slot=slot, filter_tau=tau)
            r = capture(f"mux_{tau}_{slot}", cfg, sequence=frames("checkerboard", cfg))
            # Compare the bright-to-dark transition against its settled bus voltage.
            begin = r.samples[-1] - 0.9 * slot
            time = r.traces["time"]
            window = np.r_[
                begin, time[(time > begin) & (time < r.samples[-1])], r.samples[-1]
            ]
            bus = np.interp(window, time, r.traces["bs"])
            residual = np.abs(bus - bus[-1])
            outside = np.flatnonzero(residual > 1e-3)
            settling = 0.0
            if len(outside):
                i = outside[-1]
                fraction = (residual[i] - 1e-3) / (residual[i] - residual[i + 1])
                settling = window[i] - begin + fraction * (window[i + 1] - window[i])
            rows.append(
                (
                    slot * 1e6,
                    f"τ={tau*1e6:g} μs",
                    1e3 * (r.volts[-1, -1] - dark_reference),
                    settling * 1e9,
                )
            )
    plot(
        root,
        "06_09_readout",
        (
            "slot (μs)",
            "filter",
            "dark residual vs slow baseline (mV)",
            "bus settling to 1 mV (ns)",
        ),
        rows,
    )
    summary.append(
        f"At τ=2 μs the bright-to-dark ADC residual goes from {rows[5][2]:.2f} mV at a 2 μs slot to {rows[9][2]:.3f} mV at 40 μs."
    )

    rows, gains = [], []
    for gain in (1, 2, 4, 8, 16):
        cfg = replace(base, gain=gain)
        d = ac_bench(cfg, decks / f"ac_{gain}.cir")
        f = d["frequency"].real
        pga = abs(d["pga"] / d["cds"])
        filt = abs(d["adc"] / d["pga"])
        gains.append((gain, "SPICE", pga[0], cutoff(f, pga), cutoff(f, filt)))
        rows.extend(
            (hz, f"{gain}×", 20 * np.log10(g), 20 * np.log10(h))
            for hz, g, h in zip(f, pga, filt)
        )
    plot(
        root,
        "07_09_frequency",
        ("frequency (Hz)", "gain", "PGA gain (dB)", "filter + driver (dB)"),
        rows,
        logx=True,
    )
    plot(
        root,
        "07_gain",
        (
            "nominal gain",
            "model",
            "measured gain (V/V)",
            "PGA bandwidth (Hz)",
            "filter cutoff (Hz)",
        ),
        gains,
    )
    summary.append(
        f"Gain 16 measures {gains[-1][2]:.4f} V/V with {gains[-1][3]/1000:.1f} kHz bandwidth. Filter and driver cutoff is {gains[-1][4]/1000:.1f} kHz."
    )

    noise_rows = []
    for tau in (1e-6, 2e-6, 5e-6):
        d = ac_bench(replace(base, filter_tau=tau), decks / f"filter_{tau}.cir")
        f = d["frequency"].real
        transfer = abs(d["adc"] / d["pga"])
        # Extend measured, flat passband down to DC. Tail beyond 100 MHz is negligible.
        enbw = f[0] + trapezoid((transfer / transfer[0]) ** 2, f)
        noise_rows.append((tau * 1e6, "AC", cutoff(f, transfer), enbw))
    plot(
        root,
        "09_noise_bandwidth",
        (
            "RC time constant (μs)",
            "model",
            "cutoff (Hz)",
            "equivalent noise bandwidth (Hz)",
        ),
        noise_rows,
    )

    rows = []
    for cds in (False, True):
        for offset in (-0.05, -0.01, 0, 0.01, 0.05):
            r = capture(
                f"cds_{cds}_{offset}", replace(base, cds=cds, reset_offset=offset), 0.25
            )
            rows.append(
                (offset * 1000, "CDS" if cds else "nominal reference", r.volts.item())
            )
    plot(root, "08_cds", ("reset offset (mV)", "reference", "ADC input (V)"), rows)
    summary.append(
        f"A 100 mV reset sweep changes the bypass output by {abs(rows[4][2]-rows[0][2])*1000:.3f} mV and CDS output by {abs(rows[9][2]-rows[5][2])*1000:.4f} mV."
    )

    rows = []
    gallery, panels = plt.subplots(1, 4, figsize=(10, 3), constrained_layout=True)
    for panel, (exp, gain) in zip(
        panels, [(0.003, 1), (0.01, 1), (0.003, 4), (0.01, 8)]
    ):
        cfg = replace(image_config, exposure=exp, gain=gain)
        directory = root / f"image_{exp}_{gain}"
        r = acquire(cfg, frames("horizontal", cfg), directory / "camera.cir")
        save_capture(directory, cfg, r)
        im = panel.imshow(
            r.codes, vmin=0, vmax=2**cfg.bits - 1, cmap="gray", interpolation="nearest"
        )
        panel.set_title(f"{exp*1000:g} ms, {gain}×")
        panel.set_axis_off()
        rows.extend(
            (x, f"{exp*1000:g} ms ×{gain}", v, int(q))
            for x, (v, q) in enumerate(zip(r.volts[0], r.codes[0]))
        )
    gallery.colorbar(im, ax=panels.tolist(), shrink=0.65, label="12-bit ADC code")
    gallery.savefig(root / "12_frames.png", dpi=140)
    plt.close(gallery)
    plot(
        root,
        "12_images",
        ("column", "exposure and gain", "first row (V)", "ADC code"),
        rows,
    )
    summary.append(
        f"At 10 ms and 8×, the bright column reaches {r.volts[0,-1]:.4f} V and converts to code {r.codes[0,-1]}."
    )

    rows = []
    ref = capture(
        "adc_gradient",
        replace(base, cols=32),
        sequence=frames("horizontal", replace(base, cols=32)),
    )
    for bits in (8, 10, 12):
        v = ref.volts.ravel()
        lsb = base.adc_range / 2**bits
        err = (quantize(v, bits, base.adc_range) + 0.5) * lsb - v
        rows.extend((a, f"{bits} bits", e * 1000) for a, e in zip(v, err))
        summary.append(
            f"{bits}-bit midpoint reconstruction RMS error on the 32 samples is {np.sqrt(np.mean(err**2))*1000:.4f} mV."
        )
    plot(root, "10_adc", ("ADC input (V)", "resolution", "midpoint error (mV)"), rows)

    cfg = replace(base, rows=2, cols=2)
    init = frames("horizontal", cfg)
    a = capture("shutter_static", cfg, sequence=init)
    b = capture(
        "shutter_flash",
        cfg,
        sequence=init + [(START + cfg.exposure + 1e-6, 1 - init[0][1])],
    )
    rows = [
        (i, label, v)
        for label, r in [("static", a), ("inverted after close", b)]
        for i, v in enumerate(r.volts.flat)
    ]
    plot(root, "11_shutter", ("pixel", "post-shutter light", "sample (V)"), rows)
    summary.append(
        f"Maximum post-shutter inversion effect is {np.max(abs(a.volts-b.volts))*1e6:.3f} μV."
    )
    (root / "summary.txt").write_text("\n".join(summary) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the twelve camera experiments")
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument(
        "--model", choices=["reference", "components"], default="reference"
    )
    parser.add_argument("--rows", type=int, default=10, help="image sweep height")
    parser.add_argument("--cols", type=int, default=10, help="image sweep width")
    parser.add_argument(
        "--channels", type=int, default=1, help="image sweep readout channels"
    )
    parser.add_argument(
        "--partitioned",
        action="store_true",
        help="solve the image sweep by hardware bank",
    )
    args = parser.parse_args()
    cfg = Config(
        model=args.model,
        rows=args.rows,
        cols=args.cols,
        channels=args.channels,
        partitioned=args.partitioned,
    )
    root = args.output or Path(
        "results/phase2/characterization"
        if args.model == "components"
        else "results/characterization"
    )
    run(root, cfg)
