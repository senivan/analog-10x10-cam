"""Banked two-bus readout. A bank spans contiguous columns and all rows."""

import numpy as np
from PySpice.Spice.Netlist import Circuit

from camera.circuits.models import library
from camera.controller.timing import START, EDGE, Timing, pwl
from camera.optics.scenes import current_source
from camera.sensor.config import Config

PIXEL = """
.subckt pixel pd vr rst rg sg row br bs vp vn params: ci=100p ch=1n rl=1T dark=70p
Xphoto 0 pd pin idark={dark}
Cint pd 0 {ci}
Rint pd 0 10T
Xreset vr pd rst pass
Xbuf pd out vp vn out TL081
Risol out drive 100
XsampleR drive hr rg pass
XsampleS drive hs sg pass
Chr hr 0 {ch}
Chs hs 0 {ch}
Rhr hr 0 {rl}
Rhs hs 0 {rl}
XrowR hr br row pass
XrowS hs bs row pass
.ends pixel
"""


def afe(cfg: Config) -> str:
    body = """
.subckt chain br bs nominal black vhi vp vn cds pga filtered adc
Xbr br rb vp vn rb TL081
Xbs bs sb vp vn sb TL081
"""
    for name, a, b, enabled in [
        ("cds", "rb", "ref", cfg.cds),
        ("bypass", "nominal", "ref", not cfg.cds),
        ("linear", "pga", "mode", not cfg.compressed),
        ("comp", "compout", "mode", cfg.compressed),
    ]:
        body += f'X{name} {a} {b} {"vhi" if enabled else "0"} pass\n'
    body += """
Rp ref plus 100k
Rb plus black 100k
Rm sb minus 100k
Rf cds minus 100k
Xdiff plus minus vp vn cds TL081
Xgain cds fb vp vn pga TL081
"""
    body += (
        f'Xbottom bot black {"vhi" if cfg.gain!=1 else "0"} pass\nRground fb bot 100k\n'
    )
    for gain in (1, 2, 4, 8, 16):
        body += f"Rgain{gain} pga tap{gain} {max(1,(gain-1)*100000)}\n"
        body += f'Xgain{gain} tap{gain} fb {"vhi" if cfg.gain==gain else "0"} pass\n'
    return (
        body
        + f"""
Rcomp pga knee 10k
Xdiode knee black 1N4148
Xknee knee compout vp vn compout TL081
Rfilter mode filt 10k
Cfilter filt 0 {cfg.filter_tau/10000}
Xfilter filt filtered vp vn filtered TL081
Xdriver filtered driven vp vn driven TL081
Riso driven adc 47
Cadc adc 0 20p
Radc adc 0 10meg
.ends chain
"""
    )


def columns(cfg: Config, k: int) -> range:
    # Balanced contiguous banks. Shorter banks idle in the last slot per row.
    q, r = divmod(cfg.cols, cfg.channels)
    start = k * q + min(k, r)
    return range(start, start + q + (k < r))


def timing_for(cfg: Config) -> Timing:
    return Timing(cfg.exposure, cfg.slot, cfg.rows * len(columns(cfg, 0)))


def clock(intervals):
    points = [(0.0, 0.0)]
    for a, b in intervals:
        if a == 0:
            points = [(0.0, 9.0)]
        else:
            points.extend([(a, 0.0), (a + EDGE, 9.0)])
        points.extend([(b, 9.0), (b + EDGE, 0.0)])
    return pwl(points)


def ref_divider(name: str, voltage: float, cfg: Config) -> str:
    # 10k potentiometer from local regulated supply, buffered wiper.
    fraction = voltage / cfg.supply
    return (
        f"R{name}top rail w{name} {max(.001,1e4*(1-fraction))}\n"
        f"R{name}bot w{name} 0 {max(.001,1e4*fraction)}\n"
        f"X{name} w{name} buf{name} vp vn buf{name} TL081\nRiso{name} buf{name} {name} 100\n"
    )


def bank(cfg, k, label, levels, times, factors, timing):
    cols = columns(cfg, k)
    width = len(columns(cfg, 0))
    lines = [
        f".subckt bank{label} adc cds pga filtered br bs",
        f"Vrail rail 0 {cfg.supply}",
        "Vplus vp 0 7.5",
        "Vminus vn 0 -7.5",
        "Vlogic high 0 9",
    ]
    for name, voltage in [
        ("vr", cfg.reset + cfg.reset_offset),
        ("nominal", cfg.reset),
        ("black", cfg.black),
    ]:
        lines.append(ref_divider(name, voltage, cfg))

    def control(name, intervals):
        lines.extend(
            [f"V{name} src{name} 0 {clock(intervals)}", f"R{name} src{name} {name} 33"]
        )

    # Reference aperture ends after reset release, so its injected charge is sampled.
    control("rst", [(0, START - 5e-6)])
    control("rg", [(1e-6, START)])
    control("sg", [(timing.close - 8e-6, timing.close)])
    for r in range(cfg.rows):
        begin = timing.read + r * width * cfg.slot
        control(f"row{r}", [(begin, begin + width * cfg.slot - 0.1e-6)])
    for j, c in enumerate(cols):
        intervals = []
        for r in range(cfg.rows):
            begin = timing.read + (r * width + j) * cfg.slot
            intervals.append((begin, begin + cfg.slot - 0.1e-6))
        control(f"col{j}", intervals)
        for bus in ("br", "bs"):
            lines.append(f"Xmux{bus}{j} {bus}{j}_0 {bus} col{j} pass")
        for r in range(cfg.rows):
            i = r * len(cols) + j
            lines.append(f"Iphoto{i} pd{i} 0 {current_source(times,levels[:,r,c],cfg)}")
            lines.append(
                f"X{i} pd{i} vr rst rg sg row{r} br{j}_{r} bs{j}_{r} vp vn pixel "
                f"ci={cfg.cint*factors[r,c,0]} ch={cfg.hold*factors[r,c,1]} rl={cfg.leakage} dark={cfg.dark}"
            )
            for bus in ("br", "bs"):
                node = f"{bus}{j}_{r}"
                lines.append(f"C{node} {node} 0 1p")
                if r:
                    lines.append(f"R{node} {node} {bus}{j}_{r-1} .1")
    lines.extend(
        [
            "Rbr br vr 1G",
            "Rbs bs vr 1G",
            f"Cbr br 0 {5e-12+1e-12*len(cols)}",
            f"Cbs bs 0 {5e-12+1e-12*len(cols)}",
            "Xafe br bs nominal black high vp vn cds pga filtered adc chain",
            f".ends bank{label}",
        ]
    )
    return "\n".join(lines)


def deck(cfg, levels, times, banks, *, local=False, factors=None):
    timing = timing_for(cfg)
    c = Circuit("Discrete component global shutter")
    if factors is None:
        factors = 1 + np.random.default_rng(cfg.seed).uniform(
            -cfg.tolerance, cfg.tolerance, (cfg.rows, cfg.cols, 2)
        )
    text = [library(), PIXEL, afe(cfg)]
    saved = []
    for k in banks:
        diagnostic = cfg.probe_col in columns(cfg, k)
        label = 0 if local else k
        text.append(bank(cfg, k, label, levels, times, factors, timing))
        pins = [
            f"{node}{label}" for node in ("adc", "cds", "pga", "filtered", "br", "bs")
        ]
        c.X(f"b{label}", f"bank{label}", *pins)
        saved += pins if diagnostic else pins[:1]
        if diagnostic:
            probe = (
                cfg.probe_row * len(columns(cfg, k))
                + cfg.probe_col
                - columns(cfg, k).start
            )
            saved += [
                f"xb{label}.pd{probe}",
                f"xb{label}.x{probe}.hr",
                f"xb{label}.x{probe}.hs",
            ]
    text += [
        ".save " + " ".join(f"v({n})" for n in saved),
        f".temp {cfg.temperature}",
        ".options method=gear gmin=1e-15 reltol=2e-5 vntol=1e-7 abstol=1e-14",
        f".tran {cfg.slot/10} {timing.end} 0 {max(cfg.exposure/30,cfg.slot/10)}",
        ".end",
    ]
    return str(c) + "\n".join(text) + "\n"
