"""Join an IP manifest against the driver database to produce a lock file.

The lock is the contract with CMake: one record per (IP, hardware version)
pair, carrying the exact source to fetch and the target name the driver is
expected to define.  Two instances of the same IP at the same version share one
driver; the same IP at two versions yields two drivers with distinct targets.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import SCHEMA, __version__
from .db import default_target, lookup, resolve_source
from .util import IpmanError, utc_now


def _version_suffix(version: str) -> str:
    return "v" + re.sub(r"[^A-Za-z0-9]", "_", version)


def resolve(manifest: dict, db: dict, db_path, include_vendor: bool = False,
            strict: bool = False, subs: dict | None = None) -> dict:
    groups: dict = {}
    order: list = []
    skipped_vendor = 0

    for ip in manifest["ips"]:
        if not ip["custom"] and not include_vendor:
            skipped_vendor += 1
            continue
        ip_key = "%s:%s:%s" % (ip["vendor"], ip["library"], ip["name"])
        gkey = (ip_key, ip["version"])
        if gkey not in groups:
            groups[gkey] = {"ip": ip_key, "name": ip["name"],
                            "ip_version": ip["version"], "instances": []}
            order.append(gkey)
        groups[gkey]["instances"].append({
            "instance": ip["instance"],
            "fullname": ip["fullname"],
            "base_address": ip["base_address"],
            "high_address": ip["high_address"],
        })

    drivers, unresolved = [], []
    # A design may carry the same IP at two versions; keep target names unique.
    name_counts: dict = {}
    for gkey in order:
        name_counts[groups[gkey]["name"]] = name_counts.get(groups[gkey]["name"], 0) + 1

    for gkey in order:
        group = groups[gkey]
        hit = lookup(db, group["ip"], group["ip_version"])
        if hit is None:
            entry = db.get("drivers", {}).get(group["ip"])
            reason = ("no rule for version %s (database has %s)"
                      % (group["ip_version"],
                         ", ".join(r["match"] for r in entry.get("versions", [])) or "none")
                      ) if entry else "no database entry for %s" % group["ip"]
            unresolved.append({
                "ip": group["ip"],
                "ip_version": group["ip_version"],
                "instances": [i["instance"] for i in group["instances"]],
                "reason": reason,
            })
            continue

        entry, rule = hit
        target = rule.get("target") or default_target(group["name"])
        if name_counts[group["name"]] > 1 and not rule.get("target"):
            target = "%s_%s" % (target, _version_suffix(group["ip_version"]))

        drivers.append({
            "ip": group["ip"],
            "ip_version": group["ip_version"],
            "matched": rule["match"],
            "target": target,
            "summary": entry.get("summary", ""),
            "owner": entry.get("owner", ""),
            "source": resolve_source(rule, db_path, subs),
            "instances": group["instances"],
        })

    if strict and unresolved:
        lines = ["%s (%s) used by %s: %s" % (u["ip"], u["ip_version"],
                                             ", ".join(u["instances"]), u["reason"])
                 for u in unresolved]
        raise IpmanError("unresolved custom IP:\n  " + "\n  ".join(lines))

    return {
        "schema": SCHEMA,
        "kind": "ip-driver-lock",
        "generated": utc_now(),
        "generator": "ipman %s" % __version__,
        "db_version": db["db_version"],
        "db_path": Path(db_path).resolve().as_posix(),
        "source": manifest["source"],
        "drivers": drivers,
        "unresolved": unresolved,
        "skipped_vendor_ip": skipped_vendor,
    }


def lock_to_text(lock: dict) -> str:
    out = ["resolved against driver database v%s" % lock["db_version"], ""]
    if lock["drivers"]:
        for d in lock["drivers"]:
            src = d["source"]
            detail = "%s %s" % (src["type"], src["uri"])
            if src.get("ref"):
                detail += " @ " + src["ref"]
            out.append("  %s %s -> %s" % (d["ip"], d["ip_version"], d["target"]))
            out.append("      %s" % detail)
            out.append("      instances: %s"
                       % ", ".join(i["instance"] for i in d["instances"]))
    else:
        out.append("  (no drivers resolved)")
    if lock["unresolved"]:
        out.append("")
        out.append("  UNRESOLVED:")
        for u in lock["unresolved"]:
            out.append("    %s %s (%s) - %s"
                       % (u["ip"], u["ip_version"], ", ".join(u["instances"]), u["reason"]))
    return "\n".join(out)
