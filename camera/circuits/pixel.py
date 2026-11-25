from PySpice.Spice.Netlist import SubCircuit


def pixel() -> SubCircuit:
    cell = SubCircuit(
        "pixel",
        "pd",
        "vr",
        "rst",
        "refgate",
        "siggate",
        "sel",
        "br",
        "bs",
        ci="100p",
        ch="1n",
        rl="1e12",
        dark="2p",
        vos="100u",
    )
    cell.raw_spice = """
Dphoto 0 pd silicon
Cjunction pd 0 4p
Cintegration pd 0 {ci}
Rintegration pd 0 10T
Idark pd 0 {dark}
Ibias pd 0 0.2p
Sreset pd vr rst 0 gate
Bfollower buf 0 V=max(0.02,min(v(vdd)-0.02,v(pd)+vos))
Rout buf drive 50
"""
    for node, gate, bus in [("hr", "refgate", "br"), ("hs", "siggate", "bs")]:
        cell.raw_spice += f"""
S{node} drive {node} {gate} 0 gate
C{node} {node} 0 {{ch}}
R{node} {node} 0 {{rl}}
I{node} {node} 0 0.2p
E{node} source{node} 0 {node} 0 1
Rout{node} source{node} pin{node} 50
Sread{node} pin{node} {bus} sel 0 gate
"""
    return cell


MODELS = """
.global vdd
.model gate SW(Ron=50 Roff=1e14 Vt=1.65 Vh=0.05)
.model silicon D(Is=1e-14 N=1.2)
"""
