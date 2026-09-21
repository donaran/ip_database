"""Build a synthetic design_1.xsa so the pipeline can be exercised without Vivado.

The .hwh written here mirrors the structure Vivado emits for a Zynq-7000 block
design: an EDKSYSTEM root, a MODULES list where every IP carries its VLNV, and
the processor's MEMRANGES giving each slave its base address.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# instance, modtype, vlnv, base, high  (base None -> not memory mapped)
IPS = [
    ("processing_system7_0", "processing_system7",
     "xilinx.com:ip:processing_system7:5.5", None, None),
    ("ps7_axi_periph", "axi_interconnect",
     "xilinx.com:ip:axi_interconnect:2.1", None, None),
    ("rst_ps7_100M", "proc_sys_reset",
     "xilinx.com:ip:proc_sys_reset:5.0", None, None),
    ("axi_gpio_0", "axi_gpio",
     "xilinx.com:ip:axi_gpio:2.0", "0x41200000", "0x4120FFFF"),
    # --- custom IP below -------------------------------------------------
    ("pwm_ctrl_0", "pwm_ctrl",
     "acme.com:user:pwm_ctrl:1.2", "0x43C00000", "0x43C0FFFF"),
    ("pwm_ctrl_1", "pwm_ctrl",
     "acme.com:user:pwm_ctrl:1.2", "0x43C10000", "0x43C1FFFF"),
    ("adc_stream_0", "adc_stream",
     "acme.com:user:adc_stream:2.0", "0x43C20000", "0x43C2FFFF"),
    ("axi_gpio_lite_0", "axi_gpio_lite",
     "acme.com:user:axi_gpio_lite:1.0", "0x43C30000", "0x43C3FFFF"),
    # Deliberately absent from the driver database: shows up as unresolved.
    ("crypto_accel_0", "crypto_accel",
     "acme.com:hls:crypto_accel:3.1", "0x43C40000", "0x43C4FFFF"),
]


def build_hwh() -> str:
    memranges = "\n".join(
        '        <MEMRANGE INSTANCE="%s" BASENAME="C_S_AXI_BASEADDR" '
        'BASEVALUE="%s" HIGHVALUE="%s" MEMTYPE="REGISTER" '
        'MASTERBUSINTERFACE="M_AXI_GP0" SLAVEBUSINTERFACE="S_AXI"/>'
        % (name, base, high)
        for name, _mt, _vlnv, base, high in IPS if base)

    modules = []
    for name, modtype, vlnv, base, high in IPS:
        body = ""
        if name == "processing_system7_0":
            body = "\n      <MEMRANGES>\n%s\n      </MEMRANGES>" % memranges
        elif base:
            body = (
                "\n      <PARAMETERS>"
                '\n        <PARAMETER NAME="C_S_AXI_BASEADDR" VALUE="%s"/>'
                '\n        <PARAMETER NAME="C_S_AXI_HIGHADDR" VALUE="%s"/>'
                "\n      </PARAMETERS>" % (base, high))
        modules.append(
            '    <MODULE FULLNAME="/%s" INSTANCE="%s" MODTYPE="%s" VLNV="%s" '
            'IPTYPE="PERIPHERAL" HWVERSION="%s">%s\n    </MODULE>'
            % (name, name, modtype, vlnv, vlnv.rsplit(":", 1)[-1], body))

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<EDKSYSTEM NAME="design_1" VIVADO_VERSION="2024.1" ARCH="zynq" '
        'TIMESTAMP="Mon Sep 21 10:00:00 2026">\n'
        '  <SYSTEMINFO ARCH="zynq" DEVICE="7z020" PACKAGE="clg400" SPEED="-1"/>\n'
        '  <MODULES>\n%s\n  </MODULES>\n'
        '</EDKSYSTEM>\n' % "\n".join(modules))


SYSDEF = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<sysdef version="1.0" name="design_1_wrapper">\n'
    '  <files>\n'
    '    <file name="design_1.hwh" type="HW_HANDOFF"/>\n'
    '    <file name="design_1_wrapper.bit" type="BIT"/>\n'
    '  </files>\n'
    '</sysdef>\n')


def main(argv=None) -> int:
    out = Path(argv[0]) if argv else HERE / "design_1.xsa"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("design_1.hwh", build_hwh())
        zf.writestr("sysdef.xml", SYSDEF)
        zf.writestr("design_1_wrapper.bit", b"\x00" * 64)  # placeholder
    print("wrote %s (%d IP, %d custom)"
          % (out, len(IPS), sum(1 for i in IPS if not i[2].startswith("xilinx.com:ip:"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
