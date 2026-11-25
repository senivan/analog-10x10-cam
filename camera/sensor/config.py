from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Config:
    rows: int = 10
    cols: int = 10
    exposure: float = 0.010
    slot: float = 40e-6
    gain: int = 1
    bits: int = 12
    cds: bool = True
    compressed: bool = False
    supply: float = 5.0
    reset: float = 3.0
    black: float = 0.1
    adc_range: float = 3.3
    cint: float = 100e-12
    hold: float = 1e-9
    leakage: float = 1e12
    dark: float | None = None
    responsivity: float | None = None
    full_power: float = 45e-9
    filter_tau: float = 2e-6
    reset_offset: float = 0.0
    tolerance: float = 0.0
    seed: int = 10
    temperature: float = 27.0

    model: str = "reference"
    channels: int = 1
    partitioned: bool = False
    probe_row: int = 0
    probe_col: int = 0

    def __post_init__(self):
        if self.model not in ("reference", "components"):
            raise ValueError("model must be reference or components")
        real = self.model == "components"
        if self.dark is None:
            object.__setattr__(self, "dark", 70e-12 if real else 2e-12)
        if self.responsivity is None:
            object.__setattr__(self, "responsivity", 0.44 if real else 0.45)
        if type(self.channels) is not int or not 1 <= self.channels <= self.cols:
            raise ValueError("channels must be between one and the column count")
        if not real and (self.channels != 1 or self.partitioned):
            raise ValueError("Parallel banks require the component architecture")
        if any(
            type(p) is not int or not 0 <= p < n
            for p, n in ((self.probe_row, self.rows), (self.probe_col, self.cols))
        ):
            raise ValueError("Probe coordinates outside sensor")
        if real and not (
            0 <= self.temperature <= 70 and self.supply <= 5.5 and self.supply >= 4.5
        ):
            raise ValueError(
                "Component design uses a 4.5–5.5 V reference supply and 0–70 °C MOS array"
            )
        for name in (
            "exposure",
            "slot",
            "supply",
            "adc_range",
            "cint",
            "hold",
            "leakage",
            "responsivity",
            "full_power",
            "filter_tau",
        ):
            if not isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if (
            any(
                type(v) is not int
                for v in (self.rows, self.cols, self.seed, self.gain, self.bits)
            )
            or self.seed < 0
        ):
            raise ValueError(
                "Dimensions, seed, gain and bits must be integers, with a nonnegative seed"
            )
        if min(self.rows, self.cols) < 1 or self.slot < 1e-6 or self.exposure < 20e-6:
            raise ValueError(
                "Use positive dimensions, slot >= 1 us and exposure >= 20 us"
            )
        if self.gain not in (1, 2, 4, 8, 16) or self.bits not in (8, 10, 12):
            raise ValueError("Unsupported gain or ADC resolution")
        if not (
            0 < self.reset + self.reset_offset < self.supply
            and 0 < self.reset < self.supply
            and 0 <= self.black < min(self.supply, self.adc_range)
        ):
            raise ValueError("Invalid voltage references")
        if not (
            0 <= self.tolerance < 1
            and isfinite(self.dark)
            and self.dark >= 0
            and isfinite(self.temperature)
            and self.temperature > -273.15
        ):
            raise ValueError("Invalid sensor parameters")
