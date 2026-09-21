"""Tests for git ref handling: what a rule pins, and whether it exists.

Run with the rest of the suite:  python -m unittest discover -s tests
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "sample"))

from ipman import db as dbmod  # noqa: E402
from ipman import gitref  # noqa: E402
from ipman import xsa as xsamod  # noqa: E402
from ipman.cmakegen import generate_cmake  # noqa: E402
from ipman.resolve import ip_substitutions, resolve  # noqa: E402
from ipman.util import IpmanError  # noqa: E402

from test_ipman import build_db, make_xsa  # noqa: E402


class TestRefClassification(unittest.TestCase):
    def test_hex_object_name_is_a_commit(self):
        self.assertEqual(gitref.classify("9f2c1ab"), "commit")
        self.assertEqual(gitref.classify("a" * 40), "commit")

    def test_tag_name_is_a_tag(self):
        self.assertEqual(gitref.classify("v1.4.0"), "tag")
        self.assertEqual(gitref.classify("release-2024"), "tag")

    def test_explicit_type_wins_over_the_guess(self):
        # A tag that happens to be all hex would otherwise look like a commit.
        self.assertEqual(gitref.classify("abcdef1", "tag"), "tag")
        self.assertEqual(gitref.classify("main", "branch"), "branch")

    def test_bad_ref_type_rejected(self):
        with self.assertRaises(IpmanError):
            gitref.classify("v1.0.0", "sha")

    def test_only_tags_and_branches_can_be_shallow_cloned(self):
        self.assertTrue(gitref.can_shallow_clone("v1.4.0"))
        self.assertTrue(gitref.can_shallow_clone("main", "branch"))
        self.assertFalse(gitref.can_shallow_clone("9f2c1ab"))
        self.assertFalse(gitref.can_shallow_clone("a" * 40))


class TestRefValidation(unittest.TestCase):
    def _db(self, source):
        db = dbmod.empty_db()
        dbmod.add_driver(db, "a.com:user:ip", "*", source)
        return db

    def test_commit_type_on_a_non_sha_is_rejected(self):
        db = self._db({"type": "git", "uri": "u", "ref": "v1.0.0",
                       "ref_type": "commit"})
        with self.assertRaises(IpmanError):
            dbmod.validate(db)

    def test_unknown_ref_type_is_rejected(self):
        db = self._db({"type": "git", "uri": "u", "ref": "v1.0.0",
                       "ref_type": "sha"})
        with self.assertRaises(IpmanError):
            dbmod.validate(db)

    def test_branch_ref_warns(self):
        db = self._db({"type": "git", "uri": "u", "ref": "main",
                       "ref_type": "branch"})
        self.assertTrue(any("moves under you" in w for w in dbmod.validate(db)))

    def test_abbreviated_commit_warns(self):
        db = self._db({"type": "git", "uri": "u", "ref": "9f2c1ab"})
        self.assertTrue(any("ambiguous" in w for w in dbmod.validate(db)))

    def test_full_commit_is_clean(self):
        db = self._db({"type": "git", "uri": "u", "ref": "a" * 40})
        self.assertEqual(dbmod.validate(db), [])

    def test_tag_is_clean(self):
        db = self._db({"type": "git", "uri": "u", "ref": "v1.4.0"})
        self.assertEqual(dbmod.validate(db), [])

    def test_templated_ref_is_not_second_guessed(self):
        db = self._db({"type": "git", "uri": "u", "ref": "v${IP_VERSION}.0"})
        self.assertEqual(dbmod.validate(db), [])


class TestRefTemplating(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manifest = xsamod.extract(make_xsa(Path(self.tmp.name) / "design_1.xsa"))

    def tearDown(self):
        self.tmp.cleanup()

    def _resolve(self, entries, manifest=None):
        path = build_db(Path(self.tmp.name), "db.json", entries)
        return resolve(manifest or self.manifest, dbmod.load_many([path]), path)

    def test_substitutions_available_to_a_rule(self):
        subs = ip_substitutions("acme.com:user:pwm_ctrl", "1.2")
        self.assertEqual(subs["IP_NAME"], "pwm_ctrl")
        self.assertEqual(subs["IP_VENDOR"], "acme.com")
        self.assertEqual(subs["IP_LIBRARY"], "user")
        self.assertEqual(subs["IP_VERSION"], "1.2")
        self.assertEqual(subs["IP_VERSION_MAJOR"], "1")
        self.assertEqual(subs["IP_VERSION_MINOR"], "2")

    def test_ip_version_drives_the_tag(self):
        lock = self._resolve([("acme.com:user:pwm_ctrl", "1.*",
                               {"type": "git", "uri": "g", "ref": "v${IP_VERSION}.0"})])
        pwm = [d for d in lock["drivers"] if d["ip"].endswith("pwm_ctrl")][0]
        self.assertEqual(pwm["source"]["ref"], "v1.2.0")
        self.assertEqual(pwm["source"]["ref_type"], "tag")

    def test_major_version_drives_the_tag(self):
        lock = self._resolve([("acme.com:user:adc_stream", "2.*",
                               {"type": "git", "uri": "g",
                                "ref": "release/${IP_VERSION_MAJOR}.x"})])
        adc = [d for d in lock["drivers"] if d["ip"].endswith("adc_stream")][0]
        self.assertEqual(adc["source"]["ref"], "release/2.x")

    def test_substitutions_reach_uri_and_subdir(self):
        lock = self._resolve([("acme.com:user:pwm_ctrl", "1.*",
                               {"type": "git", "uri": "g/${IP_NAME}.git",
                                "ref": "v1.0.0", "subdir": "drivers/${IP_NAME}"})])
        pwm = [d for d in lock["drivers"] if d["ip"].endswith("pwm_ctrl")][0]
        self.assertEqual(pwm["source"]["uri"], "g/pwm_ctrl.git")
        self.assertEqual(pwm["source"]["subdir"], "drivers/pwm_ctrl")

    def test_exact_rules_map_versions_to_different_tags(self):
        manifest = json.loads(json.dumps(self.manifest))
        second = [ip for ip in manifest["ips"] if ip["instance"] == "pwm_ctrl_1"][0]
        second["version"] = "1.3"
        second["vlnv"] = "acme.com:user:pwm_ctrl:1.3"
        lock = self._resolve([
            ("acme.com:user:pwm_ctrl", "1.2",
             {"type": "git", "uri": "g", "ref": "v1.4.0"}),
            ("acme.com:user:pwm_ctrl", "1.3",
             {"type": "git", "uri": "g", "ref": "v1.5.2"}),
        ], manifest=manifest)
        got = {d["ip_version"]: d["source"]["ref"] for d in lock["drivers"]
               if d["ip"].endswith("pwm_ctrl")}
        self.assertEqual(got, {"1.2": "v1.4.0", "1.3": "v1.5.2"})

    def test_ref_kind_is_judged_after_expansion(self):
        lock = self._resolve([("acme.com:user:pwm_ctrl", "1.*",
                               {"type": "git", "uri": "g",
                                "ref": "${IP_VERSION_MAJOR}abcdef"})])
        cmake = generate_cmake(lock)
        # Expands to "1abcdef", a valid object name, so no shallow clone.
        self.assertIn('GIT_TAG "1abcdef"', cmake)
        self.assertNotIn("GIT_SHALLOW", cmake)


class TestShallowCloneGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.manifest = xsamod.extract(make_xsa(Path(cls.tmp.name) / "d.xsa"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _cmake(self, source):
        path = build_db(Path(self.tmp.name), "db.json",
                        [("acme.com:user:pwm_ctrl", "1.*", source)])
        return generate_cmake(resolve(self.manifest, dbmod.load_many([path]), path))

    def test_tag_is_shallow_cloned(self):
        cmake = self._cmake({"type": "git", "uri": "g", "ref": "v1.4.0"})
        self.assertIn("GIT_SHALLOW TRUE", cmake)
        self.assertIn("# tag", cmake)

    def test_branch_is_shallow_cloned(self):
        cmake = self._cmake({"type": "git", "uri": "g", "ref": "main",
                             "ref_type": "branch"})
        self.assertIn("GIT_SHALLOW TRUE", cmake)

    def test_full_commit_is_not_shallow_cloned(self):
        cmake = self._cmake({"type": "git", "uri": "g", "ref": "a" * 40})
        self.assertNotIn("GIT_SHALLOW", cmake)
        self.assertIn("# commit", cmake)

    def test_abbreviated_commit_is_not_shallow_cloned(self):
        # Regression: a short sha used to be mistaken for a tag, generating
        # `git clone --depth 1 --branch <sha>`, which always fails.
        cmake = self._cmake({"type": "git", "uri": "g", "ref": "9f2c1ab"})
        self.assertNotIn("GIT_SHALLOW", cmake)

    def test_hex_looking_tag_declared_as_a_tag_is_shallow_cloned(self):
        cmake = self._cmake({"type": "git", "uri": "g", "ref": "abcdef1",
                             "ref_type": "tag"})
        self.assertIn("GIT_SHALLOW TRUE", cmake)


@unittest.skipUnless(shutil.which("git"), "git is not on PATH")
class TestRefVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        work = Path(cls.tmp.name) / "work"
        work.mkdir()
        env = ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
               "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]

        def git(*args):
            subprocess.run(["git", *env, *args], cwd=str(work), check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        (work / "CMakeLists.txt").write_text("# driver\n")
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "first")
        git("tag", "-a", "v1.0.0", "-m", "v1.0.0")   # annotated
        git("tag", "lightweight-1.0")                # lightweight

        cls.bare = Path(cls.tmp.name) / "driver.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(work), str(cls.bare)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.uri = cls.bare.as_posix()
        cls.head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(work),
                                  check=True, capture_output=True,
                                  text=True).stdout.strip()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_annotated_tag_resolves_to_its_commit(self):
        result = gitref.verify(self.uri, "v1.0.0")
        self.assertEqual(result["status"], "ok")
        # Not the tag object -- the commit it peels to, which is what you pin.
        self.assertEqual(result["sha"], self.head)

    def test_lightweight_tag(self):
        self.assertEqual(gitref.verify(self.uri, "lightweight-1.0")["status"], "ok")

    def test_branch(self):
        result = gitref.verify(self.uri, "main", "branch")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["sha"], self.head)

    def test_missing_tag_is_reported(self):
        result = gitref.verify(self.uri, "v9.9.9")
        self.assertEqual(result["status"], "missing")
        self.assertIn("v9.9.9", result["detail"])

    def test_commit_at_a_ref_tip_is_confirmed(self):
        self.assertEqual(gitref.verify(self.uri, self.head)["status"], "ok")

    def test_unreachable_commit_is_unknown_not_missing(self):
        # A well-formed object name we cannot confirm without fetching: say so
        # rather than claiming the rule is wrong.
        result = gitref.verify(self.uri, "0" * 40, "commit")
        self.assertEqual(result["status"], "unknown")

    def test_templated_ref_is_skipped(self):
        self.assertEqual(gitref.verify(self.uri, "v${IP_VERSION}.0")["status"],
                         "skipped")

    def test_rule_with_no_ref_is_skipped(self):
        self.assertEqual(gitref.verify(self.uri, None)["status"], "skipped")

    def test_unreachable_remote_raises(self):
        missing = Path(self.tmp.name).joinpath("nope.git").as_posix()
        with self.assertRaises(IpmanError):
            gitref.verify(missing, "v1.0.0", timeout=15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
