"""Git ref handling: what kind of ref a rule pins, and does it exist.

A git driver rule pins one ref per hardware version::

    {"match": "1.2", "type": "git", "uri": "...", "ref": "v1.4.0"}
    {"match": "1.3", "type": "git", "uri": "...", "ref": "v1.5.2"}
    {"match": "2.*", "type": "git", "uri": "...", "ref": "9f2c1ab",
     "ref_type": "commit"}

`ref_type` is optional -- a ref that looks like a hex object name is treated as
a commit, anything else as a tag.  It matters because a commit cannot be
cloned shallowly by name the way a tag or branch can, and getting that wrong
produces a confusing `git clone --depth 1 --branch <sha>` failure deep inside
FetchContent rather than an error anyone can act on.
"""
from __future__ import annotations

import re
import shutil
import subprocess

from .util import IpmanError

REF_TYPES = ("tag", "branch", "commit")

# Git object names are 7-40 hex characters in practice (abbreviated to full).
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
TEMPLATE_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


def classify(ref: str | None, declared: str | None = None) -> str:
    """Return 'tag', 'branch' or 'commit' for a rule's ref.

    An explicit ref_type always wins: a tag whose name happens to be all hex
    would otherwise be mistaken for a commit.
    """
    if declared:
        if declared not in REF_TYPES:
            raise IpmanError("ref_type must be one of %s, got %r"
                             % ("/".join(REF_TYPES), declared))
        return declared
    if ref and SHA_RE.match(ref):
        return "commit"
    return "tag"


def is_templated(value: str | None) -> bool:
    """True if the value still contains ${...} and cannot be checked as-is."""
    return bool(value) and bool(TEMPLATE_RE.search(value))


def can_shallow_clone(ref: str | None, declared: str | None = None) -> bool:
    """Tags and branches can be fetched with --depth 1; commits cannot."""
    if not ref:
        return False
    return classify(ref, declared) != "commit"


def ls_remote(uri: str, ref: str | None = None, timeout: int = 20):
    """Run `git ls-remote`, returning [(sha, refname), ...].

    Raises IpmanError if git is missing or the remote cannot be reached, so
    the caller can tell "ref is wrong" apart from "I could not look".
    """
    if not shutil.which("git"):
        raise IpmanError("git is not on PATH, cannot verify refs")
    cmd = ["git", "ls-remote", uri]
    if ref:
        # The last pattern asks for the peeled target of an annotated tag;
        # without it ls-remote reports only the tag object.
        cmd += [ref, "refs/tags/" + ref, "refs/heads/" + ref,
                "refs/tags/%s^{}" % ref]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise IpmanError("timed out after %ds contacting %s" % (timeout, uri))
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise IpmanError("git ls-remote %s failed: %s"
                         % (uri, detail[-1] if detail else "unknown error"))
    out = []
    for line in proc.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            out.append((parts[0], parts[1].strip()))
    return out


def verify(uri: str, ref: str | None, ref_type: str | None = None,
           timeout: int = 20) -> dict:
    """Check that `ref` exists on `uri`.

    Returns {"status": ..., "detail": ..., "sha": ...} where status is:
      ok       the ref exists (sha is the commit it points at)
      missing  the remote answered and does not have it
      skipped  nothing to check against (no ref, or a ${templated} one)
      unknown  a commit that no branch or tag points at -- not disprovable
                without fetching, so not treated as a failure
    """
    if not ref:
        return {"status": "skipped", "detail": "rule pins no ref", "sha": None}
    if is_templated(ref) or is_templated(uri):
        return {"status": "skipped",
                "detail": "ref or uri is templated; resolved per IP version",
                "sha": None}

    kind = classify(ref, ref_type)
    if kind == "commit":
        # ls-remote lists refs, not arbitrary commits. If a branch or tag tip
        # happens to be this commit we can confirm it; otherwise we cannot say
        # it is wrong, only that we could not confirm it.
        for sha, name in ls_remote(uri, timeout=timeout):
            if sha.lower().startswith(ref.lower()):
                return {"status": "ok", "detail": "commit is the tip of %s" % name,
                        "sha": sha}
        return {"status": "unknown",
                "detail": "commit is not at a branch or tag tip; "
                          "cannot confirm without fetching",
                "sha": None}

    matches = ls_remote(uri, ref, timeout=timeout)
    peeled = "refs/tags/%s^{}" % ref
    wanted = {ref, "refs/tags/" + ref, "refs/heads/" + ref}
    # An annotated tag lists twice: the tag object, then the commit it peels
    # to. The commit is the one worth reporting and worth pinning.
    by_name = {name: sha for sha, name in matches}
    if peeled in by_name:
        return {"status": "ok",
                "detail": "refs/tags/%s -> %s" % (ref, by_name[peeled][:12]),
                "sha": by_name[peeled]}
    for sha, name in matches:
        if name in wanted:
            return {"status": "ok", "detail": "%s -> %s" % (name, sha[:12]),
                    "sha": sha}
    return {"status": "missing",
            "detail": "no %s named %r on the remote" % (kind, ref), "sha": None}
