"""Local manufacturer original and ngspice-portable component deck."""

from pathlib import Path

ROOT = Path(__file__).parent


def library() -> str:
    # SLOJ069 contains a DOS EOF byte. Express its two linear polynomials
    # using linear primitive sources so libngspice needs no XSPICE code models.
    original = (ROOT / "TL081.301").read_text(encoding="ascii").rstrip("\x1a\n")
    original = original.replace(
        "EGND 99  0 POLY(2) (3,0) (4,0) 0 .5 .5",
        "Ehalf mid 0 3 0 .5\nEground 99 mid 4 0 .5",
    )
    original = original.replace(
        "FB    7 99 POLY(5) VB VC VE VLP VLN 0 4.715E6 -5E6 5E6 5E6 -5E6",
        "Fsum0 7 99 VB 4.715meg\n"
        "Fsum1 7 99 VC -5meg\n"
        "Fsum2 7 99 VE 5meg\n"
        "Fsum3 7 99 VLP 5meg\n"
        "Fsum4 7 99 VLN -5meg",
    )
    return (
        original
        + "\n"
        + (ROOT / "devices.lib").read_text()
        + (ROOT / "1N4148.lib").read_text()
    )
