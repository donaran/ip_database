# ipman — XSA to driver builds

Takes a Vivado `.xsa`, produces a manifest of every IP block and its version,
looks each custom IP up in a shared driver database, and hands CMake the exact
driver sources to build. Drivers live wherever you want: their own git repo, a
tarball in Artifactory, or a directory inside the project.

```
design_1.xsa ──▶ ip-manifest.json ──▶ ip-drivers.lock.json ──▶ ip_drivers.cmake
   (Vivado)        (every IP + VLNV)     (IP → driver source)      (FetchContent /
                            ▲                                      add_subdirectory)
                            │
                   ip-drivers.json  ◀── versioned in git, published to Artifactory
                   (+ project overlay)
```

`hello_fpga`, the C++ program in `src/`, is a working end-to-end example. It
links one CMake target and prints what it found in the bitstream.

---

## Quick start

```bash
# 1. Build the demo hardware and the stand-in "remote" driver sources.
python sample/bootstrap_demo.py --clean

# 2. Configure and build. The XSA is parsed here.
cmake -S . -B build
cmake --build build --config Release

# 3. Run.
./build/Release/hello_fpga        # Windows: build\Release\hello_fpga.exe
```

Configure output:

```
-- ipman: parsing .../sample/design_1.xsa
-- ipman: 9 IP instances, 3 driver(s) resolved, 1 unresolved
CMake Warning: ipman: no driver for acme.com:hls:crypto_accel 3.1 ...
--   adc_stream driver 2.1.0 -> ipdrv_adc_stream (IP 2.0, instances: adc_stream_0)
--   axi_gpio_lite driver 1.0.0 -> ipdrv_axi_gpio_lite (IP 1.0, instances: axi_gpio_lite_0)
--   pwm_ctrl driver 1.4.0 -> ipdrv_pwm_ctrl (IP 1.2, instances: pwm_ctrl_0;pwm_ctrl_1)
```

The demo deliberately covers all four cases: a driver fetched from git, one
unpacked from an archive, one built from a directory in the project, and one IP
with no driver at all.

Tests: `python -m unittest discover -s tests` (79 tests, no network, no Vivado).

---

## Where things live

| Path | What it is |
| --- | --- |
| `tools/ipman/` | the tool (pure standard library, Python 3.9+) |
| `cmake/IpMan.cmake` | `ipman_configure()` and `ipman_fetch_db()` |
| `db/README.md` | **runbook: adding a new driver or repository** |
| `db/ip-drivers.json` | the shared driver database |
| `db/project-overrides.json` | project overlay: drivers still developed in-tree |
| `drivers/pwm_ctrl/` | an in-project driver package |
| `src/main.cpp` | the hello-world application |
| `sample/` | synthetic XSA and stand-in git repo / archive |
| `tests/` | unit tests: a fake Artifactory server and a throwaway git repo |

---

## The driver database

One JSON file, keyed by `vendor:library:name` — the VLNV **without** the
version. Each entry maps hardware versions to driver revisions:

```json
{
  "schema": 1,
  "kind": "ip-driver-db",
  "db_version": "1.1.0",
  "drivers": {
    "acme.com:user:adc_stream": {
      "summary": "Streaming ADC capture front end",
      "owner": "dsp-team@acme.com",
      "versions": [
        {"match": "1.*", "type": "archive",
         "uri": "${ARTIFACTORY}/fpga-generic/drivers/adc_stream-1.9.0.tar.gz",
         "sha256": "..."},
        {"match": "2.*", "type": "archive",
         "uri": "${ARTIFACTORY}/fpga-generic/drivers/adc_stream-2.1.0.tar.gz",
         "sha256": "..."}
      ]
    }
  },
  "changelog": [...]
}
```

**Version matching.** `match` is an exact version (`1.2`), a glob (`1.*`), or
`*`. The most specific match wins, so the order of rules in the file never
changes the outcome. Vivado's odd version strings (`1.03.a`) work as literals.

**Source types.**

| `type` | fields | fetched by |
| --- | --- | --- |
| `git` | `uri`, `ref`, `ref_type`, `subdir` | `FetchContent` (shallow clone for a tag or branch) |
| `archive` | `uri`, `sha256`, `subdir` | `FetchContent` with `URL_HASH` |
| `path` | `uri` (absolute, `${VAR}`-relative, or relative to the database file) | `add_subdirectory` |

**Variables.** `${NAME}` in a `uri`, `ref` or `subdir` is substituted from
`-D NAME=value`, then from the environment. `${PROJECT_ROOT}` is always set by `ipman_configure()` to
`CMAKE_SOURCE_DIR`. This is what keeps the shared database site-neutral:

```json
{"type": "git", "uri": "${CORP_GIT}/fpga/drivers/pwm_ctrl.git", "ref": "v1.4.0"}
```

Per-IP variables are also available, so a rule can derive its ref from the
hardware version it matched: `IP_VENDOR`, `IP_LIBRARY`, `IP_NAME`,
`IP_VERSION`, `IP_VERSION_MAJOR`, `IP_VERSION_MINOR`.

**Pinning a tag or commit per IP version.** Each version rule carries its own
`ref`, so the hardware version decides which point in the driver's history gets
built:

```json
"versions": [
  {"match": "1.2", "type": "git", "uri": "...", "ref": "v1.4.0"},
  {"match": "1.3", "type": "git", "uri": "...", "ref": "v1.5.2"},
  {"match": "2.*", "type": "git", "uri": "...",
   "ref": "9f2c1ab4d7e0...", "ref_type": "commit"}
]
```

`ref_type` is `tag`, `branch` or `commit`, and is inferred when omitted — a hex
object name is a commit, anything else a tag. It decides whether the clone can
be shallow: a commit cannot be fetched by name with `--depth 1`, so it is
cloned in full. Declare it explicitly when a tag name happens to be all hex, or
to make a branch dependency obvious (`validate` warns about branches, since the
driver then moves underneath you).

When driver tags track IP versions, one rule can cover the family:

```json
{"match": "1.*", "type": "git", "uri": "...", "ref": "v${IP_VERSION}.0"}
```

IP 1.0 pulls tag `v1.0.0`, IP 1.3 pulls `v1.3.0`. The ref is classified after
expansion, so a template that resolves to a sha is still treated as a commit.

Check that the refs are real before anyone builds:

```bash
python -m ipman db verify -D CORP_GIT=ssh://git@git.acme.com
```

```
acme.com:user:axi_gpio_lite  1.*   v${IP_VERSION}.0  skipped  templated; resolved per IP version
acme.com:user:axi_gpio_lite  2.*   1b2a654d6ffa...   ok       commit is the tip of HEAD
```

`db add --verify-ref` runs the same check for a single rule before writing it,
and refuses to add a rule pinning a tag that does not exist.

**Layering.** `--db` is repeatable and later files win. The shared database
holds org-wide drivers; a project overlay adds or overrides entries without
anyone editing the shared file — that is how an in-project driver directory
coexists with the global database:

```jsonc
// db/project-overrides.json
{"acme.com:user:pwm_ctrl": {"versions": [
  {"match": "1.*", "type": "path", "uri": "${PROJECT_ROOT}/drivers/pwm_ctrl"}]}}
```

---

## Maintaining the database

Step-by-step, from a new IP in a block design to a published database entry:
**[db/README.md](db/README.md)**.

Never hand-edit it; the CLI keeps the file sorted, validated, versioned, and
changelogged, so git diffs stay readable.

```bash
export PYTHONPATH=tools
export IPMAN_DB=db/ip-drivers.json

# Add an IP, or a new hardware-version rule for one that exists.
python -m ipman db add \
  --vlnv acme.com:user:pwm_ctrl --match "2.*" \
  --type git --uri '${CORP_GIT}/fpga/drivers/pwm_ctrl.git' --ref v2.0.0 \
  --summary "PWM controller" --owner fpga-team@acme.com

# Point an existing rule at a newer driver release.
python -m ipman db add --vlnv acme.com:user:pwm_ctrl --match "1.*" \
  --type git --uri '${CORP_GIT}/fpga/drivers/pwm_ctrl.git' --ref v1.4.1 \
  --replace --bump patch

python -m ipman db remove --vlnv acme.com:user:old_ip
python -m ipman db list
python -m ipman db validate --strict
python -m ipman db bump major -m "schema cleanup"
```

Every edit bumps `db_version` (`--bump major|minor|patch`, default `minor`) and
prepends a changelog entry. Commit the result; git is the source of truth.

Validation errors are hard failures (bad key, unknown source type, duplicate
`match`). Warnings are advisory: a git source with no `ref` is not
reproducible, an archive with no `sha256` is not verifiable. `db publish`
refuses to upload with warnings unless you pass `--allow-warnings`.

---

## Artifactory (free tier / Community Edition)

Only generic repositories and the plain REST API are used — no JFrog CLI, no
commercial feature, no Python dependencies.

**Layout.**

```
<repo>/ip-drivers/1.1.0/ip-drivers.json    immutable, never overwritten
<repo>/ip-drivers/latest/ip-drivers.json   moving pointer, rewritten each publish
```

**Setup.** Create a generic local repository (`fpga-generic`), then an access
token with deploy rights on it. Export it as `ARTIFACTORY_TOKEN`.

```bash
export PYTHONPATH=tools
ART=https://acme.jfrog.io/artifactory

python -m ipman db publish --db db/ip-drivers.json \
  --url $ART --repo fpga-generic --token env:ARTIFACTORY_TOKEN

python -m ipman db versions --url $ART --repo fpga-generic --token env:ARTIFACTORY_TOKEN
python -m ipman db fetch --url $ART --repo fpga-generic \
  --db-version 1.1.0 -o db/ip-drivers.json --token env:ARTIFACTORY_TOKEN
```

`publish` uploads with an `X-Checksum-Sha256` header and **refuses to overwrite
a version that already exists** unless `--force`. That is what makes published
versions immutable on a tier with no retention or release-bundle feature: to
change anything you bump the version and publish again. `fetch` verifies the
checksum Artifactory reports against the bytes it received.

Auth accepts `--token`, `--api-key`, or `--user`/`--password`; any of them can
be given as `env:VARNAME` so secrets stay out of shell history and CI logs.

**Version control model.** git holds the editable database and its history;
Artifactory holds immutable published snapshots that projects pin to. A release
job ties the two together:

```yaml
# .gitlab-ci.yml / GitHub Actions equivalent
publish-driver-db:
  rules: [{ if: $CI_COMMIT_TAG }]
  script:
    - export PYTHONPATH=tools
    - python -m ipman db validate --db db/ip-drivers.json --strict
    - python -m ipman db publish --db db/ip-drivers.json
        --url $ARTIFACTORY_URL --repo fpga-generic --token env:ARTIFACTORY_TOKEN
```

**Consuming a pinned version** — the project never needs the database in its
own tree:

```cmake
ipman_fetch_db(
  URL        https://acme.jfrog.io/artifactory
  REPO       fpga-generic
  DB_VERSION 1.1.0                      # or "latest"
  OUTPUT     ${CMAKE_BINARY_DIR}/ip-drivers.json
  TOKEN      env:ARTIFACTORY_TOKEN)
ipman_configure(XSA ${HELLO_XSA} DB ${IPMAN_DB})
```

A pinned version is cached across configures; `latest` is re-fetched every
time. In this repo that path is wired to `-DHELLO_ARTIFACTORY_URL=...
-DHELLO_IP_DB_VERSION=1.1.0`.

The same repository is the natural home for driver tarballs referenced by
`archive` entries.

---

## CMake API

```cmake
list(APPEND CMAKE_MODULE_PATH "${CMAKE_SOURCE_DIR}/cmake")
include(IpMan)

ipman_configure(
  XSA     "${CMAKE_SOURCE_DIR}/hw/design_1.xsa"
  DB      "${CMAKE_SOURCE_DIR}/db/ip-drivers.json"
          "${CMAKE_SOURCE_DIR}/db/project-overrides.json"   # optional overlay
  STRICT                                                     # optional
  DEFINES "CORP_GIT=https://git.acme.com")

target_link_libraries(app PRIVATE ipman::drivers)
```

`ipman::drivers` is an interface library: it links every resolved driver and
puts the generated header on the include path. Also set in the caller's scope:
`IPMAN_MANIFEST`, `IPMAN_LOCK`, `IPMAN_GENERATED_DIR`, `IPMAN_DRIVER_TARGETS`,
`IPMAN_DB_VERSION`.

`STRICT` turns an IP with no driver into a configure error instead of a
warning. Use it in CI once the database is complete.

Changing the XSA or any database file re-runs configure automatically
(`CMAKE_CONFIGURE_DEPENDS`).

### Generated header

`ipman_ips.h`, in the style of `xparameters.h`:

```c
#define IPMAN_XSA_FILE       "design_1.xsa"
#define IPMAN_DB_VERSION     "1.1.0+0.2.0"
#define IPMAN_IP_COUNT       5

#define PWM_CTRL_0_BASEADDR          0x43C00000UL
#define PWM_CTRL_0_HIGHADDR          0x43C0FFFFUL

static const ipman_ip_info_t IPMAN_IPS[...] = {
    { "pwm_ctrl_0", "acme.com:user:pwm_ctrl:1.2", "ipdrv_pwm_ctrl",
      0x43C00000UL, 0x43C0FFFFUL },
    ...
};
```

IP with no driver still appears, with an empty `driver` field — the application
can report it instead of silently ignoring it.

---

## Driver package contract

A driver package is a directory with a `CMakeLists.txt` that defines one target.
The default target name is `ipdrv_<ipname>`; override it per rule with
`--target`. Before the directory is added, ipman sets:

| Variable | Example |
| --- | --- |
| `IPMAN_DRIVER_TARGET` | `ipdrv_pwm_ctrl` |
| `IPMAN_DRIVER_NAME` | `pwm_ctrl` |
| `IPMAN_DRIVER_IP_VERSION` | `1.2` |
| `IPMAN_DRIVER_INSTANCES` | `pwm_ctrl_0;pwm_ctrl_1` |

```cmake
cmake_minimum_required(VERSION 3.20)
project(ipdrv_pwm_ctrl VERSION 1.4.0 LANGUAGES CXX)

if(DEFINED IPMAN_DRIVER_TARGET)
  set(_target "${IPMAN_DRIVER_TARGET}")
else()
  set(_target ipdrv_pwm_ctrl)          # so the package configures standalone
endif()

add_library(${_target} STATIC src/pwm_ctrl.cpp)
target_include_directories(${_target} PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
```

If the package fails to define that target, configure stops with a message
naming the IP and the expected target — not a confusing link error later.

Two instances of one IP at one version share a single driver build. The same IP
present at two versions produces two targets (`ipdrv_pwm_ctrl_v1_2` and
`ipdrv_pwm_ctrl_v2_0`), so both register maps can coexist in one binary.

The demo drivers compile with `IPDRV_SIMULATION=1`, which backs the register
block with memory so the example runs on a host. Cross-compiling for the target
turns that option off and the same code does real MMIO.

---

## CLI reference

```
ipman extract  <design.xsa> [-o out] [-f json|text] [--custom-only]
ipman resolve  (--xsa F | --manifest F) [--db F]... [-o out] [-f json|text]
               [--strict] [--include-vendor] [-D VAR=VALUE]... [--project-root D]
ipman generate --xsa F [--db F]... --out-dir D [--header-name H]
               [--strict] [--include-vendor] [-D VAR=VALUE]... [--project-root D]

ipman db init | list | validate | verify | add | remove | bump
ipman db publish | fetch | versions        (Artifactory)
```

`IPMAN_DB` sets the default database path. `generate` is what
`ipman_configure()` calls; the rest are for humans and CI.

Useful on its own, with no CMake involved:

```bash
PYTHONPATH=tools python -m ipman extract sample/design_1.xsa -f text -o -
```

```
design_1.xsa  (9 IP instances)

INSTANCE              VLNV                                  BASE        KIND
--------------------  ------------------------------------  ----------  ----
adc_stream_0          acme.com:user:adc_stream:2.0          0x43C20000  custom
axi_gpio_0            xilinx.com:ip:axi_gpio:2.0            0x41200000  vendor
crypto_accel_0        acme.com:hls:crypto_accel:3.1         0x43C40000  custom
pwm_ctrl_0            acme.com:user:pwm_ctrl:1.2            0x43C00000  custom
...
```

---

## Notes on real XSAs

An `.xsa` is a zip. Everything ipman needs comes from the `.hwh` hardware
handoff files inside it: `MODULE` elements carry `VLNV`, and the processor's
`MEMRANGES` carry each slave's base address (module `C_S_AXI_BASEADDR`
parameters are the fallback). Hierarchical block designs are flattened by
Vivado, so nested IP is found by `FULLNAME`.

"Custom" means the VLNV vendor is not `xilinx.com`, or the library is not one of
the stock Xilinx libraries — so `acme.com:user:*` and HLS-exported
`acme.com:hls:*` are custom, and `xilinx.com:ip:axi_gpio:2.0` is not. Vendor IP
is listed in the manifest but not resolved unless you pass `--include-vendor`;
if you do, add database entries for it the same way. Adjust `VENDOR_VENDORS` and
`VENDOR_LIBRARIES` in `tools/ipman/xsa.py` if your site uses different vendor
strings.

An XSA exported from a non-block-design flow has no `.hwh` and nothing to
harvest; ipman says so rather than silently producing an empty manifest.
