# SPICE monochrome camera

This Analog Schemotechnics project simulates one exposure of a discrete global-shutter camera. The default netlist contains 100 integration nodes, 200 analog memories and a shared differential readout, gain stage, filter and ADC driver. Every output code comes from a timed sample of its simulated ADC-driver output. Python generates light and control stimuli and performs the final ideal quantization.

[Electrical design, schematics and timing](docs/design.md) · [Experimental results](docs/measurements.md) · [Generated 100-pixel netlist](results/checker10.cir)

## Component camera

Select the component profile for the S5971 sensor, ALD1106 transistor switches, TL081 analog path and 1N4148 compressor. Set independent height and width, physical bank count and probe coordinates from the CLI or Streamlit. Existing invocations select the original reference circuit.

```sh
python -m camera.cli checkerboard --model components --height 4 --width 8 --channels 2 --partitioned --out results/rectangular
```

[Component schematics, timing and BOM](docs/component-camera.md) · [Device models and sources](camera/circuits/models/README.md) · [Component and scalability measurements](docs/phase2-results.md)

## Install on macOS ARM64

From the repository root, use a native ARM64 Homebrew Python and ngspice.

```sh
brew install python@3.12 ngspice
"$(brew --prefix python@3.12)/bin/python3.12" -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

The validated environment used Python 3.12.14, PySpice 1.5 and Homebrew ngspice/libngspice 47. On Debian-like systems install Python with venv support, ngspice and libngspice0, then use the same venv and pip steps. The Linux instructions have not been exercised here.

Homebrew's shared library discovery worked on the test machine. If the loader cannot locate the dylib, set the following variable before starting Python.

```sh
export NGSPICE_LIBRARY_PATH="$(brew --prefix libngspice)/lib/libngspice.dylib"
```

PySpice 1.5 warns that version 47 is unsupported. The divider, pixel and full-array transients worked through the shared interface. On some bias points PySpice treats ngspice convergence-stepping diagnostics as a command failure even after successful stepping. The runner accepts the completed dynamic-gmin note pair when data rows were returned. For other shared command failures it retries the saved deck with the ngspice executable and reads its binary raw output. Both paths reject nonfinite data. Acquisition checks the final simulation time.

## Acquire

```sh
python -m camera.cli horizontal --out results/gradient
python -m camera.cli path/to/photo.jpg --exposure 0.005 --gain 2 --bits 10 --out results/photo
python -m camera.cli moving --compressed --slot 0.000040 --out results/motion
python -m camera.cli checkerboard --rows 2 --cols 2 --no-cds
python -m camera.cli --help
python -m examples.test_card
```

Patterns include `uniform`, `horizontal`, `vertical`, `checkerboard`, `point` and `moving`. Options use SI units, apart from temperature in degrees Celsius and dimensionless settings. A capture writes a standalone netlist, the acquisition settings in JSON, a voltage matrix in volts, an integer ADC matrix, an 8-bit display PNG and compressed NumPy waveforms. Row zero is the top of the image. The PNG maps the entire ADC code range to grayscale. Use the CSV for numerical analysis. Choose a new output directory to retain an earlier run.

```python
from pathlib import Path
import numpy as np
from camera.sensor.config import Config
from camera.simulation.acquire import acquire

cfg = Config(rows=2, cols=2, exposure=0.005, gain=2)
initial = np.array([[0., 0.25], [0.5, 1.]])
frames = [(0., initial), (0.006, 1 - initial)]
capture = acquire(cfg, frames, Path("results/api/camera.cir"))
print(capture.codes)
```

Each frame starts at an absolute time in seconds and specifies a linear fraction of the per-pixel full-scale optical power. A 20 ns ramp connects successive different levels. The last frame persists. Netlists run independently with `ngspice -b -r camera.raw results/checker10.cir`.

## Characterize and inspect

```sh
python -m experiments.run results/characterization
python -m pip install -r requirements-ui.txt
python -m streamlit run app.py
```

The characterization runner writes plots, CSV tables, measured summaries and the decks used for each sweep. The local Streamlit instrument previews the input, runs acquisitions on demand and displays pixelated output, ADC codes, clipping, histogram and selectable node waveforms. It retains each session's latest acquisition under `results/ui/`. A default 10×10 checkerboard took approximately 3.2 s on the validation host. Scene, timing, solver version and host affect runtime.
