"""Tests for ipman.  Run with:  python -m unittest discover -s tests

Everything here is offline: the XSA is built in a temp directory and the
Artifactory tests run against a throwaway HTTP server that implements the
handful of endpoints ipman actually uses.
"""
from __future__ import annotations

import contextlib
import http.server
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "sample"))

from ipman import artifactory as art  # noqa: E402
from ipman import db as dbmod  # noqa: E402
from ipman import xsa as xsamod  # noqa: E402
from ipman.cmakegen import generate_cmake, generate_header  # noqa: E402
from ipman.resolve import resolve  # noqa: E402
from ipman.util import IpmanError, expand_env  # noqa: E402

import make_sample_xsa  # noqa: E402


def make_xsa(path: Path) -> Path:
    """Build the sample XSA without its progress line landing in test output."""
    with contextlib.redirect_stdout(io.StringIO()):
        make_sample_xsa.main([str(path)])
    return path


def build_db(tmp: Path, name: str, entries) -> Path:
    database = dbmod.empty_db()
    for key, match, source in entries:
        dbmod.add_driver(database, key, match, source)
    path = tmp / name
    dbmod.save(path, database)
    return path


class TestXsaExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.xsa = Path(cls.tmp.name) / "design_1.xsa"
        make_xsa(cls.xsa)
        cls.manifest = xsamod.extract(cls.xsa)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_instances_found(self):
        self.assertEqual(len(self.manifest["ips"]), 9)

    def test_custom_ip_flagged(self):
        custom = {ip["instance"] for ip in self.manifest["ips"] if ip["custom"]}
        self.assertEqual(custom, {"pwm_ctrl_0", "pwm_ctrl_1", "adc_stream_0",
                                  "axi_gpio_lite_0", "crypto_accel_0"})

    def test_vendor_ip_not_flagged(self):
        vendor = {ip["instance"] for ip in self.manifest["ips"] if not ip["custom"]}
        self.assertIn("axi_gpio_0", vendor)
        self.assertIn("processing_system7_0", vendor)

    def test_base_address_from_memranges(self):
        by_name = {ip["instance"]: ip for ip in self.manifest["ips"]}
        self.assertEqual(by_name["pwm_ctrl_0"]["base_address"], "0x43C00000")
        self.assertEqual(by_name["pwm_ctrl_1"]["base_address"], "0x43C10000")
        self.assertEqual(by_name["pwm_ctrl_0"]["high_address"], "0x43C0FFFF")

    def test_vlnv_split(self):
        by_name = {ip["instance"]: ip for ip in self.manifest["ips"]}
        pwm = by_name["pwm_ctrl_0"]
        self.assertEqual((pwm["vendor"], pwm["library"], pwm["name"], pwm["version"]),
                         ("acme.com", "user", "pwm_ctrl", "1.2"))

    def test_source_is_fingerprinted(self):
        self.assertEqual(len(self.manifest["source"]["sha256"]), 64)
        self.assertEqual(self.manifest["source"]["vivado_version"], "2024.1")

    def test_rejects_non_zip(self):
        junk = Path(self.tmp.name) / "not_really.xsa"
        junk.write_text("nope")
        with self.assertRaises(IpmanError):
            xsamod.extract(junk)


class TestVersionMatching(unittest.TestCase):
    def setUp(self):
        self.db = dbmod.empty_db()
        for match, uri in (("*", "catchall"), ("1.*", "one_x"), ("1.2", "exact")):
            dbmod.add_driver(self.db, "acme.com:user:pwm_ctrl", match,
                             {"type": "path", "uri": uri})

    def _uri(self, version):
        hit = dbmod.lookup(self.db, "acme.com:user:pwm_ctrl", version)
        return None if hit is None else hit[1]["uri"]

    def test_exact_beats_glob(self):
        self.assertEqual(self._uri("1.2"), "exact")

    def test_glob_beats_catchall(self):
        self.assertEqual(self._uri("1.7"), "one_x")

    def test_catchall_is_last_resort(self):
        self.assertEqual(self._uri("9.9"), "catchall")

    def test_order_in_file_does_not_matter(self):
        entry = self.db["drivers"]["acme.com:user:pwm_ctrl"]
        entry["versions"].reverse()
        self.assertEqual(self._uri("1.2"), "exact")

    def test_unknown_ip_returns_none(self):
        self.assertIsNone(dbmod.lookup(self.db, "acme.com:user:nope", "1.0"))

    def test_duplicate_match_rejected(self):
        with self.assertRaises(IpmanError):
            dbmod.add_driver(self.db, "acme.com:user:pwm_ctrl", "1.2",
                             {"type": "path", "uri": "other"})

    def test_replace_allows_update(self):
        dbmod.add_driver(self.db, "acme.com:user:pwm_ctrl", "1.2",
                         {"type": "path", "uri": "newer"}, replace=True)
        self.assertEqual(self._uri("1.2"), "newer")


class TestDatabaseMaintenance(unittest.TestCase):
    def test_bump_levels(self):
        db = dbmod.empty_db()
        db["db_version"] = "1.2.3"
        self.assertEqual(dbmod.bump(db, "patch"), "1.2.4")
        self.assertEqual(dbmod.bump(db, "minor"), "1.3.0")
        self.assertEqual(dbmod.bump(db, "major"), "2.0.0")

    def test_changelog_records_author(self):
        db = dbmod.empty_db()
        dbmod.log_change(db, "added something", "someone")
        self.assertEqual(db["changelog"][0]["author"], "someone")
        self.assertEqual(db["changelog"][0]["db_version"], db["db_version"])

    def test_validate_rejects_bad_key(self):
        db = dbmod.empty_db()
        db["drivers"]["not_a_vlnv"] = {"versions": [{"match": "*", "type": "path",
                                                     "uri": "x"}]}
        with self.assertRaises(IpmanError):
            dbmod.validate(db)

    def test_validate_warns_on_unpinned_git(self):
        db = dbmod.empty_db()
        dbmod.add_driver(db, "a.com:user:ip", "*", {"type": "git", "uri": "u"})
        warnings = dbmod.validate(db)
        self.assertTrue(any("no 'ref'" in w for w in warnings))

    def test_remove_drops_empty_entry(self):
        db = dbmod.empty_db()
        dbmod.add_driver(db, "a.com:user:ip", "*", {"type": "path", "uri": "u"})
        dbmod.remove_driver(db, "a.com:user:ip", "*")
        self.assertNotIn("a.com:user:ip", db["drivers"])

    def test_roundtrip_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_db(Path(tmp), "db.json",
                            [("a.com:user:ip", "1.*", {"type": "path", "uri": "u"})])
            reloaded = dbmod.load(path)
            self.assertIn("a.com:user:ip", reloaded["drivers"])


class TestOverlay(unittest.TestCase):
    def test_overlay_overrides_and_extends(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shared = build_db(tmp, "shared.json", [
                ("a.com:user:gpio", "1.*", {"type": "git", "uri": "shared_gpio"}),
                ("a.com:user:pwm", "1.*", {"type": "git", "uri": "shared_pwm"}),
            ])
            overlay = build_db(tmp, "overlay.json", [
                ("a.com:user:pwm", "1.*", {"type": "path", "uri": "local_pwm"}),
                ("a.com:user:extra", "*", {"type": "path", "uri": "local_extra"}),
            ])
            merged = dbmod.load_many([shared, overlay])

            self.assertEqual(dbmod.lookup(merged, "a.com:user:pwm", "1.0")[1]["uri"],
                             "local_pwm")
            self.assertEqual(dbmod.lookup(merged, "a.com:user:gpio", "1.0")[1]["uri"],
                             "shared_gpio")
            self.assertIsNotNone(dbmod.lookup(merged, "a.com:user:extra", "3.0"))
            self.assertEqual(merged["db_version"], "0.1.0+0.1.0")

    def test_relative_path_resolves_against_its_own_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "sub").mkdir()
            shared = build_db(tmp, "shared.json", [
                ("a.com:user:gpio", "*", {"type": "path", "uri": "drivers/gpio"})])
            overlay = build_db(tmp / "sub", "overlay.json", [
                ("a.com:user:pwm", "*", {"type": "path", "uri": "drivers/pwm"})])
            merged = dbmod.load_many([shared, overlay])

            gpio = dbmod.resolve_source(
                dbmod.lookup(merged, "a.com:user:gpio", "1.0")[1], shared)
            pwm = dbmod.resolve_source(
                dbmod.lookup(merged, "a.com:user:pwm", "1.0")[1], shared)
            self.assertTrue(gpio["uri"].endswith("/drivers/gpio"))
            self.assertTrue(pwm["uri"].endswith("/sub/drivers/pwm"))


class TestResolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        xsa = make_xsa(tmp / "design_1.xsa")
        cls.manifest = xsamod.extract(xsa)
        cls.db_path = build_db(tmp, "db.json", [
            ("acme.com:user:pwm_ctrl", "1.*", {"type": "path", "uri": "d/pwm"}),
            ("acme.com:user:adc_stream", "1.*",
             {"type": "archive", "uri": "http://x/adc-1.9.0.tgz", "sha256": "a" * 64}),
            ("acme.com:user:adc_stream", "2.*",
             {"type": "archive", "uri": "http://x/adc-2.1.0.tgz", "sha256": "b" * 64}),
            ("acme.com:user:axi_gpio_lite", "1.*",
             {"type": "git", "uri": "${CORP_GIT}/gpio.git", "ref": "v1.0.0"}),
        ])
        cls.db = dbmod.load_many([cls.db_path])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _lock(self, **kwargs):
        kwargs.setdefault("subs", {"CORP_GIT": "https://git.acme.com"})
        return resolve(self.manifest, self.db, self.db_path, **kwargs)

    def test_instances_of_one_ip_share_a_driver(self):
        lock = self._lock()
        pwm = [d for d in lock["drivers"] if d["ip"].endswith("pwm_ctrl")][0]
        self.assertEqual([i["instance"] for i in pwm["instances"]],
                         ["pwm_ctrl_0", "pwm_ctrl_1"])
        self.assertEqual(pwm["target"], "ipdrv_pwm_ctrl")

    def test_hardware_version_selects_the_driver(self):
        lock = self._lock()
        adc = [d for d in lock["drivers"] if d["ip"].endswith("adc_stream")][0]
        self.assertEqual(adc["ip_version"], "2.0")
        self.assertEqual(adc["source"]["uri"], "http://x/adc-2.1.0.tgz")

    def test_missing_ip_is_reported_not_fatal(self):
        lock = self._lock()
        self.assertEqual([u["ip"] for u in lock["unresolved"]],
                         ["acme.com:hls:crypto_accel"])

    def test_strict_mode_fails_on_missing_driver(self):
        with self.assertRaises(IpmanError):
            self._lock(strict=True)

    def test_vendor_ip_skipped_by_default(self):
        lock = self._lock()
        self.assertEqual(lock["skipped_vendor_ip"], 4)

    def test_uri_variables_expanded(self):
        lock = self._lock()
        gpio = [d for d in lock["drivers"] if d["ip"].endswith("axi_gpio_lite")][0]
        self.assertEqual(gpio["source"]["uri"], "https://git.acme.com/gpio.git")

    def test_same_ip_at_two_versions_gets_two_targets(self):
        # Splice a second pwm_ctrl at 2.0 into the manifest.
        manifest = json.loads(json.dumps(self.manifest))
        older = [ip for ip in manifest["ips"] if ip["instance"] == "pwm_ctrl_1"][0]
        older["version"] = "2.0"
        older["vlnv"] = "acme.com:user:pwm_ctrl:2.0"
        db = dbmod.load_many([self.db_path])
        dbmod.add_driver(db, "acme.com:user:pwm_ctrl", "2.*",
                         {"type": "path", "uri": "d/pwm2"})
        lock = resolve(manifest, db, self.db_path,
                       subs={"CORP_GIT": "https://git.acme.com"})
        targets = sorted(d["target"] for d in lock["drivers"]
                         if d["ip"].endswith("pwm_ctrl"))
        self.assertEqual(targets, ["ipdrv_pwm_ctrl_v1_2", "ipdrv_pwm_ctrl_v2_0"])

    def test_missing_uri_variable_is_a_clean_error(self):
        with self.assertRaises(IpmanError):
            resolve(self.manifest, self.db, self.db_path, subs={})


class TestGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        xsa = make_xsa(tmp / "design_1.xsa")
        cls.manifest = xsamod.extract(xsa)
        db_path = build_db(tmp, "db.json", [
            ("acme.com:user:pwm_ctrl", "1.*",
             {"type": "path", "uri": "dir with spaces/pwm"}),
            ("acme.com:user:adc_stream", "2.*",
             {"type": "archive", "uri": "http://x/adc.tgz", "sha256": "b" * 64}),
            ("acme.com:user:axi_gpio_lite", "1.*",
             {"type": "git", "uri": "https://git/gpio.git", "ref": "v1.0.0",
              "subdir": "driver"}),
        ])
        cls.lock = resolve(cls.manifest, dbmod.load_many([db_path]), db_path)
        cls.cmake = generate_cmake(cls.lock, tmp / "ipman_ips.h")
        cls.header = generate_header(cls.manifest, cls.lock)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_git_source_is_pinned_and_shallow(self):
        self.assertIn('GIT_REPOSITORY "https://git/gpio.git"', self.cmake)
        self.assertIn('GIT_TAG "v1.0.0"', self.cmake)
        self.assertIn("GIT_SHALLOW TRUE", self.cmake)
        self.assertIn('SOURCE_SUBDIR "driver"', self.cmake)

    def test_archive_source_carries_hash(self):
        self.assertIn('URL_HASH "SHA256=%s"' % ("b" * 64), self.cmake)

    def test_path_source_is_quoted(self):
        self.assertIn('add_subdirectory("', self.cmake)
        self.assertIn("dir with spaces/pwm", self.cmake)

    def test_driver_variables_exposed_to_the_package(self):
        self.assertIn('set(IPMAN_DRIVER_INSTANCES "pwm_ctrl_0;pwm_ctrl_1")', self.cmake)

    def test_missing_target_is_caught(self):
        self.assertIn("if(NOT TARGET ipdrv_pwm_ctrl)", self.cmake)

    def test_unresolved_ip_warns_at_configure_time(self):
        self.assertIn("message(WARNING", self.cmake)
        self.assertIn("crypto_accel", self.cmake)

    def test_header_defines_base_addresses(self):
        self.assertIn("#define PWM_CTRL_0_BASEADDR", self.header)
        self.assertIn("0x43C00000UL", self.header)

    def test_header_lists_every_custom_ip(self):
        self.assertIn("#define IPMAN_IP_COUNT       5", self.header)
        self.assertIn('"acme.com:user:pwm_ctrl:1.2"', self.header)

    def test_header_marks_undriven_ip(self):
        line = [ln for ln in self.header.splitlines() if "crypto_accel_0" in ln][0]
        self.assertIn('"", ', line)


class _FakeArtifactory(http.server.BaseHTTPRequestHandler):
    """Just enough of the Artifactory REST surface for the client to be real."""

    store: dict = {}

    def log_message(self, *args):  # keep the test output quiet
        pass

    def _path(self):
        return self.path.split("?")[0]

    def do_HEAD(self):
        self.send_response(200 if self._path() in self.store else 404)
        self.end_headers()

    def do_GET(self):
        path = self._path()
        if path.startswith("/artifactory/api/storage/"):
            prefix = path.replace("/artifactory/api/storage", "/artifactory")
            folders = sorted({key[len(prefix):].strip("/").split("/")[0]
                              for key in self.store if key.startswith(prefix + "/")})
            body = json.dumps({"children": [{"uri": "/" + f, "folder": True}
                                            for f in folders]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if path not in self.store:
            self.send_response(404)
            self.end_headers()
            return
        data, digest = self.store[path]
        self.send_response(200)
        self.send_header("X-Checksum-Sha256", digest)
        self.end_headers()
        self.wfile.write(data)

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length)
        self.store[self._path()] = (data, self.headers.get("X-Checksum-Sha256", ""))
        self.send_response(201)
        self.end_headers()


class TestArtifactory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _FakeArtifactory.store = {}
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _FakeArtifactory)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d/artifactory" % cls.server.server_address[1]
        cls.tmp = tempfile.TemporaryDirectory()
        cls.headers = art.credential_headers(token="secret")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def _db_file(self, version: str) -> Path:
        db = dbmod.empty_db()
        dbmod.add_driver(db, "a.com:user:ip", "*", {"type": "path", "uri": "u"})
        db["db_version"] = version
        path = Path(self.tmp.name) / ("db-%s.json" % version)
        dbmod.save(path, db)
        return path

    def test_auth_header_forms(self):
        self.assertEqual(art.credential_headers(token="t")["Authorization"], "Bearer t")
        self.assertIn("X-JFrog-Art-Api", art.credential_headers(api_key="k"))
        self.assertTrue(art.credential_headers(user="u", password="p")["Authorization"]
                        .startswith("Basic "))

    def test_publish_then_fetch_roundtrip(self):
        path = self._db_file("2.0.0")
        result = art.publish(path, self.base, "fpga-generic", "ip-drivers",
                             self.headers)
        self.assertEqual(result["version"], "2.0.0")
        self.assertEqual(len(result["urls"]), 2)  # versioned + latest

        out = Path(self.tmp.name) / "fetched.json"
        got = art.fetch(self.base, "fpga-generic", "ip-drivers", "2.0.0", out,
                        self.headers)
        self.assertEqual(got["db_version"], "2.0.0")
        self.assertEqual(json.loads(out.read_text())["db_version"], "2.0.0")

    def test_latest_pointer_follows_the_newest_publish(self):
        art.publish(self._db_file("3.0.0"), self.base, "fpga-generic", "ip-drivers",
                    self.headers)
        out = Path(self.tmp.name) / "latest.json"
        got = art.fetch(self.base, "fpga-generic", "ip-drivers", "latest", out,
                        self.headers)
        self.assertEqual(got["db_version"], "3.0.0")

    def test_published_versions_are_immutable(self):
        path = self._db_file("4.0.0")
        art.publish(path, self.base, "fpga-generic", "ip-drivers", self.headers)
        with self.assertRaises(IpmanError) as ctx:
            art.publish(path, self.base, "fpga-generic", "ip-drivers", self.headers)
        self.assertIn("already published", str(ctx.exception))
        art.publish(path, self.base, "fpga-generic", "ip-drivers", self.headers,
                    force=True)

    def test_list_published_versions(self):
        art.publish(self._db_file("5.0.0"), self.base, "fpga-generic", "ip-drivers",
                    self.headers)
        versions = art.list_versions(self.base, "fpga-generic", "ip-drivers",
                                     self.headers)
        self.assertIn("5.0.0", versions)
        self.assertIn("latest", versions)

    def test_missing_version_is_a_clean_error(self):
        with self.assertRaises(IpmanError):
            art.fetch(self.base, "fpga-generic", "ip-drivers", "9.9.9",
                      Path(self.tmp.name) / "nope.json", self.headers)


class TestEnvExpansion(unittest.TestCase):
    def test_substitutions_win_over_environment(self):
        self.assertEqual(expand_env("${A}/x", {"A": "sub"}), "sub/x")

    def test_unset_variable_raises_ipman_error(self):
        with self.assertRaises(IpmanError):
            expand_env("${DEFINITELY_NOT_SET_12345}/x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
