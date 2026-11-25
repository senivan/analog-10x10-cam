"""Frames contain linear fractions of full-scale per-pixel power."""

from pathlib import Path

import numpy as np
from PIL import Image

from camera.controller.timing import EDGE, START, pwl
from camera.sensor.config import Config

PATTERNS = ("uniform", "horizontal", "vertical", "checkerboard", "point", "moving")


def scene(name: str, shape: tuple[int, int], position: float = 0.0) -> np.ndarray:
    h, w = shape
    y, x = np.indices(shape)
    if name == "uniform":
        return np.ones(shape)
    if name == "horizontal":
        return x / max(1, w - 1)
    if name == "vertical":
        return y / max(1, h - 1)
    if name == "checkerboard":
        return (x + y) % 2
    if name == "point":
        return ((x == w // 2) & (y == h // 2)).astype(float)
    if name == "moving":
        return (
            (x >= position * w)
            & (x < position * w + max(1, w // 3))
            & (abs(y - h // 2) <= h // 4)
        ).astype(float)
    with Image.open(Path(name)) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=float) / 255
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    luminance = linear @ np.array([0.2126, 0.7152, 0.0722])
    return np.asarray(
        Image.fromarray(luminance.astype("float32")).resize(
            (w, h), Image.Resampling.BOX
        )
    )


def frames(name: str, cfg: Config) -> list[tuple[float, np.ndarray]]:
    shape = (cfg.rows, cfg.cols)
    sequence = [(0.0, scene(name, shape))]
    if name == "moving":
        for i in range(1, 5):
            sequence.append((START + i * cfg.exposure / 4, scene(name, shape, i / 5)))
    return sequence


def current_source(times: np.ndarray, levels: np.ndarray, cfg: Config):
    currents = levels * cfg.full_power * cfg.responsivity
    points = [(0.0, currents[0])]
    for index in range(1, len(times)):
        if currents[index] != currents[index - 1]:
            points.extend(
                [
                    (times[index], currents[index - 1]),
                    (times[index] + EDGE, currents[index]),
                ]
            )
    return pwl(points) if len(points) > 1 else currents[0]
