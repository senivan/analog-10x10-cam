"""Run with python -m camera.cli."""

import argparse
from dataclasses import asdict, fields
import json
from pathlib import Path

import numpy as np
from PIL import Image

from camera.optics.scenes import frames
from camera.sensor.config import Config
from camera.simulation.acquire import Capture, acquire


def save_capture(out: Path, cfg: Config, capture: Capture) -> None:
    (out / "settings.json").write_text(json.dumps(asdict(cfg), indent=2) + "\n")
    np.savetxt(out / "codes.csv", capture.codes, fmt="%d", delimiter=",")
    np.savetxt(out / "adc_volts.csv", capture.volts, delimiter=",")
    np.savez_compressed(
        out / "waveforms.npz", samples=capture.samples, **capture.traces
    )
    display = np.rint(capture.codes * (255.0 / (2**cfg.bits - 1))).astype("uint8")
    Image.fromarray(display).save(out / "image.png")


def main():
    p = argparse.ArgumentParser(
        description="Simulate a monochrome global shutter camera"
    )
    p.add_argument(
        "scene", nargs="?", default="horizontal", help="pattern name or sRGB image path"
    )
    p.add_argument("--out", type=Path, default=Path("results/capture"))
    for field in fields(Config):
        name = field.name
        default = field.default
        flag = "--" + name.replace("_", "-")
        if isinstance(default, bool):
            p.add_argument(flag, action=argparse.BooleanOptionalAction, default=default)
        else:
            aliases = {"rows": ["--height"], "cols": ["--width"]}.get(name, [])
            p.add_argument(
                flag,
                *aliases,
                type=float if default is None else type(default),
                default=default,
            )
    args = vars(p.parse_args())
    name, out = args.pop("scene"), args.pop("out")
    cfg = Config(**args)
    capture = acquire(cfg, frames(name, cfg), out / "camera.cir")
    save_capture(out, cfg, capture)
    print(
        f"{cfg.rows} × {cfg.cols} in {capture.seconds:.2f} s, codes "
        f"{capture.codes.min()} to {capture.codes.max()}, files in {out}"
    )


if __name__ == "__main__":
    main()
