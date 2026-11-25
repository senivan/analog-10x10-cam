# Reference circuit electrical design

## Signal path

```text
incident W × A/W → independent SPICE photocurrent per pixel
                               ↓
             photodiode + Cint + reset switch      × 100
                               ↓
                    high impedance follower
                       ↙               ↘
             reset track/hold     signal track/hold
                    ↓                     ↓
              buffered paired read switches, one pixel selected
                    ↓                     ↓
               reset bus               signal bus
                    └─ difference amplifier ─┘ ← black reference
                                  ↓
                           switched PGA
                                  ↓
                     linear / diode compressor
                                  ↓
                       RC + active follower
                                  ↓
                    driver + 47 Ω + ADC load
                                  ↓
                   sample adc → quantize → reshape
```

## Optical input and integration

An image represents a spatial distribution of light under an assumed fixed spectrum. The optical input assumes ordinary sRGB, decodes each RGB channel to linear light, forms Y = 0.2126 R + 0.7152 G + 0.0722 B, then box-resamples the linear image to the sensor grid. Generated patterns already specify linear light. The full-scale input is 45 nW **incident on one active area**. Thus P = Y × 45 nW and Iphoto = 0.45 A/W × P. Treat 0.45 A/W as an assumed effective silicon responsivity at a fixed visible red wavelength around 650 nm. The model omits lens transmission, diffraction, spectral integration, ICC transforms and automatic exposure. [sRGB transfer and conversion equations](https://www.w3.org/TR/css-color-4/#color-conversion-code)

```text
3 V reset ─ Sreset ── pd ─── (+) follower ─ 50 Ω ─ drive
                      │
                      ├── Cint ∥ Cjunction ∥ Rleak ─ ground
                      ├── diode cathode (anode at ground)
                      └── Iphoto + Idark + Ibias → ground
```

Reset raises the cathode and reverse biases the diode. Opening reset allows the current sink to discharge the node. While reverse biased, ΔV ≈ (Iphoto + Idark + Ibias + Ileak)t/(Cint + Cjunction). At 20.25 nA and 10 ms the generated charge is 202.5 pC. A target swing near 2 V requires about 101 pF. The design uses 100 pF plus 4 pF of lumped junction/stray capacitance, giving 1.947 V ideal swing and about 1.05 V remaining reverse bias. A 10 TΩ shunt, 2 pA dark sink, 0.2 pA input bias and the diode's small reverse saturation current describe separate leakage paths. All values are design assumptions.

The nominal linear window ends near the follower's 20 mV lower limit, at about 15.3 ms of full light. For 1 s exposures use lower incident power or a larger capacitor. In severe overexposure the SPICE diode forward biases and the follower clips. Negative cathode voltage in that regime flags a real component-selection issue. A hardware follower would need specified input protection and recovery behavior before the overload predictions could be used quantitatively.

## Storage and shutter

```text
drive ─ Sref ─ hr ─── follower ─ 50 Ω ─ Sread ─ br
               ├── 1 nF to ground
               └── 1 TΩ and bias sink to ground
drive ─ Ssig ─ hs ─── follower ─ 50 Ω ─ Sread ─ bs
               └── identical storage and leakage network
```

The two read switches share one pixel-select control. The hold buffers isolate capacitor charge from the 30 pF buses. Each bus has a 1 TΩ DC path. With 50 Ω output impedance and 50 Ω switch resistance, the nominal tracking time constant is 100 ns. About nine time constants settle a full-scale step within half a 12-bit LSB. The shorter acquisition gate lasts 8 μs. During tracking of a ramp, the capacitor lags by about one time constant. An off resistance of 100 TΩ creates finite isolation. A stored 3 V on 1 nF with 1 TΩ leakage loses about 12 μV over the 4 ms default scan, plus bias and switch leakage. The reset memory also ages throughout exposure. Tolerance settings apply a seeded uniform fractional spread independently to integration and storage capacitance per pixel, with that pixel's two storage capacitors matched.

| Control or event | Time relative to frame start |
|---|---|
| Reset | Starts closed in DC operating point, release at 25 μs |
| Reset reference track | 5 to 24 μs |
| All pixels integrate | 25 μs to T = 25 μs + exposure |
| Signal track | T − 8 μs to T |
| All signal holds isolated | Immediately after falling edge at T |
| Row-major read of pixel k | T + 5 μs + k × slot |
| ADC aperture | 90% into each slot |
| Select falls | 100 ns before slot end |

```text
             reset and settle         simultaneous integration          scan
reset     ━━━━━━━━━━━━━━━━━━━━━┓_______________________________________________
ref gate       ┏━━━━━━━━━━━━┓__________________________________________________
sig gate  ______________________________________________┏━━━━━━━━┓_____________
select 0  __________________________________________________________┏━━━━┓_____
select 1  __________________________________________________________________┏━━
                                                                    ↑   •
                                                                 select sample
```

The control levels are 0 and 3.3 V with 20 ns edges and switch hysteresis around 1.65 V. Reset and signal samples use a common clock across the array. Reset is still active while the reset reference is tracked. A real reset-opening charge error arising *after* that capture would survive the subtraction.

## Difference, gain, compression and drive

```text
selected br or nominal reset ─ 1 MΩ ─┬─ (+) A1
black reference ────────────── 1 MΩ ─┘
bs ─────────────────────────── 1 MΩ ─┬─ (−) A1 ─── cds
cds ────────────────────────── 1 MΩ ─┘

cds ─ (+) A2 ─ pga ─ selected Rf + switch ─┐
      (−) A2 ───────────────────────────────┤
black ─ bottom switch + 9.95 kΩ ────────────┘
```

A matched four-resistor subtractor establishes Vcds ≈ Vblack + Vreset,held − Vsignal,held. Bypass selects the fixed nominal reset voltage and preserves positive scene polarity. The 1 MΩ arms limit loading by the 100 Ω bus source resistance. Buffered references are ideal voltage sources in this design. The CDS test adds a controlled offset to the actual reset supply shared by both measurements. This tests rejection of a correlated frame offset. Photon arrival statistics, kTC reset-opening noise, Johnson noise, amplifier noise and switch injection are absent from the transient model. The reported ADC error and deterministic offset rejection are distinct from temporal noise or SNR.

The PGA implements Vpga ≈ Vblack + G(Vcds − Vblack). A 10 kΩ effective bottom arm sets the scale. Active feedback arms total (G−1)×10 kΩ including the selected switch's 50 Ω. Unity mode closes direct feedback and opens the bottom arm. The op-amp macromodel uses a 2.513 mS transconductor into 39.79 MΩ in parallel with 100 pF, then a buffered 10 Ω output. This gives about 100,000 DC gain and 4 MHz gain-bandwidth product. The ±400 μA internal current limit gives 4 V/μs slew. A 20 μV input offset and soft clamps near 20 mV and Vdd−20 mV allow offset, saturation and recovery to appear in transients. With a 5 V analog supply and 3.3 V ADC reference the driver can overrange the ideal ADC. Real hardware needs a compatible input rating or protection circuit.

```text
pga ───────────────────────── linear switch ─┐
pga ─ 10 kΩ ─ knee ─ follower ─ diode-mode sw ┤
              └── diode anode → black cathode │
                        selected mode ────────┘
                            ↓
                         9.95 kΩ ─ filt ─ active follower ─ driver ─ 47 Ω ─ adc
                                    │                                     │
                                  200 pF                              20 pF ∥ 10 MΩ
                                    │                                     │
                                   GND                                   GND
```

In compression mode the diode shunts the knee to black. With u = Vpga−Vblack and v = Vknee−Vblack, (u−v)/R = Is[exp(v/(nVT))−1]. The 10 kΩ resistor limits current below 0.5 mA across the 5 V supply. The assumed 1 nA saturation current and n = 1.5 put the bend within the 0–2 V nominal signal swing. At low input the transfer is nearly linear. At larger current the rise becomes approximately logarithmic. Compression after the PGA cannot recover information lost to upstream clipping.

Filter input resistance including the mode switch is 10 kΩ. A 200 pF capacitor gives τ = 2 μs and fc ≈ 79.6 kHz. The follower isolates the pole, and the final driver and 47 Ω isolation resistor drive 20 pF plus a 10 MΩ input. At the default 25 kpixel/s the sample arrives after 18 filter time constants. The model includes driver bandwidth and static ADC loading. Switched-capacitor ADC kickback, comparator errors, DNL and INL would require more detailed models.

## Simulation and reconstruction

Each pixel is a PySpice subcircuit instance, with independent optical current and a common exposure timeline. The simulator starts from the DC solution and takes adaptive Gear transient steps. PWL transitions supply breakpoints around the sampling windows. Resistive DC paths keep the isolated nodes defined. The selected pixel's internal voltages and shared readout nodes are saved. Pixel zero is selected by default. Every other pixel remains electrically present. Static front-end switches use voltage-controlled conductance with the same on/off resistance in DC, AC and transient analyses. Dynamic pixel switches use the ngspice SW model. [ngspice manual](https://ngspice.sourceforge.io/docs.html)

Python linearly interpolates the final ADC node at each aperture, clips to the converter range and computes min(2ᴺ−1, floor(2ᴺ × Vclipped/Vref)). The simulator reshapes these integer codes in read order. Each unclipped code represents a bin of width Vref/2ᴺ. The quantization experiment uses its midpoint to estimate the input voltage.

The pixel followers use unity-gain controlled sources with output resistance. The integration follower additionally includes input offset and output limits. The stored-level followers have ideal gain and input common-mode behavior. The shared op-amps assume rail-to-rail input capability over the normal signal range. Supply currents, layout parasitics beyond the lumped capacitances, switch charge injection, clock feedthrough, voltage-dependent junction capacitance, resistor mismatch and package temperature gradients are outside this model. Saturation recovery and temperature sweeps describe these macromodels. They do not specify a commercial part or substitute for hardware qualification.

The acquisition decks set the numerical junction shunt conductance gmin to 10⁻¹⁵ S. At 3 V this contributes only a few femtoamperes. The usual 10⁻¹² S value would create a parasitic current comparable to the specified photodiode dark current.
