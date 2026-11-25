from dataclasses import dataclass

import numpy as np

EDGE = 20e-9
START = 25e-6


def pwl(points) -> str:
    return "PWL(" + " ".join(f"{t:.13g} {v:.13g}" for t, v in points) + ")"


def gate(start: float, end: float) -> str:
    points = [(0, 3.3)] if start == 0 else [(0, 0), (start, 0), (start + EDGE, 3.3)]
    return pwl(points + [(end, 3.3), (end + EDGE, 0)])


@dataclass(frozen=True)
class Timing:
    exposure: float
    slot: float
    count: int

    @property
    def close(self):
        return START + self.exposure

    @property
    def read(self):
        return self.close + 5e-6

    @property
    def samples(self):
        return self.read + (np.arange(self.count) + 0.90) * self.slot

    @property
    def end(self):
        return self.read + self.count * self.slot
