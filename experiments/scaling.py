"""Measure each physical bank solve in a fresh ngspice process (POSIX)."""

import argparse
import csv
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from camera.cli import save_capture
from camera.optics.scenes import frames
from camera.sensor.config import Config
from camera.simulation.acquire import acquire
from camera.simulation.backend import read_raw


def census(flat):
    nodes = set()
    elements = 0
    arity = dict.fromkeys("rcdivbfh", 2) | dict.fromkeys("megs", 4) | {"j": 3}
    for line in flat.splitlines():
        match = re.match(r"\s*\d+ : (\S+) (.*)", line)
        if (
            line.lstrip().startswith("1 :")
            or not match
            or match[1][0] not in arity
            or match[1] == "discrete"
        ):
            continue
        elements += 1
        nodes.update(match[2].split()[: arity[match[1][0]]])
    return len(nodes - {"0"}), elements


class Meter:
    def __init__(self):
        self.runs = []

    def __call__(self, deck, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(deck)
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "run.cir").write_text(
                deck.removesuffix(".end\n")
                + """.control
listing e > flat.txt
run
rusage equations accept rejected totiter
write plot.raw
quit
.endc
.end
"""
            )
            start = perf_counter()
            with (work / "log").open("w") as log:
                proc = subprocess.Popen(
                    ["ngspice", "-n", "-b", "run.cir"],
                    cwd=work,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                _, status, usage = os.wait4(proc.pid, 0)
                proc.returncode = os.waitstatus_to_exitcode(status)
            seconds = perf_counter() - start
            log = (work / "log").read_text()
            if (
                proc.returncode
                or "aborted" in log.lower()
                or not (work / "plot.raw").exists()
            ):
                raise RuntimeError(f"{path}\n" + log[-1800:])
            nodes, elements = census((work / "flat.txt").read_text())

            def count(field):
                return int(re.search(field + r"\s*=\s*(\d+)", log, re.I)[1])

            self.runs.append(
                dict(
                    solve_s=seconds,
                    peak_MiB=usage.ru_maxrss
                    / (2**20 if sys.platform == "darwin" else 1024),
                    nodes=nodes,
                    elements=elements,
                    netlist_bytes=len(deck.encode()),
                    equations=count("Circuit Equations"),
                    accepted=count("Accepted timepoints"),
                    rejected=count("Rejected timepoints"),
                    iterations=count("Total iterations"),
                )
            )
            return read_raw(work / "plot.raw")


def measure(root, cfg, scene="checkerboard"):
    meter = Meter()
    directory = (
        root
        / f'{cfg.model}_{cfg.rows}x{cfg.cols}_{cfg.channels}ch_{"bank" if cfg.partitioned else "mono"}'
    )
    r = acquire(cfg, frames(scene, cfg), directory / "camera.cir", simulator=meter)
    save_capture(directory, cfg, r)
    data = {
        **asdict(cfg),
        "scene": scene,
        "distinct_solves": len(meter.runs),
        "wall_s": r.seconds,
        "read_s": cfg.rows * ((cfg.cols + cfg.channels - 1) // cfg.channels) * cfg.slot,
        "end_s": r.traces["time"][-1],
        "min_code": int(r.codes.min()),
        "max_code": int(r.codes.max()),
    }
    for key in meter.runs[0]:
        data[key] = (
            max(x[key] for x in meter.runs)
            if key == "peak_MiB"
            else sum(x[key] for x in meter.runs)
        )
    (directory / "benchmark.json").write_text(json.dumps(data, indent=2) + "\n")
    print(directory.name, round(r.seconds, 2), "s", data["peak_MiB"], "MiB", flush=True)
    return data


def report(root):
    rows = [json.loads(p.read_text()) for p in sorted(root.glob("*/benchmark.json"))]
    for row in rows:
        folder = (
            root
            / f'{row["model"]}_{row["rows"]}x{row["cols"]}_{row["channels"]}ch_{"bank" if row["partitioned"] else "mono"}'
        )
        if row["partitioned"]:
            manifest = json.loads((folder / "camera.banks.json").read_text())
            counts = {}
            with TemporaryDirectory() as tmp:
                work = Path(tmp)
                for entry in manifest:
                    filename = entry["deck"]
                    if filename in counts:
                        continue
                    deck = (folder / filename).read_text()
                    (work / "census.cir").write_text(
                        deck.removesuffix(".end\n")
                        + ".control\nlisting e > flat.txt\nquit\n.endc\n.end\n"
                    )
                    subprocess.run(
                        ["ngspice", "-n", "-b", "census.cir"],
                        cwd=work,
                        check=True,
                        capture_output=True,
                    )
                    counts[filename] = census((work / "flat.txt").read_text())
            row["sensor_nodes"] = sum(counts[e["deck"]][0] for e in manifest)
            row["sensor_elements"] = sum(counts[e["deck"]][1] for e in manifest)
        else:
            row["sensor_nodes"] = row["nodes"]
            row["sensor_elements"] = row["elements"]
    with (root / "scaling.csv").open("w") as f:
        w = csv.DictWriter(f, fieldnames=rows[0])
        w.writeheader()
        w.writerows(rows)
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), layout="constrained")
    for ax, key in zip(axes, ["wall_s", "peak_MiB", "read_s"]):
        for label, group in [
            ("banked components", [r for r in rows if r["partitioned"]]),
            (
                "monolithic components",
                [
                    r
                    for r in rows
                    if not r["partitioned"] and r["model"] == "components"
                ],
            ),
            ("reference", [r for r in rows if r["model"] == "reference"]),
        ]:
            group.sort(key=lambda r: r["rows"] * r["cols"])
            if group:
                ax.loglog(
                    [r["rows"] * r["cols"] for r in group],
                    [r[key] for r in group],
                    "o",
                    label=label,
                )
        ax.set(xlabel="sensor pixels", ylabel=key)
    axes[0].legend(fontsize=8)
    fig.savefig(root / "scaling.png", dpi=140)
    plt.close(fig)

    sweep = sorted(
        [
            r
            for r in rows
            if r["model"] == "components"
            and (r["rows"], r["cols"]) == (4, 8)
            and r["partitioned"]
        ],
        key=lambda r: r["channels"],
    )
    if sweep:
        fig, axes = plt.subplots(1, 2, figsize=(8, 3), layout="constrained")
        channels = [r["channels"] for r in sweep]
        axes[0].plot(channels, [32 / r["read_s"] / 1000 for r in sweep], "o-")
        axes[1].plot(channels, [r["wall_s"] for r in sweep], "o-")
        axes[0].set(xlabel="Physical banks", ylabel="Scan throughput (kpixel/s)")
        axes[1].set(xlabel="Physical banks", ylabel="SPICE acquisition wall time (s)")
        fig.savefig(root / "parallel.png", dpi=140)
        plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--size", nargs=2, type=int, metavar=("ROWS", "COLS"))
    p.add_argument("--channels", type=int, default=1)
    p.add_argument("--partitioned", action="store_true")
    p.add_argument("--model", default="components", choices=["components", "reference"])
    p.add_argument("--root", type=Path, default=Path("results/phase2/scaling"))
    args = p.parse_args()
    if args.size:
        measure(
            args.root,
            Config(
                rows=args.size[0],
                cols=args.size[1],
                channels=args.channels,
                model=args.model,
                partitioned=args.partitioned,
            ),
        )
    report(args.root)
