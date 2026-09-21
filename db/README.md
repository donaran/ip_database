# Adding a driver to the database

A runbook for the whole trip: a new custom IP shows up in a block design, and
you need `cmake --build` to compile a driver for it. Roughly 15 minutes for a
driver that already exists, most of it waiting on review.

Everything below assumes:

```bash
export PYTHONPATH=tools
export IPMAN_DB=db/ip-drivers.json
```

PowerShell:

```powershell
$env:PYTHONPATH = "tools"
$env:IPMAN_DB   = "db/ip-drivers.json"
```

> Quoting: `${CORP_GIT}` must reach ipman **unexpanded**. Use single quotes in
> bash and PowerShell (`'${CORP_GIT}/fpga/pwm.git'`). Double quotes will let
> your shell eat it and you'll store an empty prefix.

---

## Step 0 — Get the exact VLNV

Never type the key from memory. Read it out of the hardware:

```bash
python -m ipman extract hw/design_1.xsa -f text --custom-only -o -
```

```
INSTANCE              VLNV                                  BASE        KIND
--------------------  ------------------------------------  ----------  ----
pwm_ctrl_0            acme.com:user:pwm_ctrl:1.2            0x43C00000  custom
crypto_accel_0        acme.com:hls:crypto_accel:3.1         0x43C40000  custom
```

The database key is the VLNV **without the trailing version**:

```
acme.com:user:pwm_ctrl:1.2
└──────── key ────────┘└┬┘
                        └── this becomes --match, not part of the key
```

So `--vlnv acme.com:user:pwm_ctrl --match "1.*"`. Getting this wrong is the
single most common mistake — the key must match character for character,
including the `.com` and the library segment (`user`, `hls`, whatever your IP
packager set).

---

## Step 1 — Decide where the driver lives

| Situation | `--type` | Goes in |
| --- | --- | --- |
| Driver has its own git repo, tagged releases | `git` | shared database |
| Driver shipped as a release tarball (Artifactory generic repo) | `archive` | shared database |
| Driver still being written, lives in this project's tree | `path` | **project overlay** |

The split matters. `db/ip-drivers.json` is shared by every project in the org,
so it must only contain URIs that resolve anywhere. A `path` entry pointing at
`${PROJECT_ROOT}/drivers/...` only makes sense inside one project — it belongs
in `db/project-overrides.json`, and gets promoted to the shared database once
the driver moves to its own repo.

---

## Step 2 — Prepare the driver package

A driver package is any directory containing a `CMakeLists.txt` that defines
**one target**. Default expected name is `ipdrv_<ipname>` — for
`acme.com:user:pwm_ctrl` that's `ipdrv_pwm_ctrl`. Override per rule with
`--target` if your repo names it something else.

Minimum viable layout:

```
pwm_ctrl/
├── CMakeLists.txt
├── include/pwm_ctrl.hpp
└── src/pwm_ctrl.cpp
```

```cmake
cmake_minimum_required(VERSION 3.20)
project(ipdrv_pwm_ctrl VERSION 1.4.0 LANGUAGES CXX)

# ipman sets IPMAN_DRIVER_TARGET; the fallback keeps the package buildable
# standalone, which is what its own CI does.
if(DEFINED IPMAN_DRIVER_TARGET)
  set(_target "${IPMAN_DRIVER_TARGET}")
else()
  set(_target ipdrv_pwm_ctrl)
endif()

add_library(${_target} STATIC src/pwm_ctrl.cpp)
target_include_directories(${_target} PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(${_target} PUBLIC cxx_std_17)
```

Four variables are set for you before the directory is added:

| Variable | Example | Use it for |
| --- | --- | --- |
| `IPMAN_DRIVER_TARGET` | `ipdrv_pwm_ctrl` | the target name to define |
| `IPMAN_DRIVER_NAME` | `pwm_ctrl` | messages, file names |
| `IPMAN_DRIVER_IP_VERSION` | `1.2` | compile-def, so the binary can report what register map it was built for |
| `IPMAN_DRIVER_INSTANCES` | `pwm_ctrl_0;pwm_ctrl_1` | per-instance generation, if you do any |

`drivers/pwm_ctrl/` in this repo is a complete worked example, including the
`IPDRV_SIMULATION` switch that lets the driver build and run on a host.

**Tag a release.** A `git` rule should pin an immutable tag or commit, never a
branch — `validate` warns about both a missing `ref` and a branch `ref`,
because either means the driver changes underneath projects that already
build.

```bash
git tag -a v1.4.0 -m "pwm_ctrl driver 1.4.0" && git push origin v1.4.0
```

Decide now how driver tags relate to IP versions. Either is fine, and the
database expresses both:

| Convention | Rule |
| --- | --- |
| Driver versioned independently of the IP | one rule per IP version, each with its own `--ref` |
| Driver tag tracks the IP version (`v1.3.0` for IP 1.3) | one rule with `--ref 'v${IP_VERSION}.0'` |

---

## Step 3 — Add the entry

### From a git repository

```bash
python -m ipman db add \
  --vlnv   acme.com:user:pwm_ctrl \
  --match  "1.*" \
  --type   git \
  --uri    '${CORP_GIT}/fpga/drivers/pwm_ctrl.git' \
  --ref    v1.4.0 \
  --summary "PWM controller, 2 channels, per-mille duty" \
  --owner   fpga-team@acme.com
```

Driver not at the repo root? Add `--subdir drivers/pwm_ctrl`.

Add `--verify-ref` and the tag is checked on the remote before the rule is
written — a typo becomes an error here instead of an opaque clone failure in
somebody else's build:

```
verify ssh://git@git.acme.com/fpga/drivers/pwm_ctrl.git @ v1.4.0: ok - refs/tags/v1.4.0 -> 1b2a654d6ffa
  (pin the commit instead with --ref 1b2a654d6ffa... --ref-type commit)
```

#### Pinning a specific tag or commit per IP version

Each rule pins its own ref, so the hardware version decides what gets built:

```bash
# IP 1.2 needs driver v1.4.0; IP 1.3 needs v1.5.2.
python -m ipman db add --vlnv acme.com:user:pwm_ctrl --match "1.2"  \
  --type git --uri '${CORP_GIT}/fpga/drivers/pwm_ctrl.git' --ref v1.4.0

python -m ipman db add --vlnv acme.com:user:pwm_ctrl --match "1.3"  \
  --type git --uri '${CORP_GIT}/fpga/drivers/pwm_ctrl.git' --ref v1.5.2 --bump patch
```

To pin a commit — the 2.x register map works but has no tag yet:

```bash
python -m ipman db add --vlnv acme.com:user:pwm_ctrl --match "2.*"  \
  --type git --uri '${CORP_GIT}/fpga/drivers/pwm_ctrl.git'  \
  --ref 9f2c1ab4d7e0c3b8a1f5029e6d4c7b8a3f1e0d92 --ref-type commit
```

`--ref-type` is `tag`, `branch` or `commit` and is inferred when you leave it
off: a hex object name is a commit, anything else a tag. It is worth being
explicit when a tag name is all hex, or when you genuinely do want a branch.
Getting it wrong is not cosmetic — a commit cannot be fetched with `--depth 1`,
so ipman only shallow-clones tags and branches.

Prefer the **full 40-character sha**. An abbreviated one works today and can
become ambiguous as the repo grows; `validate` warns about it.

#### When the driver tag follows the IP version

If `pwm_ctrl` IP 1.3 is always served by driver tag `v1.3.0`, one rule covers
the whole family:

```bash
python -m ipman db add --vlnv acme.com:user:pwm_ctrl --match "1.*"  \
  --type git --uri '${CORP_GIT}/fpga/drivers/pwm_ctrl.git'  \
  --ref 'v${IP_VERSION}.0' --replace --bump minor
```

Available inside `--ref`, `--uri` and `--subdir`: `${IP_VERSION}`,
`${IP_VERSION_MAJOR}`, `${IP_VERSION_MINOR}`, `${IP_NAME}`, `${IP_VENDOR}`,
`${IP_LIBRARY}`.

The substitution happens per IP version at resolve time, so `ipman resolve`
shows the real tag:

```
  acme.com:user:pwm_ctrl 1.2 -> ipdrv_pwm_ctrl
      git ssh://git@git.acme.com/fpga/drivers/pwm_ctrl.git @ v1.2.0 (tag)
```

Convenient, but it silently depends on every future tag existing. `db verify`
cannot check a templated ref (it has no IP version to substitute), so prefer
explicit rules for drivers where the mapping is not mechanical.

`${CORP_GIT}` is substituted at configure time from `DEFINES` in
`ipman_configure()` or from the environment, so the same database works over
SSH internally and HTTPS in CI. Consuming projects pass:

```cmake
ipman_configure(XSA ... DB ... DEFINES "CORP_GIT=ssh://git@git.acme.com")
```

### From an archive

Compute the checksum first — an archive rule without one is unverifiable, and
`db publish` will refuse to upload it:

```bash
sha256sum pwm_ctrl-1.4.0.tar.gz
# or, portable:
python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" pwm_ctrl-1.4.0.tar.gz
```

```bash
python -m ipman db add \
  --vlnv  acme.com:user:pwm_ctrl \
  --match "1.*" \
  --type  archive \
  --uri   '${ARTIFACTORY}/fpga-generic/drivers/pwm_ctrl/1.4.0/pwm_ctrl-1.4.0.tar.gz' \
  --sha256 3f7a...  \
  --summary "PWM controller" --owner fpga-team@acme.com
```

The archive must unpack to a single top-level directory containing
`CMakeLists.txt` (CMake strips that one directory automatically). If it unpacks
to something deeper, add `--subdir`.

### From a directory in this project

Goes in the **overlay**, not the shared database:

```bash
python -m ipman db add --db db/project-overrides.json \
  --vlnv  acme.com:user:pwm_ctrl \
  --match "1.*" \
  --type  path \
  --uri   '${PROJECT_ROOT}/drivers/pwm_ctrl' \
  --summary "PWM controller" \
  --notes  "developed in-tree; promote once it stabilises"
```

`${PROJECT_ROOT}` is always set by `ipman_configure()` to `CMAKE_SOURCE_DIR`.
A bare relative path is also accepted and resolves against the database file's
own directory — but `${PROJECT_ROOT}` says what you mean.

---

## Step 4 — Verify before you commit

```bash
# 1. Schema, keys, source types. Warnings become errors at publish time.
python -m ipman db validate --strict

# 2. Do the git refs exist on their remotes?
python -m ipman db verify -D CORP_GIT=ssh://git@git.acme.com

# 3. Does the rule actually match the hardware version in your XSA?
python -m ipman resolve --xsa hw/design_1.xsa \
  --db db/ip-drivers.json --db db/project-overrides.json \
  -D CORP_GIT=ssh://git@git.acme.com --project-root .
```

```
  acme.com:user:pwm_ctrl 1.2 -> ipdrv_pwm_ctrl
      git ssh://git@git.acme.com/fpga/drivers/pwm_ctrl.git @ v1.4.0
      instances: pwm_ctrl_0, pwm_ctrl_1
```

If your IP shows up under `UNRESOLVED:`, the reason line says whether the key
is missing entirely or the version didn't match any rule. Fix that before
going further.

```bash
# 4. Full build, which is the only real proof the driver compiles and links.
cmake -S . -B build && cmake --build build --config Release
ctest --test-dir build -C Release
```

Add `STRICT` to `ipman_configure()` in CI once your database is complete — it
turns an IP with no driver into a configure error instead of a warning.

---

## Step 5 — Commit and publish

Two separate things happen, in this order.

**git is the source of truth.** Open a PR with the changed database file. The
diff is readable on purpose — entries are sorted, and the tool has already
prepended a changelog line naming you and the version:

```json
{ "db_version": "1.2.0", "date": "...", "author": "bkowalski",
  "change": "added acme.com:user:pwm_ctrl [1.*]" }
```

**Artifactory holds immutable published snapshots.** After merge, on a tag,
CI publishes:

```bash
python -m ipman db validate --db db/ip-drivers.json --strict
python -m ipman db publish --db db/ip-drivers.json \
  --url $ARTIFACTORY_URL --repo fpga-generic --token env:ARTIFACTORY_TOKEN
```

That writes both an immutable versioned copy and the moving `latest` pointer:

```
fpga-generic/ip-drivers/1.2.0/ip-drivers.json
fpga-generic/ip-drivers/latest/ip-drivers.json
```

Publishing a `db_version` that already exists **fails by design**. If you get
`driver database v1.2.0 is already published`, do not reach for `--force` —
bump and publish again:

```bash
python -m ipman db bump patch -m "corrected pwm_ctrl ref"
```

`--force` exists for repairing a genuinely broken upload, and it breaks the
promise that a pinned version never changes underneath a project.

### Version bump policy

`db add` and `db remove` bump automatically — `--bump minor` by default.

| Change | Bump | Why |
| --- | --- | --- |
| New IP, or a new `match` rule for an existing IP | `minor` | purely additive |
| Point an existing rule at a newer driver release | `patch` | same IP, same hardware versions |
| Remove an IP, change a `target`, narrow a `match` | `major` | can break a project that resolved yesterday |

---

## Step 6 — Consuming projects pick it up

Projects tracking `latest` get it on their next configure. Projects pinning a
version bump it deliberately:

```cmake
ipman_fetch_db(
  URL        https://acme.jfrog.io/artifactory
  REPO       fpga-generic
  DB_VERSION 1.2.0                     # was 1.1.0
  OUTPUT     ${CMAKE_BINARY_DIR}/ip-drivers.json
  TOKEN      env:ARTIFACTORY_TOKEN)
```

Or from the command line, without touching `CMakeLists.txt`:

```bash
cmake -S . -B build \
  -DHELLO_ARTIFACTORY_URL=https://acme.jfrog.io/artifactory \
  -DHELLO_IP_DB_VERSION=1.2.0
```

---

## Common follow-up tasks

### The IP got a new hardware version

Vivado bumps `pwm_ctrl` from 1.2 to 2.0 with a new register map. Add a rule —
don't edit the old one, designs still on 1.x need it:

```bash
python -m ipman db add --vlnv acme.com:user:pwm_ctrl --match "2.*" \
  --type git --uri '${CORP_GIT}/fpga/drivers/pwm_ctrl.git' --ref v2.0.0 \
  --verify-ref
```

Most specific match wins, so `1.*` and `2.*` coexist and rule order in the file
is irrelevant. A design containing **both** versions gets two targets —
`ipdrv_pwm_ctrl_v1_2` and `ipdrv_pwm_ctrl_v2_0` — so both register maps can
live in one binary.

### New driver release, same hardware version

```bash
python -m ipman db add --vlnv acme.com:user:pwm_ctrl --match "1.*" \
  --type git --uri '${CORP_GIT}/fpga/drivers/pwm_ctrl.git' --ref v1.4.1 \
  --replace --bump patch
```

`--replace` is required. Without it the tool refuses rather than silently
overwriting a rule someone else added.

### Promote an in-project driver to the shared database

Once the driver has its own repo and a tag:

```bash
# Remove the local override...
python -m ipman db remove --db db/project-overrides.json \
  --vlnv acme.com:user:pwm_ctrl --bump major

# ...and add the real thing to the shared database.
python -m ipman db add --db db/ip-drivers.json \
  --vlnv acme.com:user:pwm_ctrl --match "1.*" \
  --type git --uri '${CORP_GIT}/fpga/drivers/pwm_ctrl.git' --ref v1.4.0 \
  --summary "PWM controller" --owner fpga-team@acme.com

git rm -r drivers/pwm_ctrl
```

Rebuild and confirm the configure log now shows the driver arriving over git.

### Retire an IP

```bash
python -m ipman db remove --vlnv acme.com:user:old_ip --bump major
# or just one rule:
python -m ipman db remove --vlnv acme.com:user:old_ip --match "1.*" --bump major
```

Removing the last rule drops the whole entry.

### Inspect what's there

```bash
python -m ipman db list                      # human readable
python -m ipman db list -f json | jq .       # everything
python -m ipman db versions --url $ART --repo fpga-generic --token env:ARTIFACTORY_TOKEN
```

---

## Troubleshooting

| Message | Cause | Fix |
| --- | --- | --- |
| `no database entry for acme.com:user:foo` | key typo, or IP genuinely absent | re-read the key from `ipman extract`; check vendor and library segments |
| `no rule for version 2.0 (database has 1.*)` | hardware version outgrew the rules | add a `2.*` rule (see above) |
| `already has a rule for match '1.*'` | editing an existing rule | add `--replace` |
| `URI '...' references ${CORP_GIT}, which is not set` | variable not passed through | add it to `DEFINES` in `ipman_configure()`, or export it |
| `driver package for ... did not define target ipdrv_foo` | package defines a differently named target | set `--target` on the rule, or rename the target in the package |
| `ipman: driver for ... not found at <path>` | `path` entry points somewhere with no `CMakeLists.txt` | fix the URI; check `${PROJECT_ROOT}` is what you think |
| `no tag named 'v1.4.0' on the remote` | typo, or the tag was never pushed | `git push origin v1.4.0`; re-run with `--verify-ref` |
| `ref_type is 'commit' but 'v1.0.0' is not a hex object name` | `--ref-type commit` on a tag | drop `--ref-type`, or pass the sha |
| `ref 'main' is a branch, so the driver moves under you` | rule pins a branch | pin a tag or a full commit sha |
| `abbreviated commit ... may become ambiguous` | short sha | use the full 40 characters |
| git: `Remote branch <sha> not found in upstream` | a commit rule mis-declared as a tag | set `--ref-type commit` so the clone is not shallow |
| CMake: `HASH mismatch` on an archive | tarball rebuilt, or wrong checksum | recompute the sha256; prefer immutable release artifacts |
| `driver database v1.2.0 is already published` | republishing an existing version | `db bump patch`, then publish |
| `refusing to publish with warnings` | unpinned git ref, or archive with no sha256 | fix the rule; `--allow-warnings` only for a deliberate exception |
| Configure doesn't pick up your edit | stale build tree | database files are in `CMAKE_CONFIGURE_DEPENDS`; if you edited an unrelated file, re-run `cmake -S . -B build` |

---

## Checklist

- [ ] VLNV key read from `ipman extract`, not typed from memory
- [ ] Driver package defines `ipdrv_<name>` (or `--target` set)
- [ ] `git` rule pins a tag or full commit sha, never a branch
- [ ] `--ref-type` set explicitly if the ref is a commit with a hex-looking alternative
- [ ] `ipman db verify` clean (or the ref is deliberately templated)
- [ ] `archive` rule carries a `sha256`
- [ ] `path` rules live in the project overlay, never the shared database
- [ ] `ipman db validate --strict` clean
- [ ] `ipman resolve` shows the IP resolved, not unresolved
- [ ] Full `cmake --build` and `ctest` pass
- [ ] PR merged to the database repo before publishing
- [ ] Published to Artifactory on a tag; version bumped, never `--force`

See the top-level [README](../README.md) for the database schema, the CMake
API, and the Artifactory layout.
