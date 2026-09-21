"""Publish and fetch the driver database from an Artifactory generic repo.

Artifactory Community Edition / the free cloud tier both provide generic
repositories and the plain REST API used here (PUT to deploy, GET to fetch,
/api/storage to list), so no commercial feature and no JFrog CLI is required.
Only the standard library is used.

Version control model
---------------------
git is the source of truth for editing the database; Artifactory holds the
immutable published copies that projects pin to::

    <repo>/<prefix>/<db_version>/ip-drivers.json   # immutable, never overwritten
    <repo>/<prefix>/latest/ip-drivers.json         # moving pointer, always rewritten

`publish` refuses to overwrite an existing version unless --force, which is
what gives you the immutability guarantee on a tier without a retention or
release-bundle feature.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .util import IpmanError, sha256_bytes

DB_FILENAME = "ip-drivers.json"


def credential_headers(token: str | None = None, api_key: str | None = None,
                       user: str | None = None, password: str | None = None) -> dict:
    """Build auth headers. Any value may be given as 'env:VARNAME'."""
    def deref(value):
        if value and value.startswith("env:"):
            name = value[4:]
            if name not in os.environ:
                raise IpmanError("environment variable %s is not set" % name)
            return os.environ[name]
        return value

    token, api_key = deref(token), deref(api_key)
    user, password = deref(user), deref(password)

    if token:
        return {"Authorization": "Bearer " + token}
    if api_key:
        return {"X-JFrog-Art-Api": api_key}
    if user and password:
        raw = base64.b64encode(("%s:%s" % (user, password)).encode()).decode()
        return {"Authorization": "Basic " + raw}
    return {}


def _request(method: str, url: str, headers: dict, data: bytes | None = None,
             timeout: int = 60):
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers or {})
    except urllib.error.URLError as exc:
        raise IpmanError("cannot reach %s: %s" % (url, exc.reason))


def _join(base: str, *parts: str) -> str:
    out = base.rstrip("/")
    for part in parts:
        out += "/" + str(part).strip("/")
    return out


def db_url(base_url: str, repo: str, prefix: str, version: str) -> str:
    return _join(base_url, repo, prefix, version, DB_FILENAME)


def publish(db_path, base_url: str, repo: str, prefix: str, headers: dict,
            force: bool = False, update_latest: bool = True) -> dict:
    db_path = Path(db_path)
    payload = db_path.read_bytes()
    db = json.loads(payload.decode("utf-8"))
    version = db["db_version"]
    digest = sha256_bytes(payload)

    target = db_url(base_url, repo, prefix, version)
    status, _, _ = _request("HEAD", target, headers)
    if status == 200 and not force:
        raise IpmanError(
            "driver database v%s is already published at %s.\n"
            "Published versions are immutable -- bump the version "
            "(ipman db bump) and publish again, or pass --force." % (version, target))
    if status in (401, 403):
        raise IpmanError("authentication rejected by Artifactory (HTTP %d)" % status)

    deploy_headers = dict(headers)
    deploy_headers["Content-Type"] = "application/json"
    deploy_headers["X-Checksum-Sha256"] = digest

    results = {"version": version, "sha256": digest, "urls": []}
    for url in ([target] + ([db_url(base_url, repo, prefix, "latest")]
                            if update_latest else [])):
        status, body, _ = _request("PUT", url, deploy_headers, data=payload)
        if status not in (200, 201):
            raise IpmanError("upload to %s failed (HTTP %d): %s"
                             % (url, status, body.decode("utf-8", "replace")[:400]))
        results["urls"].append(url)
    return results


def fetch(base_url: str, repo: str, prefix: str, version: str, out_path,
          headers: dict) -> dict:
    url = db_url(base_url, repo, prefix, version)
    status, body, resp_headers = _request("GET", url, headers)
    if status == 404:
        raise IpmanError("no driver database at %s" % url)
    if status in (401, 403):
        raise IpmanError("authentication rejected by Artifactory (HTTP %d)" % status)
    if status != 200:
        raise IpmanError("download failed (HTTP %d): %s"
                         % (status, body.decode("utf-8", "replace")[:400]))

    digest = sha256_bytes(body)
    declared = (resp_headers.get("X-Checksum-Sha256")
                or resp_headers.get("x-checksum-sha256"))
    if declared and declared.lower() != digest:
        raise IpmanError("checksum mismatch for %s: Artifactory says %s, got %s"
                         % (url, declared, digest))

    db = json.loads(body.decode("utf-8"))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(body)
    return {"url": url, "sha256": digest, "db_version": db.get("db_version"),
            "path": out_path.as_posix()}


def list_versions(base_url: str, repo: str, prefix: str, headers: dict) -> list:
    url = _join(base_url, "api/storage", repo, prefix)
    status, body, _ = _request("GET", url, headers)
    if status == 404:
        return []
    if status != 200:
        raise IpmanError("listing failed (HTTP %d): %s"
                         % (status, body.decode("utf-8", "replace")[:400]))
    data = json.loads(body.decode("utf-8"))
    return sorted(child["uri"].lstrip("/") for child in data.get("children", [])
                  if child.get("folder"))
