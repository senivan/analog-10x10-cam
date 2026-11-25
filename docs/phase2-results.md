# Component-camera characterization

All measurements on this page come from ngspice 47 on ARM64 macOS. The reference is the previous generic circuit. Component runs use the S5971/ALD1106/TL081/1N4148 circuit. The comparison uses the same optical power and timing in both profiles, with each sensor's own responsivity and leakage. The ADC and image reconstruction are identical. [Circuits and operating conditions](component-camera.md) · [Standalone device checks](../results/phase2/components/components.csv)

## Electrical results

| Bench | Reference | Component circuit |
|---|---:|---:|
| Full light, 10 ms, cathode voltage | 1.053 V | 1.110 V |
| Full light, 10 ms, ADC input at unity gain | 2.047 V | 1.966 V |
| Exposed hold minus cathode at 10 ms | +0.118 mV | −1.993 mV |
| Hold droop before sixth row select, 10 GΩ, 500 μs slot | 0.630 mV | 0.693 mV |
| Bright-to-dark residual, 2×3, 40 μs slot | −0.001 mV | +16.58 mV |
| PGA gain at 16× | 15.997 V/V | 15.963 V/V |
| PGA bandwidth at 16× | 249.6 kHz | 388.3 kHz |
| Filter + driver cutoff at 16× | 79.47 kHz | 77.52 kHz |
| 4×8 gradient, fraction of ADC span used | 59.00% | 56.65% |
| 4×8 gradient, RMS error against fixed reference calibration | 0.127 mV | 43.33 mV |

At 50 ms of full light the component cathode reaches −0.157 V and the ADC input levels off at 3.232 V. The SPICE PIN and MOS bulk junctions conduct in this regime. The lower optical sensitivity, voltage-dependent junction capacitance and gate loading alter the slope before overload. At 10 ms full light, switching in the compression diode reduces the ADC input from 1.966 V to 0.624 V. [Exposure and saturation](../results/phase2/comparison/exposure.csv) · [Compression curves](../results/phase2/comparison/compression.png)

At quarter light the reset-opening step is −14.89 mV and the hold-opening step is −1.71 mV in the component model. Capturing the reset memory after reset release allows CDS to remove most of the reset pedestal. Across the −50 to +50 mV reset-offset sweep, the three measured CDS outputs span 7.3 μV. Bypass spans 100.28 mV. The result describes deterministic charge injection, offset and loading. Semiconductor mismatch and random transient noise would require additional validation. [Pedestal measurements](../results/phase2/comparison/pedestal.csv)

The slow dark-pixel error persists at a 100 μs slot. Filter settling alone cannot restore charge lost when a hold capacitor is connected to the previous bus voltage. At a 3 μs slot the residual grows to 475 mV. Equivalent bus settling to within 1 mV of its own aperture voltage is roughly 74–78 ns across these runs. [Readout sweep](../results/phase2/comparison/settling.csv) · [Pre-select storage error](../results/phase2/comparison/storage.csv)

A 16-row column sweep tested whether more storage capacitance could reduce charge sharing without changing the 8 μs acquisition gate. Moving from 1 to 2.2 nF reduced the late dark-pixel error from 50.4 to 23.6 mV and raised late bright–dark contrast from 1.772 to 1.824 V. At 4.7 nF, dark error fell further to 11.3 mV, but the bright hold missed the cathode voltage by 13.6 mV and contrast fell back to 1.772 V. The measurements support 2.2 nF for this column and timing. The scaling series uses the same 1 nF setting at every resolution. [Storage-capacitor sweep](../results/phase2/comparison/column_hold.csv)

The image-error comparison uses the original full-scale calibration for both circuits. The reported RMS includes the new optical responsivity as well as analog errors. Each image uses the same fixed display scale. [Image comparison](../results/phase2/comparison/frames.png) · [Gain and bandwidth](../results/phase2/comparison/gain.csv) · [File-input capture](../results/phase2/file_image)

## Partition agreement

A 3×5 moving scene with two unequal-width banks and seeded 1% capacitor tolerances was run monolithically and bank by bank. The greatest difference at the ADC apertures was 8.15 μV or less, about 0.01 of a 12-bit ADC bin. Within each bank, row selection, charge sharing and the filter's previous-pixel state still affect subsequent reads. The regression also inverts illumination after the shutter closes and checks the held outputs against a half-bin isolation budget. [Per-pixel differences](../results/phase2/comparison/partition.csv)

## Simulation and scan time

The scalability experiment uses a 10 ms exposure, a 40 μs slot and a checkerboard. Wall time measures construction, circuit execution and sampling. Peak memory is the largest individual ngspice child RSS measured with POSIX wait4. It excludes Python, disk output and other processes. Timings are individual runs on a shared host. The plotted sweep changes both pixel count and hardware bank count. [Benchmark CSV](../results/phase2/scaling/scaling.csv) · [Runtime and memory plots](../results/phase2/scaling/scaling.png)

| Rows × columns | Banks | Execution | Wall time | Peak ngspice RSS | Physical scan |
|---|---:|---|---:|---:|---:|
| 2×2 reference | 1 | Monolithic | 0.038 s | 10.89 MiB | 0.16 ms |
| 2×2 components | 1 | Monolithic | 0.35 s | 12.66 MiB | 0.16 ms |
| 4×8 components | 2 | Monolithic | 8.25 s | 18.89 MiB | 0.64 ms |
| 8×8 components | 4 | Partitioned | 4.90 s | 16.33 MiB | 0.64 ms |
| 10×10 reference | 1 | Monolithic | 3.22 s | 17.75 MiB | 4.00 ms |
| 10×10 components | 1 | Monolithic | 130.63 s | 32.53 MiB | 4.00 ms |
| 10×10 components | 5 | Partitioned | 7.65 s | 17.08 MiB | 0.80 ms |
| 16×16 components | 16 | Partitioned | 10.36 s | 16.13 MiB | 0.64 ms |
| 32×32 components | 32 | Partitioned | 40.84 s | 19.19 MiB | 1.28 ms |
| 64×64 components | 64 | Partitioned | 158.84 s | 26.16 MiB | 2.56 ms |
| 128×128 components | 128 | Partitioned | 593.14 s | 39.20 MiB | 5.12 ms |

With dimensions, clock schedule, scene and channel count fixed at 10×10 and one channel, the component circuit took about 41 times the reference wall time and 1.8 times its peak engine memory. The monolithic component solve accepted 42,365 timesteps and the reference accepted 12,450. In a 64-row pilot the KLU solver stopped at the first reference-track edge with a timestep-too-small error. The completed scaling runs used ngspice’s standard sparse solver and adaptive Gear timesteps. No waveform decimation was applied before ADC sampling. [Monolithic 10×10 benchmark](../results/phase2/scaling/components_10x10_1ch_mono/benchmark.json)

At 64×64 the full modeled frame lasts 12.59 ms, including reset, exposure, isolation and scan. The full sensor has 105,984 distinct electrical nodes excluding common ground and 284,096 expanded primitive elements. The regular scene required three distinct decks totaling 83,495 bytes. The three solves accepted 87,881 timesteps and rejected 20,949. The benchmark CSV distinguishes the counts summed across executed decks from the expanded full-sensor counts. Arbitrary images can require a different solve for every bank. [64×64 node voltages, codes, manifests and decks](../results/phase2/scaling/components_64x64_64ch_bank)

**128×128 is the largest completed acquisition.** The checkerboard used 128 physical column channels and three distinct SPICE solves. The two alternating optical patterns account for two decks, and the selected pixel's additional probe list accounts for the third. The full circuit has 400,384 non-ground nodes and 1,084,288 primitive elements. The three solves accepted 161,363 timesteps and rejected 36,499. The frame lasted 15.15 ms in simulated time. All 16,384 exported codes were checked against the voltage matrix, the selected bank against its raw ADC waveform, and each manifest entry against the full deck generated for that column. [128×128 acquisition](../results/phase2/scaling/components_128x128_128ch_bank)

The highest dark-pixel sample rose from 0.255 V at 64 rows to 0.355 V at 128. The lowest bright-pixel sample fell from 1.818 V to 1.689 V. Increasing column capacitance and the transition from the previous pixel's stored voltage reduce checkerboard contrast. The 8.15 μV partition comparison above measures a separate numerical effect in a smaller, unequal-bank circuit. No full 128×128 monolithic comparison was attempted.

The 4×8 channel sweep holds dimensions and the slot fixed. Increasing from one to eight physical channels shortens the scan from 1.28 to 0.16 ms and raises scan throughput from 25 to 200 kpixel/s. The extra processing chains increase the circuit from 2,409 to 5,272 elements. SPICE wall time fell from 14.78 to 1.32 s in the partitioned checkerboard case. Throughput excludes exposure time. [Parallel-channel plot](../results/phase2/scaling/parallel.png)

## Reproduction

Run the commands in the circuit guide. Each benchmark directory stores the circuit or bank manifest, config, ADC voltages, codes, image and selected waveforms. To rebuild the benchmark charts from existing measurements use `python -m experiments.scaling`. To repeat any single benchmark pass its row count, column count, profile, channel count and partition setting. Use `python -m experiments.comparison --rows 4 --cols 8` for the electrical comparison. Its image dimensions can be changed independently of the fixed component benches.


The original twelve experiments can also run on the component circuit with `python -m experiments.run --model components --channels 10 --partitioned`. The component rerun uses monolithic block benches and 10×10 image acquisitions with ten physical banks. Post-shutter illumination inversion produced a maximum ADC sample change of 1.66 μV in its 2×2 bench. At 10 ms and 8× gain, the brightest column overran the ADC and reached code 4095. The analytical integration column uses the junction's small-signal capacitance at reset bias and omits other parasitics. In the hold-duration sweep the measured change through the ADC aperture includes charge sharing during readout. The separate pre-select experiment isolates hold leakage. [Twelve-experiment measurement summary](../results/phase2/characterization/summary.txt) · [Full-frame comparison](../results/phase2/characterization/12_frames.png)
