"""Execute the saved deck with PySpice. Retry shared-interface errors in batch."""

from pathlib import Path
import logging
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock

import numpy as np
from PySpice.Spice.NgSpice.Shared import NgSpiceShared, NgSpiceCommandError

_lock = Lock()


def _batch(path: Path) -> dict[str, np.ndarray]:
    with TemporaryDirectory() as directory:
        raw = Path(directory) / "plot.raw"
        run = subprocess.run(
            ["ngspice", "-n", "-b", "-r", str(raw), str(path.resolve())],
            capture_output=True,
            text=True,
        )
        if run.returncode or not raw.exists():
            raise RuntimeError(f"{path}: {run.stdout}\n{run.stderr}")
        return read_raw(raw)


def read_raw(raw: Path) -> dict[str, np.ndarray]:
    header, payload = raw.read_bytes().split(b"Binary:\n", 1)
    metadata, variables = header.decode().split("Variables:\n")
    fields = dict(line.split(":", 1) for line in metadata.splitlines() if ":" in line)
    n = int(fields["No. Variables"])
    names = [
        (
            line.split()[1][2:-1] + "#branch"
            if line.split()[1].startswith("i(")
            else line.split()[1].removeprefix("v(").removesuffix(")")
        )
        for line in variables.splitlines()
    ]
    dtype = np.complex128 if "complex" in fields["Flags"] else np.float64
    values = np.frombuffer(payload, dtype=dtype).reshape(int(fields["No. Points"]), n)
    return dict(zip(names, values.T, strict=True))


def simulate(deck: str, path: Path) -> dict[str, np.ndarray]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(deck)
    with _lock:
        try:
            engine = NgSpiceShared.new_instance()
            engine.load_circuit(deck)
            try:
                try:
                    engine.run()
                except NgSpiceCommandError:
                    # PySpice 1.5 treats every stderr message as an error. This
                    # exact pair is informational and the analysis has returned.
                    if (
                        engine.stderr.splitlines()
                        != [
                            "Note: Starting dynamic gmin stepping",
                            "Note: Dynamic gmin stepping completed",
                        ]
                        or "No. of Data Rows" not in engine.stdout
                    ):
                        raise
                plot = engine.plot(None, engine.last_plot)
                data = {
                    name: np.asarray(vec.to_waveform()).copy()
                    for name, vec in plot.items()
                }
            finally:
                engine.destroy()
                engine.remove_circuit()
        except (OSError, NgSpiceCommandError) as error:
            logging.getLogger(__name__).warning(
                "Retrying %s in ngspice batch mode (%s)", path, error
            )
            data = _batch(path)
    if not data or any(not np.isfinite(v).all() for v in data.values()):
        raise RuntimeError(f"Invalid simulation results for {path}")
    return data
