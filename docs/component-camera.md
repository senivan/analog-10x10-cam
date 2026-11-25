# Component camera and rectangular readout

Select `model="components"` in the API or `--model components` in the CLI. The reference profile remains the default for compatibility with existing callers and analytical regression tests. The component path implements the same optical-to-ADC workflow. Both paths support arbitrary positive row and column counts, limited in practice by memory and solve time. [Component model register](../camera/circuits/models/README.md)

## Pixel and shared signal paths

```text
S5971 anode at ground, cathode at pd
optical current sink ── pd ── 100 pF ∥ 10 TΩ to ground
                         ├── ALD reset channel ─ buffered reset divider
                         └── TL081 follower ─ 100 Ω ─┬─ ALD ref gate ─ hr
                                                    └─ ALD sig gate ─ hs
each hold       1 nF ∥ 1 TΩ to ground
hr and hs  → paired row-pass MOSFETs → two distributed column buses
            → paired column-pass MOSFETs → bank reset and signal buses
            → two TL081 followers → differential CDS with black reference
            → switched TL081 PGA → linear or 1N4148 shunt + TL081 buffer
            → 10 kΩ / 200 pF active filter → TL081 driver → 47 Ω → ADC
```

Each bank has three 10 kΩ divider wipers buffered by TL081s for nominal reset, actual reset and black. The 5 V supply sets their adjustment range. An external stimulus may offset actual reset for a CDS experiment. A 100 Ω series output resistor isolates each reference follower. Directly coupling the reset follower to a whole column of integration capacitors caused a timestep collapse during the first reference gate transition in an early 64-row bench. The resistor retains the shared reference impedance and allowed the standard sparse solver to finish. Use of ±7.5 V analog supplies keeps the normal 0–3.3 V signal in the TL081 input and output range. The ideal ADC still accepts analog overdrive and clips its output code. Physical ADC protection and regulator design are outside the circuit.

The integration capacitance still dominates the nominal S5971 junction capacitance. A 45 nW, 660 nm equivalent pixel generates 19.8 nA. Its swing is approximately 1.9 V over 10 ms. The PIN junction capacitance increases as reverse bias falls. The resulting curvature and the extra leakage are present at the ADC. Severe overexposure forward biases the diode and can engage bulk junctions of grounded MOS switches. Quantitative performance in overload requires characterization of the particular hardware.

All three exposure gates have a separate 33 Ω driver in each bank, fed by the same external 0/9 V clock timing. The nine-volt gate swing gives headroom for single N-channel switches passing a 3 V reset. A physical controller would require level translation. Real gate load and finite rise/fall times appear at the downstream gates. Reset opens at 20 μs. The reset memory tracks from 1 to 25 μs and therefore captures reset-release pedestal. The signal gate tracks during the last 8 μs of the configured exposure. Images use the difference between these two apertures. Aperture skew due to unequal capacitive loads can occur in unequal-width banks.

The pixel follower supplies acquisition current into the storage capacitors. On readout, the selected capacitor connects directly to its column, then to its bank bus. Switching is destructive at the analog-memory level. The column has 0.1 Ω between adjacent row taps and 1 pF per tap, in addition to the junction capacitance of every off switch. Each final bus has 5 pF plus 1 pF per bank column and a 1 GΩ return to reset. These interconnect values are layout assumptions. Finite input resistance and bias of the bank follower remain present. The PGA uses 100 kΩ base resistance so the several-hundred-ohm analog switch contributes a small but measurable gain error. The filter's switch resistance also shifts its cutoff. There are no behavioral gain, subtraction or log expressions in the external circuit.

## Addressing and circuit partitions

For R rows, C columns and K banks, 1 ≤ K ≤ C. Split adjacent columns as evenly as possible. Bank widths differ by at most one. Let W = ceil(C/K). Row r gets W slots. Local column j is sampled at t_read + (rW + j + 0.9) × slot. Each bank has two independent final buses and a complete processing chain continuously connected throughout the simulation. Short banks idle in the spare slot. The frame is reconstructed using each bank's own ADC node and its columns' original indices. The public samples vector has one time per image element in row-major order. With parallel channels these times can repeat or go backwards at a bank boundary.

In monolithic mode all banks coexist in one ngspice circuit. In partitioned mode each solve still includes **all rows and columns of one physical bank**, the complete exposure, the full physical readout timeline and that bank's filter memory. References and control resistors are local to each bank in both configurations. The shared boundaries are prescribed external clocks, ideal supplies and ground. Under these assumptions there is no interbank analog state to hand off. Supply impedance shared across banks, ground bounce, shared regulator dynamics, mutual capacitance between banks and thermal coupling would break this equivalence. Modeling such effects would require a coupled solve.

The partitioner compares a digest of the entire normalized deck, including the actual optical waveform, tolerances, clock schedule, wire network and saved probes. It reuses sampled voltages only for identical decks within the same frame. A frame with distinct stimuli or tolerances in every bank requires every bank solve. The bank manifest maps every physical bank to its standalone deck. Probe data come from the selected bank's native adaptive time grid. The voltage CSV includes all banks. The measurement harness runs identical decks in fresh ngspice processes, reads the binary raw data once, and obtains simulator counters and peak resident memory. The camera API also supports the PySpice shared interface.

## Bill of materials

Let P = R × C. The following counts describe the simulated topology, before connectors, power distribution, level translators, decoupling, or ADC selection.

| Item | Count |
|---|---:|
| Hamamatsu S5971 | P |
| TI TL081CP | P + 10K (three references, two read buffers, CDS, PGA, compressor buffer, filter and driver per bank) |
| ALD1106 pass channels | 5P + 2C + 10K (reset, two track and two row gates per pixel, two column gates per column, ten static selections per bank) |
| ALD1106PBL quad packages | at least ceil((5P + 2C + 10K)/4), subject to routing and package placement |
| NXP 1N4148 | K |
| Integration capacitors / storage capacitors | P / 2P |
| Pixel follower isolation resistors | P |
| Adjustable divider references | 3K |
| Control drive resistances | (R + 3)K + C |
| Filter capacitors / ADC isolation resistors | K / K |

The shunt resistances, bus capacitances and distributed wire resistances model dielectric, switch, input and layout parasitics. The active-device count and amplifier power make a discrete 64×64 assembly a substantial hardware design. The SPICE demonstration establishes electrical simulation feasibility.

## Commands

```sh
python -m camera.cli checkerboard --model components --height 4 --width 8 --channels 2 --probe-row 3 --probe-col 7 --out results/rectangular
python -m camera.cli path/to/input.png --model components --rows 10 --cols 16 --channels 4 --partitioned --out results/banked
python -m experiments.components
python -m experiments.comparison
python -m experiments.scaling --size 64 64 --channels 64 --partitioned
python -m pytest -q
```

Use a fresh output directory for each capture. To rerun a bank independently, run `ngspice -b -r bank.raw path/to/camera.bank0.cir`. The benchmark harness uses POSIX wait4 for child peak RSS. It was exercised on ARM64 macOS with ngspice 47. [Performance and electrical comparisons](phase2-results.md)
