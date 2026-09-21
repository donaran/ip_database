"""Materialise the demo's "remote" driver sources.

Real projects point the driver database at a git server and an Artifactory
generic repo.  So the demo can run offline, this script builds local stand-ins
under sample/_demo:

    repos/axi_gpio_lite.git              a bare git repo, tagged v1.0.0
    archives/adc_stream-2.1.0.tar.gz     a reproducible driver tarball

It also writes sample/design_1.xsa, and reports the tarball's sha256 so the
database entry can pin it.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEMO = HERE / "_demo"
SRC = HERE / "driver_src"

# Fixed timestamp keeps the tarball byte-identical between runs, so its sha256
# only changes when the driver source actually changes.
EPOCH = 1_600_000_000


def run(cmd, cwd=None):
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def make_git_repo(name: str, tag: str) -> Path:
    """Commit a driver package and expose it as a bare repo to clone from."""
    repos = DEMO / "repos"
    repos.mkdir(parents=True, exist_ok=True)
    bare = repos / (name + ".git")
    if bare.exists():
        shutil.rmtree(bare)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / name
        shutil.copytree(SRC / name, work)
        env = ["-c", "user.name=ipman demo", "-c", "user.email=demo@example.invalid",
               "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]
        run(["git", *env, "init", "-q"], cwd=work)
        run(["git", *env, "add", "-A"], cwd=work)
        run(["git", *env, "commit", "-q", "-m", "%s driver" % name], cwd=work)
        run(["git", *env, "tag", "-a", tag, "-m", tag], cwd=work)
        run(["git", "clone", "-q", "--bare", str(work), str(bare)])
    print("  git repo  %s (tag %s)" % (bare.as_posix(), tag))
    return bare


def make_archive(name: str, version: str) -> tuple:
    """Pack a driver package the way a release job would, reproducibly."""
    archives = DEMO / "archives"
    archives.mkdir(parents=True, exist_ok=True)
    out = archives / ("%s-%s.tar.gz" % (name, version))

    def norm(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        info.mtime = EPOCH
        info.mode = 0o755 if info.isdir() else 0o644
        return info

    raw = out.with_suffix("")  # the .tar before compression
    with tarfile.open(raw, "w", format=tarfile.GNU_FORMAT) as tf:
        for path in sorted((SRC / name).rglob("*")):
            tf.add(path, arcname=(name + "/" + path.relative_to(SRC / name).as_posix()),
                   filter=norm, recursive=False)
    data = raw.read_bytes()
    raw.unlink()
    with open(out, "wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
            gz.write(data)

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print("  archive   %s" % out.as_posix())
    print("            sha256 %s" % digest)
    return out, digest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true",
                        help="remove sample/_demo before rebuilding it")
    args = parser.parse_args(argv)

    if args.clean and DEMO.exists():
        shutil.rmtree(DEMO)

    print("building demo hardware and driver sources under %s" % DEMO.as_posix())
    sys.path.insert(0, str(HERE))
    import make_sample_xsa  # noqa: E402

    make_sample_xsa.main([str(HERE / "design_1.xsa")])
    make_git_repo("axi_gpio_lite", "v1.0.0")
    _, digest = make_archive("adc_stream", "2.1.0")

    print("\ndatabase entries these back:")
    print("  acme.com:user:axi_gpio_lite  git      ${DEMO_GIT}/axi_gpio_lite.git @ v1.0.0")
    print("  acme.com:user:adc_stream     archive  ${DEMO_ARCHIVES}/adc_stream-2.1.0.tar.gz")
    print("                               sha256   %s" % digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
