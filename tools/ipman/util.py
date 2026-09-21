"""Small shared helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class IpmanError(Exception):
    """User-facing error; the CLI prints it without a traceback."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json_atomic(path: Path, data: dict) -> None:
    """Write pretty, stable JSON so the file diffs cleanly under git."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value: str, extra: dict | None = None) -> str:
    """Expand ${VAR} from `extra` then the environment.

    Lets the shared database hold site-neutral URIs such as
    ``${CORP_GIT}/fpga/drivers/pwm_ctrl.git``.
    """
    extra = extra or {}

    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name in extra:
            return str(extra[name])
        if name in os.environ:
            return os.environ[name]
        raise IpmanError(
            "URI %r references ${%s}, which is not set. Pass -D %s=... "
            "or export it." % (value, name, name))

    return _ENV_RE.sub(sub, value)
