"""Standalone component operating points before camera integration."""

import csv
from pathlib import Path
import numpy as np

from camera.circuits.models import library
from camera.simulation.backend import simulate


def run(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)

    def bench(name, body):
        return simulate(
            name
            + "\n"
            + library()
            + "\n.options gmin=1e-15\n.temp 25\n"
            + body
            + "\n.end\n",
            directory / (name + ".cir"),
        )

    mos = bench("ald1106", "Vg g 0 5\nVd d 0 .1\nX1 d 0 g pass\n.save i(vd)\n.op")
    pin = bench(
        "s5971", "Vb k 0 DC 10 AC 1\nX1 0 k pin\n.save i(vb)\n.ac lin 1 1meg 1meg"
    )
    dark = bench("dark", "Vb k 0 10\nX1 0 k pin\n.save i(vb)\n.op")
    amp = bench(
        "tl081",
        "Vcc vcc 0 15\nVee vee 0 -15\nVi plus 0 DC 2 AC 1\nX1 plus out vcc vee out TL081\nRl out 0 10k\n.save v(out)\n.ac dec 32 100 100meg",
    )
    diode = bench("1n4148", "I1 0 a 10m\nX1 a 0 1N4148\n.save v(a)\n.op")
    f = amp["frequency"].real
    gain = abs(amp["out"])
    metrics = {
        "on_ohm": 0.1 / abs(mos["vd#branch"].item()),
        "junction_pF": abs(pin["vb#branch"].imag.item()) / (2 * np.pi * 1e6) * 1e12,
        "dark_pA": abs(dark["vb#branch"].item()) * 1e12,
        "follower_dc_gain": gain[0],
        "follower_bw_Hz": f[np.flatnonzero(gain < 0.707)[0]],
        "forward_10mA_V": diode["a"].item(),
    }
    off = bench("ald_off", "Vd d 0 10\nX1 d 0 0 pass\n.save i(vd)\n.op")
    gate = bench(
        "ald_gate", "Vg g 0 DC 0 AC 1\nX1 0 0 g pass\n.save i(vg)\n.ac lin 1 1meg 1meg"
    )
    slew = bench(
        "tl081_step",
        "Vcc vp 0 15\nVee vn 0 -15\nVi p 0 PWL(0 0 1u 0 1.001u 10)\nX1 p out vp vn out TL081\nRl out 0 2k\nCl out 0 100p\n.save v(out)\n.tran 2n 6u\n",
    )

    def crossing(v):
        idx = np.flatnonzero(slew["out"] >= v)[0]
        return np.interp(
            v, slew["out"][idx - 1 : idx + 1], slew["time"][idx - 1 : idx + 1]
        )

    dc = bench(
        "tl081_bias",
        "Vcc vp 0 7.5\nVee vn 0 -7.5\nVi p 0 2\nX1 p out vp vn out TL081\nRl out 0 10k\n.save i(vi) v(out)\n.op",
    )
    metrics.update(
        off_pA=abs(off["vd#branch"].item()) * 1e12,
        gate_pF=abs(gate["vg#branch"].imag.item()) / (2 * np.pi * 1e6) * 1e12,
        slew_V_per_us=8e-6 / (crossing(9) - crossing(1)),
        input_pA=abs(dc["vi#branch"].item()) * 1e12,
        follower_error_mV=(dc["out"].item() - 2) * 1000,
    )
    with (directory / "components.csv").open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(metrics)
        writer.writerow(metrics.values())
    return metrics


if __name__ == "__main__":
    print(run(Path("results/phase2/components")))
