"""Regenerate everything PeakRDL owns for this driver package.

The single place the exporter flags live. Run it after editing
rdl/pwm_ctrl.rdl, commit the result, and CI re-runs it with --check to
confirm the committed output still matches the register description.

    python regenerate.py              # rewrite generated/
    python regenerate.py --check      # fail if generated/ is stale
    python regenerate.py --out DIR    # write somewhere else

PeakRDL is not a build dependency of the driver: the generated files are
committed so a consumer needs only a C++ toolchain. This script is for whoever
changes the registers.

    pip install peakrdl peakrdl-regblock-vhdl
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RDL = HERE / "rdl" / "pwm_ctrl.rdl"
GENERATED = HERE / "generated"

# Every hardware revision the driver serves gets its own elaboration.
TOPS = ("pwm_ctrl_v1", "pwm_ctrl_v2")

# axi4-lite-flat, not axi4-lite: the flat form gives plain std_logic_vector
# ports with the conventional AXI signal names, which Vivado's IP packager
# infers as an AXI4-Lite interface on its own. The record form relies on
# VHDL-2008 record element constraints at the entity boundary.
CPUIF = "axi4-lite-flat"


def peakrdl(exe: str, *args) -> None:
    cmd = [exe, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit("failed: %s" % " ".join(cmd))


def generate(out_dir: Path, exe: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for top in TOPS:
        # C header for the driver. The struct overlay uses GCC's
        # __attribute__((packed)); include/peakrdl_compat.hpp neutralises that
        # for MSVC host builds.
        peakrdl(exe, "c-header", str(RDL), "-t", top,
                "-o", str(out_dir / ("%s.h" % top)), "-b", "ltoh")

        # VHDL register block plus its support package.
        peakrdl(exe, "regblock-vhdl", str(RDL), "-t", top,
                "-o", str(out_dir), "--cpuif", CPUIF,
                "--copy-utils-pkg", "--hwif-report")


def compare(reference: Path, candidate: Path) -> list:
    """Files that differ, are missing, or are unexpected."""
    names = {p.name for p in reference.glob("*")} | {p.name for p in candidate.glob("*")}
    bad = []
    for name in sorted(names):
        a, b = reference / name, candidate / name
        if not a.is_file():
            bad.append("%s: not committed" % name)
        elif not b.is_file():
            bad.append("%s: no longer generated" % name)
        elif not filecmp.cmp(a, b, shallow=False):
            bad.append("%s: differs" % name)
    return bad


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify generated/ is up to date, write nothing")
    parser.add_argument("--out", help="write here instead of generated/")
    parser.add_argument("--peakrdl", default="peakrdl",
                        help="path to the peakrdl executable")
    args = parser.parse_args(argv)

    if not shutil.which(args.peakrdl) and not Path(args.peakrdl).is_file():
        raise SystemExit(
            "peakrdl not found (%s). Install it with:\n"
            "    pip install peakrdl peakrdl-regblock-vhdl" % args.peakrdl)

    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "generated"
            generate(candidate, args.peakrdl)
            stale = compare(GENERATED, candidate)
        if stale:
            print("generated/ is out of date with %s:" % RDL.name)
            for item in stale:
                print("  %s" % item)
            print("\nRun: python %s" % Path(__file__).name)
            return 1
        print("generated/ matches %s" % RDL.name)
        return 0

    out = Path(args.out) if args.out else GENERATED
    generate(out, args.peakrdl)
    print("regenerated %s from %s" % (out, RDL.name))
    for path in sorted(out.glob("*")):
        print("  %s" % path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
