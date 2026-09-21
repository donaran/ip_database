"""The driver-side manifest: what a driver package claims to implement.

`ipman-driver.json` sits in the root of a driver package (or in its `subdir`)
and is the driver's half of the contract the database describes::

    {
      "schema": 1,
      "kind": "ipman-driver",
      "driver_version": "1.4.0",
      "target": "ipdrv_pwm_ctrl",
      "implements": [
        {"ip": "acme.com:user:pwm_ctrl", "match": "1.*",
         "map": {"type": "acme::PwmCtrlV1", "header": "pwm_ctrl_v1.hpp"}},
        {"ip": "acme.com:user:pwm_ctrl", "match": "2.*",
         "map": {"type": "acme::PwmCtrlV2", "header": "pwm_ctrl_v2.hpp"}}
      ],
      "id_register": {
        "offset": "0x00",
        "magic": {"value": "0x5057", "bits": [31, 16]},
        "major": {"bits": [15, 8]},
        "minor": {"bits": [7, 0]}
      },
      "register_model": {"source": "rdl/pwm_ctrl.rdl", "sha256": "..."}
    }

Why it exists: the database says "IP version 1.2 is served by this git tag",
but nothing checked that whatever is at that tag actually implements 1.2. A
re-tagged repo, a bad `--replace`, or a copy-pasted rule produces a driver that
compiles cleanly against the wrong register map and fails on hardware. The
manifest lets `ipman_configure()` fail at configure time instead.

`implements[].match` uses the same semantics as the database: an exact version,
a glob, or `*`. `map` and `id_register` are optional -- a driver that serves one
revision and has no ID register still gets verified, it just gets no runtime
register-map dispatch.
"""
from __future__ import annotations

from pathlib import Path

from . import SCHEMA
from .db import KEY_RE, _score
from .util import IpmanError, read_json, sha256_file, utc_now

MANIFEST_NAME = "ipman-driver.json"


def _as_int(value, what: str) -> int:
    """Accept 16, "16" or "0x10" -- JSON has no hex literal."""
    if isinstance(value, bool):
        raise IpmanError("%s must be a number, got a boolean" % what)
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        raise IpmanError("%s must be an integer or a hex string, got %r"
                         % (what, value))


def _bits(spec, what: str):
    """Validate an [msb, lsb] pair and return it normalised."""
    if not isinstance(spec, (list, tuple)) or len(spec) != 2:
        raise IpmanError("%s must be [msb, lsb]" % what)
    msb, lsb = _as_int(spec[0], what + " msb"), _as_int(spec[1], what + " lsb")
    if not 0 <= lsb <= msb <= 31:
        raise IpmanError("%s must satisfy 0 <= lsb <= msb <= 31, got [%d, %d]"
                         % (what, msb, lsb))
    return [msb, lsb]


def manifest_path(source_dir, subdir: str | None = None):
    """Where the manifest should be: under `subdir` first, then the root."""
    root = Path(source_dir)
    candidates = []
    if subdir:
        candidates.append(root / subdir.strip("/") / MANIFEST_NAME)
    candidates.append(root / MANIFEST_NAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load(path) -> dict:
    manifest = read_json(Path(path))
    validate(manifest, path)
    return manifest


def validate(manifest: dict, path=None) -> list:
    where = " in %s" % path if path else ""
    if manifest.get("kind") != "ipman-driver":
        raise IpmanError("not a driver manifest%s (kind=%r)"
                         % (where, manifest.get("kind")))
    if manifest.get("schema") != SCHEMA:
        raise IpmanError("driver manifest schema %r%s, this ipman speaks schema %d"
                         % (manifest.get("schema"), where, SCHEMA))

    implements = manifest.get("implements")
    if not implements:
        raise IpmanError("driver manifest%s declares no 'implements' entries" % where)

    warnings = []
    wants_dispatch = False
    for entry in implements:
        ip = entry.get("ip")
        if not ip or not KEY_RE.match(ip):
            raise IpmanError("implements entry%s has a bad 'ip': %r" % (where, ip))
        if not entry.get("match"):
            raise IpmanError("implements entry for %s%s has no 'match'" % (ip, where))
        mapping = entry.get("map")
        if mapping is None:
            continue
        wants_dispatch = True
        for field in ("type", "header"):
            if not mapping.get(field):
                raise IpmanError("%s match %s%s: map needs a %r"
                                 % (ip, entry["match"], where, field))

    id_reg = manifest.get("id_register")
    if wants_dispatch and not id_reg:
        raise IpmanError(
            "driver manifest%s declares register maps but no 'id_register'; "
            "without one there is no way to tell revisions apart at runtime" % where)
    if id_reg:
        _as_int(id_reg.get("offset", 0), "id_register.offset")
        magic = id_reg.get("magic")
        if not magic:
            raise IpmanError("id_register%s needs a 'magic'" % where)
        _as_int(magic.get("value"), "id_register.magic.value")
        _bits(magic.get("bits"), "id_register.magic.bits")
        for field in ("major", "minor"):
            if not id_reg.get(field):
                raise IpmanError("id_register%s needs a %r" % (where, field))
            _bits(id_reg[field].get("bits"), "id_register.%s.bits" % field)

    if not manifest.get("target"):
        warnings.append("manifest declares no 'target'; the name cannot be checked")
    return warnings


def normalise_id_register(id_reg: dict) -> dict:
    """Turn the loose JSON form into plain integers for code generation."""
    return {
        "offset": _as_int(id_reg.get("offset", 0), "id_register.offset"),
        "magic_value": _as_int(id_reg["magic"]["value"], "id_register.magic.value"),
        "magic_bits": _bits(id_reg["magic"]["bits"], "id_register.magic.bits"),
        "major_bits": _bits(id_reg["major"]["bits"], "id_register.major.bits"),
        "minor_bits": _bits(id_reg["minor"]["bits"], "id_register.minor.bits"),
    }


def covers(manifest: dict, ip_key: str, version: str):
    """Best `implements` entry for an IP at a version, or None."""
    best, best_score = None, -1
    for entry in manifest["implements"]:
        if entry["ip"] != ip_key:
            continue
        score = _score(entry["match"], version)
        if score is not None and score > best_score:
            best, best_score = entry, score
    return best


def maps_for(manifest: dict, ip_key: str) -> list:
    """Every register map the driver offers for one IP, any revision.

    The runtime union covers all of them, not just the revision in today's
    bitstream -- that is the point of dispatching at runtime.
    """
    out = []
    for entry in manifest["implements"]:
        if entry["ip"] == ip_key and entry.get("map"):
            out.append({"match": entry["match"],
                        "type": entry["map"]["type"],
                        "header": entry["map"]["header"]})
    return out


def check_register_model(manifest: dict, source_dir) -> list:
    """If the package ships the register source, confirm it is the one recorded."""
    model = manifest.get("register_model")
    if not model or not model.get("source") or not model.get("sha256"):
        return []
    path = Path(source_dir) / model["source"]
    if not path.is_file():
        return ["register_model.source %s is not in the package" % model["source"]]
    actual = sha256_file(path)
    if actual != model["sha256"]:
        raise IpmanError(
            "%s does not match the sha256 recorded in the driver manifest "
            "(recorded %s, found %s). The register description and the manifest "
            "have drifted apart." % (model["source"], model["sha256"][:16],
                                     actual[:16]))
    return []


def verify(source_dir, ip_key: str, ip_version: str, target: str,
           subdir: str | None = None, require: bool = False) -> dict:
    """Check a fetched driver package against what the lock expected.

    Returns a record for the code generator. Raises if the package is present
    and contradicts the lock; a package with no manifest at all is only an
    error when `require` is set.
    """
    path = manifest_path(source_dir, subdir)
    if path is None:
        if require:
            raise IpmanError(
                "%s has no %s, and --require-manifest was given"
                % (source_dir, MANIFEST_NAME))
        return {"target": target, "ip": ip_key, "ip_version": ip_version,
                "status": "no-manifest", "warnings": [], "maps": [],
                "source_dir": Path(source_dir).as_posix()}

    manifest = load(path)
    warnings = validate(manifest, path)
    root = path.parent

    declared_target = manifest.get("target")
    if declared_target and target and declared_target != target:
        raise IpmanError(
            "driver at %s declares target %r but the database expects %r"
            % (root, declared_target, target))

    entry = covers(manifest, ip_key, ip_version)
    if entry is None:
        claimed = ", ".join(sorted(
            "%s %s" % (e["ip"], e["match"]) for e in manifest["implements"]))
        raise IpmanError(
            "driver at %s does not implement %s %s.\n"
            "  It claims: %s\n"
            "  Either the database points at the wrong driver revision, or the "
            "driver needs an 'implements' entry for this hardware version."
            % (root, ip_key, ip_version, claimed or "nothing"))

    warnings.extend(check_register_model(manifest, root))

    return {
        "schema": SCHEMA,
        "kind": "ipman-driver-record",
        "generated": utc_now(),
        "target": target,
        "ip": ip_key,
        "ip_name": ip_key.split(":")[-1],
        "ip_version": ip_version,
        "matched": entry["match"],
        "driver_version": manifest.get("driver_version", ""),
        "source_dir": root.as_posix(),
        "status": "ok",
        "warnings": warnings,
        "id_register": (normalise_id_register(manifest["id_register"])
                        if manifest.get("id_register") else None),
        "maps": maps_for(manifest, ip_key),
    }
