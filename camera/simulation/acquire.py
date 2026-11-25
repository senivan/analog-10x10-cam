from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from PySpice.Spice.Netlist import Circuit

from camera.adc.ideal import quantize
from camera.circuits import components
from camera.circuits.frontend import amplifier, frontend
from camera.circuits.pixel import MODELS, pixel
from camera.controller.timing import EDGE, START, Timing, gate
from camera.optics.scenes import current_source
from camera.sensor.config import Config
from camera.simulation.backend import simulate


@dataclass
class Capture:
    traces: dict[str, np.ndarray]
    samples: np.ndarray
    volts: np.ndarray
    codes: np.ndarray
    seconds: float


def optical_arrays(cfg, frames):
    times = np.asarray([t for t, _ in frames])
    images = np.asarray([f for _, f in frames], dtype=float)
    if (
        not len(times)
        or times[0] != 0
        or not np.isfinite(times).all()
        or np.any(np.diff(times) <= EDGE)
        or images.shape != (len(times), cfg.rows, cfg.cols)
        or not np.isfinite(images).all()
        or images.min() < 0
        or images.max() > 1
    ):
        raise ValueError(
            "Expected increasing frame times from zero and linear images in [0,1]"
        )
    return times, images


def build(cfg: Config, frames: list[tuple[float, np.ndarray]], timing: Timing) -> str:
    times, images = optical_arrays(cfg, frames)
    if cfg.model == "components":
        return components.deck(cfg, images, times, range(cfg.channels))
    probe = cfg.cols * cfg.probe_row + cfg.probe_col
    c = Circuit("Global shutter discrete camera")
    c.subcircuit(pixel())
    c.subcircuit(amplifier())
    c.V("dd", "vdd", 0, cfg.supply)
    c.V("r", "vr", 0, cfg.reset + cfg.reset_offset)
    c.V("rst", "rst", 0, gate(0, START))
    c.V("rg", "rg", 0, gate(5e-6, START - 1e-6))
    c.V("sg", "sg", 0, gate(timing.close - 8e-6, timing.close))
    rng = np.random.default_rng(cfg.seed)
    for i, levels in enumerate(images.reshape(len(times), -1).T):
        c.I(f"photo{i}", f"pd{i}", 0, current_source(times, levels, cfg))
        t = timing.read + i * cfg.slot
        c.V(f"sel{i}", f"sel{i}", 0, gate(t, t + cfg.slot - 0.1e-6))
        ci, ch = 1 + rng.uniform(-cfg.tolerance, cfg.tolerance, 2)
        c.X(
            i,
            "pixel",
            f"pd{i}",
            "vr",
            "rst",
            "rg",
            "sg",
            f"sel{i}",
            "br",
            "bs",
            ci=cfg.cint * ci,
            ch=cfg.hold * ch,
            rl=cfg.leakage,
            dark=cfg.dark,
        )
    raw = (
        MODELS
        + frontend(cfg)
        + f"""
Rbr br 0 1T
Rbs bs 0 1T
Cbr br 0 30p
Cbs bs 0 30p
.temp {cfg.temperature}
.options gmin=1e-15 reltol=2e-5 abstol=1e-14 vntol=1e-7 method=gear
.save v(pd{probe}) v(x{probe}.hr) v(x{probe}.hs) v(br) v(bs) v(cds) v(pga) v(filtered) v(adc)
.tran {cfg.slot/10} {timing.end} 0 {max(cfg.exposure/30,cfg.slot/10)}
"""
    )
    return str(c) + raw + ".end\n"


def acquire(
    cfg: Config,
    frames: list[tuple[float, np.ndarray]],
    path: Path,
    *,
    simulator=simulate,
) -> Capture:
    start = perf_counter()
    if cfg.model == "components":
        timing = components.timing_for(cfg)
        times, images = optical_arrays(cfg, frames)
        groups = (
            [[k] for k in range(cfg.channels)]
            if cfg.partitioned
            else [range(cfg.channels)]
        )
        volts = np.empty((cfg.rows, cfg.cols))
        samples = np.empty_like(volts)
        slots = timing.samples.reshape(cfg.rows, -1)
        traces = {}
        cache = {}
        manifest = []
        factors = 1 + np.random.default_rng(cfg.seed).uniform(
            -cfg.tolerance, cfg.tolerance, (cfg.rows, cfg.cols, 2)
        )
        for group in groups:
            local = cfg.partitioned
            dest = (
                path
                if len(groups) == 1
                else path.with_name(f"{path.stem}.bank{group[0]}{path.suffix}")
            )
            net = components.deck(
                cfg, images, times, group, local=local, factors=factors
            )
            digest = sha256(net.encode()).digest()
            if local and digest in cache:
                previous, values = cache[digest]
                cols = components.columns(cfg, group[0])
                volts[:, cols] = values
                samples[:, cols] = slots[:, : len(cols)]
                manifest.append({"bank": group[0], "deck": previous.name})
                continue
            data = simulator(net, dest)
            check_time(data, timing, dest)
            for k in group:
                label = 0 if local else k
                cols = components.columns(cfg, k)
                apertures = slots[:, : len(cols)]
                samples[:, cols] = apertures
                values = np.interp(apertures, data["time"], data[f"adc{label}"])
                volts[:, cols] = values
                if local:
                    cache[digest] = (dest, values)
                    manifest.append({"bank": k, "deck": dest.name})
                if cfg.probe_col in cols:
                    probe = cfg.probe_row * cfg.cols + cfg.probe_col
                    index = cfg.probe_row * len(cols) + cfg.probe_col - cols.start
                    traces = {"time": data["time"]}
                    for node in ("br", "bs", "cds", "pga", "filtered", "adc"):
                        traces[node] = data[f"{node}{label}"]
                    for target, source in [
                        (f"pd{probe}", f"pd{index}"),
                        (f"x{probe}.hr", f"x{index}.hr"),
                        (f"x{probe}.hs", f"x{index}.hs"),
                    ]:
                        traces[target] = data[f"xb{label}.{source}"]
        if cfg.partitioned:
            path.with_suffix(".banks.json").write_text(
                json.dumps(manifest, indent=2) + "\n"
            )
        samples = samples.ravel()
    else:
        timing = Timing(cfg.exposure, cfg.slot, cfg.rows * cfg.cols)
        traces = simulator(build(cfg, frames, timing), path)
        check_time(traces, timing, path)
        samples = timing.samples
        volts = np.interp(samples, traces["time"], traces["adc"]).reshape(
            cfg.rows, cfg.cols
        )
    return Capture(
        traces,
        samples,
        volts,
        quantize(volts, cfg.bits, cfg.adc_range),
        perf_counter() - start,
    )


def check_time(data, timing, path):
    time = data["time"]
    if time[-1] < timing.end * (1 - 1e-9) or np.any(np.diff(time) <= 0):
        raise RuntimeError(f"Incomplete transient in {path}")
