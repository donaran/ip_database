"""Command line entry point: python -m ipman <command>."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from . import __version__
from . import artifactory as art
from . import db as dbmod
from . import xsa as xsamod
from .cmakegen import generate_cmake, generate_header
from .resolve import lock_to_text, resolve
from .util import IpmanError, read_json, write_json_atomic


def _db_paths(args):
    """--db is repeatable: global database first, project overlays after."""
    paths = args.db if isinstance(args.db, list) else [args.db]
    paths = [p for p in paths if p]
    if not paths:
        raise IpmanError("no driver database given (--db, or set IPMAN_DB)")
    return paths


def _subs(pairs, project_root=None):
    out = {}
    if project_root:
        out["PROJECT_ROOT"] = Path(project_root).resolve().as_posix()
    for item in pairs or []:
        if "=" not in item:
            raise IpmanError("--define expects VAR=VALUE, got %r" % item)
        key, value = item.split("=", 1)
        out[key] = value
    return out


def default_db_path() -> str:
    return os.environ.get("IPMAN_DB", "db/ip-drivers.json")


def _emit(text: str, out_path):
    if out_path in (None, "-"):
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    else:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print("wrote %s" % path)


def _load_manifest(args):
    if getattr(args, "manifest", None):
        manifest = read_json(Path(args.manifest))
        if manifest.get("kind") != "ip-manifest":
            raise IpmanError("%s is not an ip-manifest" % args.manifest)
        return manifest
    return xsamod.extract(args.xsa)


# ------------------------------------------------------------------ commands

def cmd_extract(args) -> int:
    manifest = xsamod.extract(args.xsa)
    if args.format == "json":
        if args.output in (None, "-"):
            print(json.dumps(manifest, indent=2))
        else:
            write_json_atomic(Path(args.output), manifest)
            print("wrote %s (%d IP instances)" % (args.output, len(manifest["ips"])))
    else:
        _emit(xsamod.manifest_to_text(manifest, args.custom_only), args.output)
    return 0


def cmd_resolve(args) -> int:
    manifest = _load_manifest(args)
    paths = _db_paths(args)
    database = dbmod.load_many(paths)
    lock = resolve(manifest, database, paths[0], include_vendor=args.include_vendor,
                   strict=args.strict, subs=_subs(args.define, args.project_root))
    if args.format == "json":
        if args.output in (None, "-"):
            print(json.dumps(lock, indent=2))
        else:
            write_json_atomic(Path(args.output), lock)
            print("wrote %s (%d drivers, %d unresolved)"
                  % (args.output, len(lock["drivers"]), len(lock["unresolved"])))
    else:
        _emit(lock_to_text(lock), args.output)
    return 0


def cmd_generate(args) -> int:
    """One-shot XSA -> manifest + lock + CMake + header. Called from CMake."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = xsamod.extract(args.xsa)
    paths = _db_paths(args)
    database = dbmod.load_many(paths)
    lock = resolve(manifest, database, paths[0], include_vendor=args.include_vendor,
                   strict=args.strict, subs=_subs(args.define, args.project_root))

    manifest_path = out_dir / "ip-manifest.json"
    lock_path = out_dir / "ip-drivers.lock.json"
    header_path = out_dir / args.header_name
    cmake_path = out_dir / "ip_drivers.cmake"

    write_json_atomic(manifest_path, manifest)
    write_json_atomic(lock_path, lock)
    header_path.write_text(generate_header(manifest, lock), encoding="utf-8", newline="\n")
    cmake_path.write_text(generate_cmake(lock, header_path), encoding="utf-8", newline="\n")

    print("ipman: %d IP instances, %d driver(s) resolved, %d unresolved"
          % (len(manifest["ips"]), len(lock["drivers"]), len(lock["unresolved"])))
    for u in lock["unresolved"]:
        print("ipman: WARNING %s %s (%s) - %s"
              % (u["ip"], u["ip_version"], ", ".join(u["instances"]), u["reason"]))
    print(cmake_path.as_posix())
    return 0


def cmd_db_init(args) -> int:
    path = Path(args.db)
    if path.exists() and not args.force:
        raise IpmanError("%s already exists (pass --force to overwrite)" % path)
    dbmod.save(path, dbmod.empty_db())
    print("created %s" % path)
    return 0


def cmd_db_list(args) -> int:
    database = dbmod.load(args.db)
    if args.format == "json":
        print(json.dumps(database, indent=2))
    else:
        sys.stdout.write(dbmod.to_text(database))
    return 0


def cmd_db_validate(args) -> int:
    database = dbmod.load(args.db)
    warnings = dbmod.validate(database, args.db)
    for warning in warnings:
        print("warning: %s" % warning)
    print("%s: schema OK, v%s, %d IP, %d version rule(s)%s"
          % (args.db, database["db_version"], len(database["drivers"]),
             sum(len(e.get("versions", [])) for e in database["drivers"].values()),
             ", %d warning(s)" % len(warnings) if warnings else ""))
    return 1 if (warnings and args.strict) else 0


def cmd_db_add(args) -> int:
    database = dbmod.load(args.db)
    source = {"type": args.type, "uri": args.uri, "ref": args.ref,
              "subdir": args.subdir, "sha256": args.sha256, "target": args.target,
              "notes": args.notes}
    action = dbmod.add_driver(database, args.vlnv, args.match, source,
                              summary=args.summary, owner=args.owner,
                              replace=args.replace)
    dbmod.validate(database)
    new_version = dbmod.bump(database, args.bump)
    dbmod.log_change(database, action, args.author or getpass.getuser())
    dbmod.save(args.db, database)
    print("%s -> %s is now v%s" % (action, args.db, new_version))
    return 0


def cmd_db_remove(args) -> int:
    database = dbmod.load(args.db)
    action = dbmod.remove_driver(database, args.vlnv, args.match)
    new_version = dbmod.bump(database, args.bump)
    dbmod.log_change(database, action, args.author or getpass.getuser())
    dbmod.save(args.db, database)
    print("%s -> %s is now v%s" % (action, args.db, new_version))
    return 0


def cmd_db_bump(args) -> int:
    database = dbmod.load(args.db)
    new_version = dbmod.bump(database, args.level)
    dbmod.log_change(database, args.message or "version bump",
                     args.author or getpass.getuser())
    dbmod.save(args.db, database)
    print("%s is now v%s" % (args.db, new_version))
    return 0


def _art_headers(args) -> dict:
    return art.credential_headers(token=args.token, api_key=args.api_key,
                                  user=args.user, password=args.password)


def cmd_db_publish(args) -> int:
    database = dbmod.load(args.db)
    warnings = dbmod.validate(database, args.db)
    if warnings and not args.allow_warnings:
        for warning in warnings:
            print("warning: %s" % warning)
        raise IpmanError("refusing to publish with warnings (pass --allow-warnings)")
    result = art.publish(args.db, args.url, args.repo, args.prefix,
                         _art_headers(args), force=args.force,
                         update_latest=not args.no_latest)
    print("published v%s (sha256 %s)" % (result["version"], result["sha256"][:16]))
    for url in result["urls"]:
        print("  %s" % url)
    return 0


def cmd_db_fetch(args) -> int:
    result = art.fetch(args.url, args.repo, args.prefix, args.db_version,
                       args.output, _art_headers(args))
    print("fetched driver database v%s -> %s" % (result["db_version"], result["path"]))
    return 0


def cmd_db_versions(args) -> int:
    versions = art.list_versions(args.url, args.repo, args.prefix, _art_headers(args))
    if not versions:
        print("no published versions under %s/%s" % (args.repo, args.prefix))
    for version in versions:
        print(version)
    return 0


# -------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipman",
        description="Vivado XSA -> custom IP manifest -> driver sources -> CMake.")
    parser.add_argument("--version", action="version", version="ipman " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    default_db = default_db_path()

    def add_define(p):
        p.add_argument("-D", "--define", action="append", metavar="VAR=VALUE",
                       help="substitute ${VAR} in database URIs (repeatable); "
                            "the environment is used as a fallback")

    p = sub.add_parser("extract", help="parse an .xsa into an IP manifest")
    p.add_argument("xsa")
    p.add_argument("-o", "--output", help="output file ('-' for stdout)")
    p.add_argument("-f", "--format", choices=("json", "text"), default="json")
    p.add_argument("--custom-only", action="store_true",
                   help="text format: hide Xilinx vendor IP")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("resolve", help="match a manifest against the driver database")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--xsa")
    src.add_argument("--manifest")
    p.add_argument("--db", action="append", default=None,
                   help="driver database; repeat to layer a project overlay "
                        "over the shared database (env IPMAN_DB)")
    p.add_argument("--project-root", help="value for ${PROJECT_ROOT} in URIs")
    p.add_argument("-o", "--output")
    p.add_argument("-f", "--format", choices=("json", "text"), default="text")
    p.add_argument("--strict", action="store_true",
                   help="fail if any custom IP has no driver")
    p.add_argument("--include-vendor", action="store_true",
                   help="also resolve drivers for Xilinx vendor IP")
    add_define(p)
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("generate", help="emit manifest, lock, CMake glue and header")
    p.add_argument("--xsa", required=True)
    p.add_argument("--db", action="append", default=None,
                   help="driver database; repeat to layer overlays (env IPMAN_DB)")
    p.add_argument("--project-root", help="value for ${PROJECT_ROOT} in URIs")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--header-name", default="ipman_ips.h")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--include-vendor", action="store_true")
    add_define(p)
    p.set_defaults(func=cmd_generate)

    dbp = sub.add_parser("db", help="inspect and maintain the driver database")
    dbsub = dbp.add_subparsers(dest="db_command", required=True)

    def add_db_arg(p):
        p.add_argument("--db", default=default_db, help="database file (env IPMAN_DB)")

    def add_edit_args(p):
        p.add_argument("--bump", choices=("major", "minor", "patch"), default="minor",
                       help="how to bump db_version (default: minor)")
        p.add_argument("--author", help="changelog author (default: current user)")

    def add_art_args(p):
        p.add_argument("--url", required=True,
                       help="Artifactory base URL, e.g. https://acme.jfrog.io/artifactory")
        p.add_argument("--repo", required=True, help="generic repository name")
        p.add_argument("--prefix", default="ip-drivers", help="path prefix in the repo")
        p.add_argument("--token", help="access token, or env:VARNAME")
        p.add_argument("--api-key", help="legacy API key, or env:VARNAME")
        p.add_argument("--user", help="username, or env:VARNAME")
        p.add_argument("--password", help="password, or env:VARNAME")

    q = dbsub.add_parser("init", help="create an empty database")
    add_db_arg(q)
    q.add_argument("--force", action="store_true")
    q.set_defaults(func=cmd_db_init)

    q = dbsub.add_parser("list", help="show the database")
    add_db_arg(q)
    q.add_argument("-f", "--format", choices=("text", "json"), default="text")
    q.set_defaults(func=cmd_db_list)

    q = dbsub.add_parser("validate", help="check the database for errors")
    add_db_arg(q)
    q.add_argument("--strict", action="store_true", help="exit non-zero on warnings")
    q.set_defaults(func=cmd_db_validate)

    q = dbsub.add_parser("add", help="add or update one IP -> driver rule")
    add_db_arg(q)
    q.add_argument("--vlnv", required=True, metavar="VENDOR:LIBRARY:NAME",
                   help="IP key without the version, e.g. acme.com:user:pwm_ctrl")
    q.add_argument("--match", required=True,
                   help="hardware version this rule covers: '1.2', '1.*' or '*'")
    q.add_argument("--type", choices=dbmod.SOURCE_TYPES, default="git")
    q.add_argument("--uri", required=True,
                   help="git URL, directory path, or archive URL; ${VARS} allowed")
    q.add_argument("--ref", help="git tag, branch or sha")
    q.add_argument("--subdir", help="driver subdirectory inside the repo/archive")
    q.add_argument("--sha256", help="archive checksum")
    q.add_argument("--target", help="CMake target the driver defines "
                                    "(default: ipdrv_<name>)")
    q.add_argument("--summary")
    q.add_argument("--owner")
    q.add_argument("--notes")
    q.add_argument("--replace", action="store_true",
                   help="overwrite an existing rule with the same --match")
    add_edit_args(q)
    q.set_defaults(func=cmd_db_add)

    q = dbsub.add_parser("remove", help="remove a rule or a whole IP entry")
    add_db_arg(q)
    q.add_argument("--vlnv", required=True)
    q.add_argument("--match", help="remove only this rule (default: the whole entry)")
    add_edit_args(q)
    q.set_defaults(func=cmd_db_remove)

    q = dbsub.add_parser("bump", help="bump db_version without other edits")
    add_db_arg(q)
    q.add_argument("level", choices=("major", "minor", "patch"))
    q.add_argument("-m", "--message")
    q.add_argument("--author")
    q.set_defaults(func=cmd_db_bump)

    q = dbsub.add_parser("publish", help="upload the database to Artifactory")
    add_db_arg(q)
    add_art_args(q)
    q.add_argument("--force", action="store_true",
                   help="overwrite an already published version")
    q.add_argument("--no-latest", action="store_true",
                   help="do not update the 'latest' pointer")
    q.add_argument("--allow-warnings", action="store_true")
    q.set_defaults(func=cmd_db_publish)

    q = dbsub.add_parser("fetch", help="download the database from Artifactory")
    add_art_args(q)
    q.add_argument("--db-version", default="latest",
                   help="published version to fetch (default: latest)")
    q.add_argument("-o", "--output", default=default_db)
    q.set_defaults(func=cmd_db_fetch)

    q = dbsub.add_parser("versions", help="list published versions in Artifactory")
    add_art_args(q)
    q.set_defaults(func=cmd_db_versions)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "db", None) is None and args.command in ("resolve", "generate"):
        args.db = [default_db_path()]
    try:
        return args.func(args)
    except IpmanError as exc:
        print("ipman: error: %s" % exc, file=sys.stderr)
        return 2
    except KeyError as exc:
        print("ipman: error: %s" % exc, file=sys.stderr)
        return 2
