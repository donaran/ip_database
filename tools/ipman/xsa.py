"""Extract an IP manifest from a Vivado .xsa archive.

An .xsa is a zip container. For any design built from a block design it holds
one or more hardware-handoff files (*.hwh), an XML dump of the elaborated
system. Every IP instance appears as a MODULE element::

    <MODULE FULLNAME="/pwm_ctrl_0" INSTANCE="pwm_ctrl_0" MODTYPE="pwm_ctrl"
            VLNV="acme.com:user:pwm_ctrl:1.2">

The VLNV field (vendor:library:name:version) is what the driver database is
keyed on, so it is the only field the rest of the pipeline strictly needs.
Base addresses are picked up opportunistically because they are free here and
make the generated instance header useful.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from . import SCHEMA, __version__
from .util import IpmanError, sha256_file, utc_now

# Anything shipped by Xilinx under a stock library is treated as vendor IP: it
# is not flagged custom, and by default it is not resolved to a driver.
VENDOR_VENDORS = {"xilinx.com"}
VENDOR_LIBRARIES = {"ip", "ip_bd", "bd", "module_ref"}

# Modules that are structural rather than addressable IP.
SKIP_MODTYPES = {"hierarchy"}

BASE_PARAM_HINTS = ("C_S_AXI_BASEADDR", "C_BASEADDR", "C_S00_AXI_BASEADDR",
                    "C_S_AXI_CONTROL_BASEADDR")
HIGH_PARAM_HINTS = ("C_S_AXI_HIGHADDR", "C_HIGHADDR", "C_S00_AXI_HIGHADDR",
                    "C_S_AXI_CONTROL_HIGHADDR")


@dataclass
class IpInstance:
    instance: str
    fullname: str
    vlnv: str
    vendor: str
    library: str
    name: str
    version: str
    modtype: str = ""
    base_address: str | None = None
    high_address: str | None = None
    custom: bool = True

    @property
    def ip_key(self) -> str:
        """vendor:library:name -- the database key (version excluded)."""
        return "%s:%s:%s" % (self.vendor, self.library, self.name)


def split_vlnv(vlnv: str) -> tuple[str, str, str, str]:
    parts = vlnv.split(":")
    if len(parts) != 4:
        raise IpmanError("malformed VLNV %r: expected vendor:library:name:version" % vlnv)
    return parts[0], parts[1], parts[2], parts[3]


def is_custom(vendor: str, library: str) -> bool:
    return not (vendor in VENDOR_VENDORS and library in VENDOR_LIBRARIES)


def _hwh_members(zf: zipfile.ZipFile) -> list[str]:
    return sorted(n for n in zf.namelist() if n.lower().endswith(".hwh"))


def _norm_addr(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        return "0x%08X" % int(value, 0)
    except ValueError:
        return value


def _collect_memranges(root: ET.Element) -> dict:
    """Address map as seen by the processors, keyed by slave instance name."""
    ranges: dict = {}
    for mr in root.iter("MEMRANGE"):
        inst = mr.get("INSTANCE")
        if not inst:
            continue
        base = _norm_addr(mr.get("BASEVALUE") or mr.get("BASEADDR"))
        high = _norm_addr(mr.get("HIGHVALUE") or mr.get("HIGHADDR"))
        if base is None:
            continue
        # Keep the lowest base if an instance is mapped from several masters.
        prev = ranges.get(inst)
        if prev is None or (prev[0] or "") > base:
            ranges[inst] = (base, high)
    return ranges


def _module_params(module: ET.Element) -> dict:
    params: dict = {}
    for p in module.iter("PARAMETER"):
        name = p.get("NAME")
        if name:
            params[name] = p.get("VALUE", "")
    return params


def parse_hwh(xml_text: str):
    root = ET.fromstring(xml_text)
    memranges = _collect_memranges(root)

    info = {
        "vivado_version": root.get("VIVADO_VERSION") or root.get("TOOL_VERSION"),
        "design": root.get("NAME") or root.get("DESIGN"),
    }
    sysinfo = root.find(".//SYSTEMINFO")
    if sysinfo is not None:
        info["arch"] = sysinfo.get("ARCH")
        info["device"] = sysinfo.get("DEVICE") or sysinfo.get("PART")
    info = {k: v for k, v in info.items() if v}

    ips: list = []
    seen: set = set()
    for module in root.iter("MODULE"):
        vlnv = module.get("VLNV")
        if not vlnv:
            continue
        if module.get("MODTYPE", "") in SKIP_MODTYPES:
            continue
        fullname = module.get("FULLNAME") or "/" + module.get("INSTANCE", "")
        instance = module.get("INSTANCE") or fullname.rsplit("/", 1)[-1]
        if fullname in seen:
            continue
        seen.add(fullname)

        vendor, library, name, version = split_vlnv(vlnv)
        base, high = memranges.get(instance, (None, None))
        if base is None:
            params = _module_params(module)
            for hint in BASE_PARAM_HINTS:
                if params.get(hint):
                    base = _norm_addr(params[hint])
                    break
            for hint in HIGH_PARAM_HINTS:
                if params.get(hint):
                    high = _norm_addr(params[hint])
                    break

        ips.append(IpInstance(
            instance=instance,
            fullname=fullname,
            vlnv=vlnv,
            vendor=vendor,
            library=library,
            name=name,
            version=version,
            modtype=module.get("MODTYPE", ""),
            base_address=base,
            high_address=high,
            custom=is_custom(vendor, library),
        ))

    ips.sort(key=lambda i: i.fullname)
    return ips, info


def extract(xsa_path) -> dict:
    """Build the manifest dict for an .xsa (or a bare .hwh, for testing)."""
    xsa_path = Path(xsa_path)
    if not xsa_path.exists():
        raise IpmanError("no such file: %s" % xsa_path)

    if xsa_path.suffix.lower() == ".hwh":
        ips, info = parse_hwh(xsa_path.read_text(encoding="utf-8"))
        hwh_names = [xsa_path.name]
    else:
        if not zipfile.is_zipfile(xsa_path):
            raise IpmanError("%s is not a zip archive; is it really an .xsa?" % xsa_path)
        with zipfile.ZipFile(xsa_path) as zf:
            hwh_names = _hwh_members(zf)
            if not hwh_names:
                raise IpmanError(
                    "%s contains no .hwh file. XSAs exported from a non-block-design "
                    "flow carry no IP metadata to harvest." % xsa_path.name)
            ips, info = [], {}
            seen = set()
            for member in hwh_names:
                part_ips, part_info = parse_hwh(zf.read(member).decode("utf-8", "replace"))
                for ip in part_ips:
                    if ip.fullname not in seen:
                        seen.add(ip.fullname)
                        ips.append(ip)
                for k, v in part_info.items():
                    info.setdefault(k, v)
            ips.sort(key=lambda i: i.fullname)

    source = {"file": xsa_path.name, "sha256": sha256_file(xsa_path), "hwh": hwh_names}
    source.update(info)
    return {
        "schema": SCHEMA,
        "kind": "ip-manifest",
        "generated": utc_now(),
        "generator": "ipman %s" % __version__,
        "source": source,
        "ips": [asdict(ip) for ip in ips],
    }


def manifest_to_text(manifest: dict, only_custom: bool = False) -> str:
    rows = [ip for ip in manifest["ips"] if ip["custom"] or not only_custom]
    if not rows:
        return "%s: no IP instances" % manifest["source"]["file"]
    wi = max([len("INSTANCE")] + [len(r["instance"]) for r in rows])
    wv = max([len("VLNV")] + [len(r["vlnv"]) for r in rows])
    out = ["%s  (%d IP instances)" % (manifest["source"]["file"], len(rows)), ""]
    out.append("%-*s  %-*s  %-10s  %s" % (wi, "INSTANCE", wv, "VLNV", "BASE", "KIND"))
    out.append("%s  %s  %s  %s" % ("-" * wi, "-" * wv, "-" * 10, "----"))
    for r in rows:
        out.append("%-*s  %-*s  %-10s  %s" % (
            wi, r["instance"], wv, r["vlnv"],
            r["base_address"] or "-", "custom" if r["custom"] else "vendor"))
    return "\n".join(out)
