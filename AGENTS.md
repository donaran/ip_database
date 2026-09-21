# AGENTS.md

Orientation for coding agents working in this repo. Read this before touching
anything; it covers the invariants that are not obvious from the code.

## What this is

`ipman` turns a Vivado hardware export into a driver build. It parses an `.xsa`
into a manifest of every IP block and version, resolves each custom IP against a
driver database, and generates the CMake that fetches and compiles the matching
driver sources. `hello_fpga` (`src/main.cpp`) is the end-to-end example.

```
design_1.xsa ──▶ ip-manifest.json ──▶ ip-drivers.lock.json ──▶ ip_drivers.cmake
  xsa.py            resolve.py             cmakegen.py           (+ ipman_ips.h)
                        ▲
                     db.py  ◀── db/*.json, versioned in git, published to Artifactory
```

Two audiences, two docs: `README.md` explains the system; `db/README.md` is the
runbook for adding a driver. Keep both in step with behaviour changes.

## Commands

```bash
# Generate the demo hardware + stand-in git repo and archive. REQUIRED FIRST:
# sample/design_1.xsa and sample/_demo/ are gitignored build inputs.
python sample/bootstrap_demo.py --clean

python -m unittest discover -s tests          # 124 tests, offline, ~2s

cmake -S . -B build                           # parses the XSA at configure time
cmake --build build --config Release
ctest --test-dir build -C Release
./build/Release/hello_fpga.exe

# The CLI, outside CMake:
PYTHONPATH=tools python -m ipman extract sample/design_1.xsa -f text -o -
PYTHONPATH=tools python -m ipman db list
```

Windows + Visual Studio is the verified configuration; the generator is
multi-config, so `--config Release` and `build/Release/` are not optional.

## Layout

| Path | Notes |
| --- | --- |
| `tools/ipman/` | the tool; **standard library only**, Python 3.9+ |
| `cmake/IpMan.cmake` | `ipman_configure()`, `ipman_fetch_db()`, `ipman_verify_driver()` |
| `db/ip-drivers.json` | shared driver database — **never hand-edit** |
| `db/project-overrides.json` | project overlay, same rule |
| `drivers/pwm_ctrl/` | in-project driver package (`path` source example) |
| `sample/driver_src/` | sources for the git and archive stand-ins |
| `sample/_demo/`, `sample/design_1.xsa` | generated, gitignored |
| `build/ipman/` | generated manifest, lock, `.cmake`, headers, driver records — never edit |
| `tests/` | offline unit tests |

## Module responsibilities

Dependencies point one way; do not introduce a cycle.

```
util.py      IpmanError, ${VAR} expansion, atomic JSON writes.  Depends on nothing.
gitref.py    Ref classification (tag/branch/commit) and `git ls-remote` checks.
xsa.py       .xsa/.hwh -> manifest dict.  The only module that knows XML.
db.py        Load/merge/validate/mutate the database; version matching.
resolve.py   manifest x db -> lock.  Builds the per-IP ${IP_*} substitutions.
cmakegen.py  lock -> ip_drivers.cmake + ipman_ips.h.  The only module emitting CMake.
driver_manifest.py  Reads a driver package's ipman-driver.json and checks it
             against the lock.  Runs after the package is on disk.
mapgen.py    Driver records -> ipman_maps.hpp, the runtime register-map union.
artifactory.py  Publish/fetch/list over plain REST.  urllib only.
cli.py       argparse surface.  Thin: logic belongs in the modules above.
```

## Data contracts

Four JSON shapes, each tagged with `kind` and `schema`. `SCHEMA` lives in
`tools/ipman/__init__.py`; bump it if any shape changes incompatibly —
`db.validate()` refuses a mismatched database rather than misreading it.

**Database** (`kind: ip-driver-db`) — keyed by `vendor:library:name`, the VLNV
**without** the version. Each entry's `versions[]` maps hardware versions to
driver sources. Invariants worth preserving:

- Most specific `match` wins (exact > glob > `*`), so file order never changes
  resolution. `db._score()` owns this.
- `db_version` is semver and every mutation bumps it and prepends a changelog
  entry. That is why the database must go through the CLI, not an editor.
- Source types are `git` / `path` / `archive`. Adding a fourth means touching
  `db.SOURCE_TYPES`, `db.validate()`, `db.resolve_source()` and
  `cmakegen.generate_cmake()` together.

**Manifest** (`kind: ip-manifest`) and **lock** (`kind: ip-driver-lock`) are
generated; nothing reads them back except `resolve --manifest`.

**Driver manifest** (`kind: ipman-driver`) lives in the driver package, not
here. `implements[].match` reuses the database's match semantics on purpose --
`driver_manifest.covers()` calls `db._score()` rather than reimplementing it. A
`map` entry opts the IP into runtime dispatch and then `id_register` becomes
mandatory, because without it there is no way to read the revision before the
revision is known.

### Two-pass configure

`ipman_configure()` runs the tool twice, and the order is forced:

1. `ipman generate` -- needs only the XSA and the database.
2. `include(ip_drivers.cmake)` -- fetches and adds each driver, and calls back
   into `ipman driver verify` per driver, writing a record to
   `<out>/drivers/<target>.json`.
3. `ipman driver maps` -- reads those records and emits `ipman_maps.hpp`.

Step 3 cannot move earlier: a git or archive driver does not exist on disk
until FetchContent has run. `<out>/drivers` is wiped before step 2 so a record
for an IP that has left the design cannot survive.

### Internal keys

`db.load_many()` annotates each rule with `_db` (the file it came from, so a
relative `path` URI resolves against its own database) and adds `_sources` to
the merged dict. These are **in-memory only**. Never pass a `load_many()` result
to `db.save()` — it would persist them. Mutating commands use single-file
`db.load()` for exactly this reason.

## Conventions

- **No third-party dependencies**, in the tool or the tests. `urllib`,
  `subprocess`, `zipfile`, `http.server` cover everything here. Do not add
  `requests`, `pytest`, `jsonschema`.
- `from __future__ import annotations` at the top of every module.
- `%`-formatting throughout, not f-strings. Match it.
- User-facing failures raise `IpmanError`; `cli.main()` prints it without a
  traceback and exits 2. Anything else is a bug and should surface as a
  traceback.
- `db.validate()` distinguishes **errors** (raise — corrupt or unusable) from
  **warnings** (returned list — advisory, e.g. a branch ref or a missing
  `sha256`). `db publish` refuses to upload with warnings unless forced.
- Generated CMake quotes every path through `cmakegen._cm_str()`. Never
  interpolate a path into CMake without it — paths with spaces are tested.
- Keep `README.md`, `db/README.md` and `--help` text truthful. The docs quote
  real error strings; if you change a message, grep for it.

## Testing

- Tests are **offline and toolchain-free**: no network, no Vivado, no
  Artifactory. `tests/test_ipman.py` stands up a fake Artifactory on
  `http.server`; `tests/test_gitrefs.py` builds a throwaway git repo with both
  an annotated and a lightweight tag.
- `test_gitrefs.py` imports `build_db` and `make_xsa` from `test_ipman.py`;
  that works because `unittest discover` puts `tests/` on `sys.path`. Run the
  suite with discovery, not by path.
- Tests build their own databases in temp directories. Do **not** write a test
  that asserts on the contents of `db/*.json` — those are demo data and their
  `db_version` moves whenever someone runs a `db` command.
- New behaviour needs a test. The git-ref work added 32 and driver
  manifests 45; the shallow-clone regression test exists because that bug
  shipped once already.

## Gotchas

- **Run `sample/bootstrap_demo.py` before `cmake`.** A fresh clone has no
  `sample/design_1.xsa`, and configure fails with "XSA not found".
- `sample/_demo/repos/*.git` is regenerated by `--clean`, which changes its
  commit shas. The demo database pins one (`acme.com:user:axi_gpio_lite`,
  `2.*`); after a `--clean` that pin is stale. It is not on the resolve path
  for the sample design, so the build still works, but `db verify` will say
  `unknown`.
- **Git Bash mangles POSIX-looking arguments.** `-D DEMO_GIT=/demo/repos`
  arrives as `C:/Program Files/Git/demo/repos`. Use `$PWD`-rooted or
  Windows-style paths when passing `-D` on this platform.
- The archive tarball is built with a fixed mtime so its sha256 is stable.
  Changing `sample/driver_src/adc_stream/` changes the hash and the database
  entry must be updated, or FetchContent fails with `HASH mismatch`.
- `ipman_configure()` calls `add_subdirectory` / `FetchContent_MakeAvailable`
  from inside a CMake function. That is deliberate and works — targets are
  global, and the directory inherits the function scope, which is how
  `IPMAN_DRIVER_*` reaches the driver package.
- Long shell heredocs get truncated by some tool harnesses. Write files with a
  file-writing tool rather than `cat > file <<'EOF'` for anything sizeable.

## Not verified

State these limits rather than implying coverage:

- The XSA parser has only been run against the **synthetic** `.hwh` in
  `sample/make_sample_xsa.py`, modelled on Vivado's format. No real Vivado
  export has been parsed here. If base addresses come back empty on a real
  XSA, the `MEMRANGE` attribute names differ — fix `xsa._collect_memranges()`.
- The Artifactory client is tested against a fake server implementing the
  endpoints it uses, not a live instance.
- `IPDRV_SIMULATION` is on for host builds, so the drivers touch memory, not
  MMIO. Nothing here has run on hardware.

## Common changes

| Task | Touch |
| --- | --- |
| New CLI flag | `cli.build_parser()` + the `cmd_*` function; logic goes in a module |
| New database field | `db.validate()`, `db.add_driver()`, `db.to_text()`, `cli` arg, both READMEs |
| New driver-manifest field | `driver_manifest.validate()`, `verify()` record, `mapgen` if it affects generation |
| Change the generated C++ union | `mapgen.generate()` + a `TestMapGeneration` assertion |
| New source type | `db.SOURCE_TYPES`, `db.validate()`, `db.resolve_source()`, `cmakegen` |
| Change generated CMake | `cmakegen.generate_cmake()` + a `TestGeneration` assertion |
| Change vendor-IP heuristic | `xsa.VENDOR_VENDORS` / `VENDOR_LIBRARIES` |
| Change the JSON shape | bump `SCHEMA` in `tools/ipman/__init__.py` |
