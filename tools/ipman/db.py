"""The shared driver database: one JSON file mapping IP -> driver source.

Layout::

    {
      "schema": 1,
      "kind": "ip-driver-db",
      "db_version": "1.3.0",          # semver, bumped on every published edit
      "updated": "2026-09-21T12:00:00Z",
      "drivers": {
        "acme.com:user:pwm_ctrl": {           # vendor:library:name, no version
          "summary": "PWM controller register driver",
          "owner": "fpga-team@acme.com",
          "versions": [
            {"match": "1.*", "type": "git",
             "uri": "${CORP_GIT}/fpga/drivers/pwm_ctrl.git",
             "ref": "v1.4.0", "subdir": "", "target": "ipdrv_pwm_ctrl"}
          ]
        }
      },
      "changelog": [ ... ]
    }

The key deliberately excludes the IP version: one IP has one entry, and the
`versions` list maps hardware versions to driver revisions.  `match` accepts an
exact version ("1.2"), a glob ("1.*") or "*" as the catch-all.  The most
specific match wins, so entry order in the file does not change behaviour.

Three source types are supported:
  git     - cloned by CMake FetchContent at `ref` (tag/branch/sha)
  path    - a directory, absolute or relative to the database file
  archive - a tarball/zip URL (e.g. an Artifactory generic repo) plus sha256
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from . import SCHEMA
from .gitref import REF_TYPES, SHA_RE, classify, is_templated
from .util import IpmanError, expand_env, read_json, utc_now, write_json_atomic

SOURCE_TYPES = ("git", "path", "archive")
KEY_RE = re.compile(r"^[^:\s]+:[^:\s]+:[^:\s]+$")
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def empty_db() -> dict:
    return {
        "schema": SCHEMA,
        "kind": "ip-driver-db",
        "db_version": "0.1.0",
        "updated": utc_now(),
        "drivers": {},
        "changelog": [],
    }


def load(path) -> dict:
    path = Path(path)
    if not path.exists():
        raise IpmanError("driver database not found: %s" % path)
    db = read_json(path)
    validate(db, path)
    return db


def load_many(paths) -> dict:
    """Load one or more databases, later files overriding earlier ones.

    This is how a globally shared database and a project-local overlay are
    combined: `--db global.json --db project.json`.  An overlay may add IP,
    replace a version rule with the same `match`, or pin a different driver
    revision, without editing the shared file.
    """
    paths = [Path(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)]
    if not paths:
        raise IpmanError("no driver database given")

    merged = None
    for path in paths:
        current = load(path)
        # Remember where each rule came from so relative 'path' URIs resolve
        # against their own database file.
        for entry in current["drivers"].values():
            for rule in entry.get("versions", []):
                rule["_db"] = path.as_posix()
        if merged is None:
            merged = current
            merged["_sources"] = [{"path": path.as_posix(),
                                   "db_version": current["db_version"]}]
            continue
        merged["_sources"].append({"path": path.as_posix(),
                                   "db_version": current["db_version"]})
        merged["db_version"] = "%s+%s" % (merged["db_version"], current["db_version"])
        for key, entry in current["drivers"].items():
            base = merged["drivers"].setdefault(
                key, {"summary": "", "owner": "", "versions": []})
            for field in ("summary", "owner"):
                if entry.get(field):
                    base[field] = entry[field]
            by_match = {r["match"]: i for i, r in enumerate(base["versions"])}
            for rule in entry.get("versions", []):
                if rule["match"] in by_match:
                    base["versions"][by_match[rule["match"]]] = rule
                else:
                    base["versions"].append(rule)
            base["versions"].sort(key=lambda r: r["match"])
    return merged


def save(path, db: dict) -> None:
    db["updated"] = utc_now()
    db["drivers"] = {k: db["drivers"][k] for k in sorted(db["drivers"])}
    write_json_atomic(Path(path), db)


def validate(db: dict, path=None) -> list:
    """Raise on anything that would break resolution; return soft warnings."""
    where = " in %s" % path if path else ""
    if db.get("kind") != "ip-driver-db":
        raise IpmanError("not a driver database%s (kind=%r)" % (where, db.get("kind")))
    if db.get("schema") != SCHEMA:
        raise IpmanError("database schema %r%s, this ipman speaks schema %d"
                         % (db.get("schema"), where, SCHEMA))
    if not SEMVER_RE.match(str(db.get("db_version", ""))):
        raise IpmanError("db_version %r%s is not MAJOR.MINOR.PATCH"
                         % (db.get("db_version"), where))

    warnings = []
    for key, entry in db.get("drivers", {}).items():
        if not KEY_RE.match(key):
            raise IpmanError("driver key %r%s must be vendor:library:name" % (key, where))
        versions = entry.get("versions")
        if not versions:
            warnings.append("%s has no version entries" % key)
            continue
        seen = set()
        for v in versions:
            match = v.get("match")
            if not match:
                raise IpmanError("%s has a version entry with no 'match'" % key)
            if match in seen:
                raise IpmanError("%s lists match %r twice" % (key, match))
            seen.add(match)
            stype = v.get("type")
            if stype not in SOURCE_TYPES:
                raise IpmanError("%s match %s: type must be one of %s, got %r"
                                 % (key, match, "/".join(SOURCE_TYPES), stype))
            if not v.get("uri"):
                raise IpmanError("%s match %s: missing 'uri'" % (key, match))
            if stype == "git":
                warnings.extend(_check_git_ref(key, match, v))
            if stype == "archive" and not v.get("sha256"):
                warnings.append("%s match %s: archive source has no 'sha256'" % (key, match))
    return warnings


def _check_git_ref(key: str, match: str, rule: dict) -> list:
    """Validate a git rule's ref/ref_type pair; return advisory warnings."""
    ref = rule.get("ref")
    declared = rule.get("ref_type")
    if declared and declared not in REF_TYPES:
        raise IpmanError("%s match %s: ref_type must be one of %s, got %r"
                         % (key, match, "/".join(REF_TYPES), declared))
    if not ref:
        return ["%s match %s: git source has no 'ref', will track the default "
                "branch (not reproducible)" % (key, match)]
    if is_templated(ref):
        return []

    kind = classify(ref, declared)
    warnings = []
    if declared == "commit" and not SHA_RE.match(ref):
        raise IpmanError("%s match %s: ref_type is 'commit' but %r is not a hex "
                         "object name" % (key, match, ref))
    if kind == "commit" and len(ref) < 40:
        warnings.append("%s match %s: abbreviated commit %r may become ambiguous; "
                        "prefer the full 40-character sha" % (key, match, ref))
    if kind == "branch":
        warnings.append("%s match %s: ref %r is a branch, so the driver moves "
                        "under you; pin a tag or a commit" % (key, match, ref))
    return warnings


def _score(pattern: str, version: str):
    """Higher is more specific; None if the pattern does not match."""
    if pattern == version:
        return 1000
    if not fnmatch.fnmatchcase(version, pattern):
        return None
    if pattern == "*":
        return 0
    return 100 + len(pattern.replace("*", "").replace("?", ""))


def lookup(db: dict, ip_key: str, version: str):
    """Return (entry, version_rule) for an IP at a hardware version, or None."""
    entry = db.get("drivers", {}).get(ip_key)
    if not entry:
        return None
    best, best_score = None, -1
    for rule in entry.get("versions", []):
        score = _score(rule["match"], version)
        if score is not None and score > best_score:
            best, best_score = rule, score
    if best is None:
        return None
    return entry, best


def default_target(ip_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", ip_name)
    return "ipdrv_" + safe


def resolve_source(rule: dict, db_path, subs: dict | None = None) -> dict:
    """Expand ${VARS} and make `path` sources absolute (relative to the db)."""
    out = dict(rule)
    db_path = out.pop("_db", None) or db_path
    for field in ("uri", "ref", "subdir"):
        if rule.get(field):
            out[field] = expand_env(str(rule[field]), subs)
    if out["type"] == "git":
        # Record what the ref turned out to be, so the lock and the generated
        # CMake do not have to guess again.
        out["ref_type"] = classify(out.get("ref"), rule.get("ref_type"))
    if out["type"] == "path":
        p = Path(out["uri"])
        if not p.is_absolute():
            p = (Path(db_path).resolve().parent / p).resolve()
        out["uri"] = p.as_posix()
    return out


# ---------------------------------------------------------------- mutations

def bump(db: dict, level: str = "patch") -> str:
    major, minor, patch = (int(x) for x in SEMVER_RE.match(db["db_version"]).groups())
    if level == "major":
        major, minor, patch = major + 1, 0, 0
    elif level == "minor":
        minor, patch = minor + 1, 0
    elif level == "patch":
        patch += 1
    else:
        raise IpmanError("bump level must be major, minor or patch")
    db["db_version"] = "%d.%d.%d" % (major, minor, patch)
    return db["db_version"]


def log_change(db: dict, message: str, author: str) -> None:
    db.setdefault("changelog", []).insert(0, {
        "db_version": db["db_version"],
        "date": utc_now(),
        "author": author,
        "change": message,
    })
    del db["changelog"][50:]


def add_driver(db: dict, key: str, match: str, source: dict,
               summary: str = "", owner: str = "", replace: bool = False) -> str:
    """Insert or update one version rule. Returns a human-readable action."""
    if not KEY_RE.match(key):
        raise IpmanError("driver key %r must be vendor:library:name (no version)" % key)
    if source.get("type") not in SOURCE_TYPES:
        raise IpmanError("type must be one of %s" % "/".join(SOURCE_TYPES))

    entry = db["drivers"].setdefault(key, {"summary": "", "owner": "", "versions": []})
    if summary:
        entry["summary"] = summary
    if owner:
        entry["owner"] = owner
    entry.setdefault("versions", [])

    rule = {"match": match}
    rule.update({k: v for k, v in source.items() if v not in (None, "")})

    for i, existing in enumerate(entry["versions"]):
        if existing["match"] == match:
            if not replace:
                raise IpmanError(
                    "%s already has a rule for match %r; pass --replace to overwrite"
                    % (key, match))
            entry["versions"][i] = rule
            entry["versions"].sort(key=lambda r: r["match"])
            return "updated %s [%s]" % (key, match)

    entry["versions"].append(rule)
    entry["versions"].sort(key=lambda r: r["match"])
    return "added %s [%s]" % (key, match)


def remove_driver(db: dict, key: str, match: str | None = None) -> str:
    entry = db["drivers"].get(key)
    if not entry:
        raise IpmanError("no such driver: %s" % key)
    if match is None:
        del db["drivers"][key]
        return "removed %s (all versions)" % key
    before = len(entry["versions"])
    entry["versions"] = [r for r in entry["versions"] if r["match"] != match]
    if len(entry["versions"]) == before:
        raise IpmanError("%s has no rule matching %r" % (key, match))
    if not entry["versions"]:
        del db["drivers"][key]
        return "removed %s [%s] (entry now empty, dropped)" % (key, match)
    return "removed %s [%s]" % (key, match)


def to_text(db: dict) -> str:
    out = ["driver database v%s  (updated %s, %d IP)"
           % (db["db_version"], db["updated"], len(db["drivers"])), ""]
    for key in sorted(db["drivers"]):
        entry = db["drivers"][key]
        head = key
        if entry.get("summary"):
            head += "  - " + entry["summary"]
        out.append(head)
        for rule in entry.get("versions", []):
            detail = "%s %s" % (rule["type"], rule["uri"])
            if rule.get("ref"):
                kind = ("templated" if is_templated(rule["ref"])
                        else classify(rule["ref"], rule.get("ref_type")))
                detail += " @ %s (%s)" % (rule["ref"], kind)
            if rule.get("subdir"):
                detail += " [" + rule["subdir"] + "]"
            out.append("    %-10s -> %s" % (rule["match"], detail))
        out.append("")
    return "\n".join(out).rstrip() + "\n"
