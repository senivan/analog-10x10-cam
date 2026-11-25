from PySpice.Spice.Netlist import SubCircuit

from camera.sensor.config import Config


def amplifier() -> SubCircuit:
    amp = SubCircuit("amp", "plus", "minus", "out")
    amp.raw_spice = """
* Dominant pole, 4 MHz GBW, 100k DC gain, 4 V/us slew, rail clamps
Bgm 0 pole I=max(-400u,min(400u,2.513m*(v(plus,minus)+20u)))
Rp pole 0 39.79meg
Cp pole 0 100p
Brails pole 0 I=(min(0,v(pole)-0.02)+max(0,v(pole)-v(vdd)+0.02))/2
Ebuf drive 0 pole 0 1
Rout drive out 10
"""
    return amp


def frontend(cfg: Config) -> str:
    net = f"""
* Voltage-controlled channel for static mode and feedback selections
.subckt select a b control
Bchannel a b I=v(a,b)*(v(control)>1.65 ? 0.02 : 1e-14)
.ends select
Vblack black 0 {cfg.black}
Vnom nominal 0 {cfg.reset}
Vcds cg 0 {3.3 if cfg.cds else 0}
Vbypass bg 0 {0 if cfg.cds else 3.3}
Xref br ref cg select
Xnom nominal ref bg select
Rplus ref plus 1meg
Rblack plus black 1meg
Rminus bs minus 1meg
Rdiff cds minus 1meg
Xdiff plus minus cds amp
Xgain cds fb pga amp
Vmulti multi 0 {0 if cfg.gain == 1 else 3.3}
Xbottom bot black multi select
Rg fb bot 9950
"""
    for gain in (1, 2, 4, 8, 16):
        # Include switch Ron in the feedback resistance.
        resistance = max(0.01, (gain - 1) * 10000 - 50)
        net += f"Vg{gain} g{gain} 0 {3.3 if cfg.gain==gain else 0}\n"
        net += f"Rf{gain} pga tap{gain} {resistance}\nXf{gain} tap{gain} fb g{gain} select\n"
    return (
        net
        + f"""
.model comp D(Is=1n N=1.5)
Rcomp pga knee 10k
Dcomp knee black comp
Xcomp knee compbuf compbuf amp
Vlin lin 0 {0 if cfg.compressed else 3.3}
Vlog logsel 0 {3.3 if cfg.compressed else 0}
Xlin pga mode lin select
Xlog compbuf mode logsel select
Rfilter mode filt 9950
Cfilter filt 0 {cfg.filter_tau/10000}
Xfilter filt filtered filtered amp
Xdriver filtered driven driven amp
Riso driven adc 47
Cadc adc 0 20p
Radc adc 0 10meg
"""
    )
