"""Make an sRGB input card and acquire it with the default camera."""

from pathlib import Path

from PIL import Image, ImageDraw

from camera.cli import save_capture
from camera.optics.scenes import frames
from camera.sensor.config import Config
from camera.simulation.acquire import acquire


def main():
    directory = Path("results/test_card")
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (100, 100), (20, 20, 20))
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((10, 15, 40, 55), fill=(230, 230, 230))
    drawing.ellipse((50, 10, 89, 49), fill=(220, 40, 20))
    for x in range(100):
        level = round(255 * x / 99)
        drawing.line((x, 70, x, 89), fill=(level,) * 3)
    source = directory / "scene.png"
    image.save(source)
    cfg = Config()
    result = acquire(cfg, frames(str(source), cfg), directory / "camera.cir")
    save_capture(directory, cfg, result)


if __name__ == "__main__":
    main()
