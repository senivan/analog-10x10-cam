import numpy as np


def quantize(volts: np.ndarray, bits: int, span: float) -> np.ndarray:
    """Unipolar mid-rise converter, including saturated end bins."""
    if bits not in (8, 10, 12) or not np.isfinite(span) or span <= 0:
        raise ValueError("Invalid converter")
    volts = np.asarray(volts)
    if not np.isfinite(volts).all():
        raise ValueError("ADC input must be finite")
    return (
        np.floor(np.clip(volts / span, 0, 1) * 2**bits)
        .clip(0, 2**bits - 1)
        .astype(np.uint16)
    )
