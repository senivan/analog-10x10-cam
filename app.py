"""Local Streamlit instrument. Launch with streamlit run app.py."""

from pathlib import Path
from tempfile import mkdtemp

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
import streamlit as st

from camera.circuits.components import columns
from camera.cli import save_capture
from camera.controller.timing import START
from camera.optics.scenes import PATTERNS, frames
from camera.sensor.config import Config
from camera.simulation.acquire import acquire


def pixels(levels):
    height, width = levels.shape
    scale = max(1, 300 // max(width, height))
    return Image.fromarray(np.uint8(np.clip(levels, 0, 1) * 255)).resize(
        (width * scale, height * scale), Image.Resampling.NEAREST
    )


st.set_page_config(page_title="Global shutter camera", layout="wide")
st.title("Global shutter camera")
panel = st.sidebar
source = panel.selectbox("Optical input", (*PATTERNS, "Image file"), index=1)
upload = (
    panel.file_uploader(
        "sRGB image", type=["png", "jpg", "jpeg", "bmp", "tiff", "webp"]
    )
    if source == "Image file"
    else None
)
model = panel.selectbox("Analog circuit", ("reference", "components"))
rows = panel.number_input("Sensor height (rows)", min_value=1, value=10)
cols = panel.number_input("Sensor width (columns)", min_value=1, value=10)
channels = (
    panel.number_input("Parallel readout banks", 1, cols, 1)
    if model == "components" and cols > 1
    else 1
)
partitioned = (
    panel.checkbox("Simulate banks separately", value=False) if channels > 1 else False
)
probe_row = (
    panel.number_input("Probe row (zero based)", 0, rows - 1, 0) if rows > 1 else 0
)
probe_col = (
    panel.number_input("Probe column (zero based)", 0, cols - 1, 0) if cols > 1 else 0
)
cfg = Config(
    rows=rows,
    cols=cols,
    model=model,
    channels=channels,
    partitioned=partitioned,
    probe_row=probe_row,
    probe_col=probe_col,
    exposure=panel.number_input("Exposure (ms)", 1.0, 1000.0, 10.0) / 1000,
    gain=panel.selectbox("Analog gain", (1, 2, 4, 8, 16)),
    bits=panel.selectbox("ADC bits", (8, 10, 12), index=2),
    cds=panel.checkbox("Correlated double sampling", True),
    compressed=panel.checkbox("Diode compression"),
    slot=panel.number_input("Pixel slot (μs)", 1.0, 1000.0, 40.0) * 1e-6,
)
if source == "Image file" and upload is None:
    st.info("Select an image to preview or acquire.")
    st.stop()
if "directory" not in st.session_state:
    Path("results/ui").mkdir(parents=True, exist_ok=True)
    st.session_state.directory = Path(mkdtemp(prefix="capture-", dir="results/ui"))
out = st.session_state.directory
if upload:
    input_file = out / "input"
    input_file.write_bytes(upload.getvalue())
    source = str(input_file)
stimulus = frames(source, cfg)
left, right = st.columns(2)
left.image(pixels(stimulus[0][1]), caption="Incident power at t = 0", width=300)
previous = st.session_state.get("capture")
estimate = previous.seconds if previous and st.session_state.settings == cfg else None
if estimate is not None:
    panel.caption(f"Previous runtime at these settings: {estimate:.2f} s")
else:
    panel.caption(
        "Runtime reference: 10×10 reference checkerboard ≈ 3.1 s. Component timing depends on bank size and scene."
    )
if panel.button("Acquire"):
    with st.spinner("Simulating sensor and readout"):
        result = acquire(cfg, stimulus, out / "camera.cir")
        save_capture(out, cfg, result)
        st.session_state.capture = result
        st.session_state.settings = cfg
if "capture" in st.session_state:
    r = st.session_state.capture
    used = st.session_state.settings
    right.image(
        pixels(r.codes / (2**used.bits - 1)),
        caption="Last acquisition · ADC codes",
        width=300,
    )
    clipped = np.count_nonzero((r.volts < 0) | (r.volts >= used.adc_range))
    st.caption(
        f"{used.exposure*1000:g} ms · gain {used.gain}× · {used.bits} bits · "
        f"{clipped} ADC inputs outside range · {r.seconds:.2f} s · {out}"
    )
    a, b = st.columns(2)
    a.write("ADC matrix")
    a.dataframe(r.codes)
    fig, ax = plt.subplots(figsize=(5, 2.6))
    ax.hist(r.codes.ravel(), bins=32, range=(0, 2**used.bits))
    ax.set(xlabel="ADC code", ylabel="Pixels")
    b.pyplot(fig)
    plt.close(fig)
    wave = st.multiselect(
        "Voltage probes",
        list(k for k in r.traces if k != "time"),
        default=[k for k in r.traces if k not in ("time", "br", "cds")],
    )
    scope = st.radio(
        "Time window", ["Frame", "Shutter closing", "Readout"], horizontal=True
    )
    t = r.traces["time"]
    close = START + used.exposure
    mask = (t >= 0) if scope == "Frame" else (t >= close - 10e-6)
    if scope == "Shutter closing":
        mask &= t <= close + 2e-6
    if wave:
        fig, ax = plt.subplots(figsize=(10, 3))
        for name in wave:
            ax.plot(t[mask] * 1e3, r.traces[name][mask], label=name)
        if "adc" in wave and scope != "Shutter closing":
            bank = next(
                columns(used, k)
                for k in range(used.channels)
                if used.probe_col in columns(used, k)
            )
            ax.scatter(
                r.samples.reshape(used.rows, used.cols)[:, bank].ravel() * 1e3,
                r.volts[:, bank].ravel(),
                s=6,
                label="Probed bank samples",
            )
        ax.set(xlabel="Time (ms)", ylabel="Voltage (V)")
        ax.legend(ncol=4)
        st.pyplot(fig)
        plt.close(fig)
