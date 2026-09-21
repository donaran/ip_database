"""Tests for the driver-side manifest and the runtime register-map union.

Run with the rest of the suite:  python -m unittest discover -s tests
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from ipman import driver_manifest as dmod  # noqa: E402
from ipman import mapgen  # noqa: E402
from ipman.util import IpmanError, sha256_file  # noqa: E402

ID_REGISTER = {
    "offset": "0x00",
    "magic": {"value": "0x5057", "bits": [31, 16]},
    "major": {"bits": [15, 8]},
    "minor": {"bits": [7, 0]},
}


def manifest(**overrides) -> dict:
    base = {
        "schema": 1,
        "kind": "ipman-driver",
        "driver_version": "1.4.0",
        "target": "ipdrv_pwm_ctrl",
        "implements": [
            {"ip": "acme.com:user:pwm_ctrl", "match": "1.*",
             "map": {"type": "acme::PwmCtrlV1", "header": "pwm_ctrl_v1.hpp"}},
            {"ip": "acme.com:user:pwm_ctrl", "match": "2.*",
             "map": {"type": "acme::PwmCtrlV2", "header": "pwm_ctrl_v2.hpp"}},
        ],
        "id_register": dict(ID_REGISTER),
    }
    base.update(overrides)
    return base


def write_package(root: Path, data: dict, subdir: str = "") -> Path:
    where = root / subdir if subdir else root
    where.mkdir(parents=True, exist_ok=True)
    (where / dmod.MANIFEST_NAME).write_text(json.dumps(data, indent=2),
                                            encoding="utf-8")
    return root


class TestManifestValidation(unittest.TestCase):
    def test_a_good_manifest_passes(self):
        self.assertEqual(dmod.validate(manifest()), [])

    def test_wrong_kind_rejected(self):
        with self.assertRaises(IpmanError):
            dmod.validate(manifest(kind="something-else"))

    def test_wrong_schema_rejected(self):
        with self.assertRaises(IpmanError):
            dmod.validate(manifest(schema=99))

    def test_no_implements_rejected(self):
        with self.assertRaises(IpmanError):
            dmod.validate(manifest(implements=[]))

    def test_bad_ip_key_rejected(self):
        with self.assertRaises(IpmanError):
            dmod.validate(manifest(implements=[{"ip": "not_a_vlnv", "match": "*"}]))

    def test_implements_entry_needs_a_match(self):
        with self.assertRaises(IpmanError):
            dmod.validate(manifest(implements=[{"ip": "a.com:user:x"}]))

    def test_map_needs_type_and_header(self):
        with self.assertRaises(IpmanError):
            dmod.validate(manifest(implements=[
                {"ip": "a.com:user:x", "match": "*", "map": {"type": "X"}}]))

    def test_maps_without_an_id_register_are_rejected(self):
        data = manifest()
        del data["id_register"]
        with self.assertRaises(IpmanError) as ctx:
            dmod.validate(data)
        self.assertIn("no way to tell revisions apart", str(ctx.exception))

    def test_a_driver_with_no_maps_needs_no_id_register(self):
        self.assertEqual(
            dmod.validate({"schema": 1, "kind": "ipman-driver",
                           "target": "ipdrv_x",
                           "implements": [{"ip": "a.com:user:x", "match": "*"}]}),
            [])

    def test_missing_target_warns_only(self):
        data = manifest()
        del data["target"]
        self.assertTrue(any("no 'target'" in w for w in dmod.validate(data)))

    def test_bad_bit_range_rejected(self):
        bad = dict(ID_REGISTER, major={"bits": [7, 15]})
        with self.assertRaises(IpmanError):
            dmod.validate(manifest(id_register=bad))

    def test_bit_range_out_of_a_word_rejected(self):
        bad = dict(ID_REGISTER, minor={"bits": [47, 32]})
        with self.assertRaises(IpmanError):
            dmod.validate(manifest(id_register=bad))

    def test_hex_strings_and_ints_both_accepted(self):
        data = manifest(id_register=dict(ID_REGISTER, offset=16))
        self.assertEqual(dmod.validate(data), [])
        self.assertEqual(dmod.normalise_id_register(data["id_register"])["offset"], 16)

    def test_normalise_decodes_hex(self):
        norm = dmod.normalise_id_register(ID_REGISTER)
        self.assertEqual(norm["offset"], 0)
        self.assertEqual(norm["magic_value"], 0x5057)
        self.assertEqual(norm["major_bits"], [15, 8])


class TestCoverage(unittest.TestCase):
    def test_covers_uses_database_match_semantics(self):
        m = manifest()
        self.assertEqual(dmod.covers(m, "acme.com:user:pwm_ctrl", "1.2")["match"], "1.*")
        self.assertEqual(dmod.covers(m, "acme.com:user:pwm_ctrl", "2.7")["match"], "2.*")

    def test_uncovered_version_returns_none(self):
        self.assertIsNone(dmod.covers(manifest(), "acme.com:user:pwm_ctrl", "3.0"))

    def test_other_ip_returns_none(self):
        self.assertIsNone(dmod.covers(manifest(), "acme.com:user:other", "1.0"))

    def test_exact_entry_beats_a_glob(self):
        m = manifest(implements=[
            {"ip": "a.com:user:x", "match": "1.*"},
            {"ip": "a.com:user:x", "match": "1.2"},
        ])
        self.assertEqual(dmod.covers(m, "a.com:user:x", "1.2")["match"], "1.2")

    def test_maps_for_returns_every_revision(self):
        # The runtime union covers what the driver can serve, not just the
        # revision in today's bitstream.
        maps = dmod.maps_for(manifest(), "acme.com:user:pwm_ctrl")
        self.assertEqual([m["match"] for m in maps], ["1.*", "2.*"])


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_matching_package_verifies(self):
        pkg = write_package(self.root / "pkg", manifest())
        record = dmod.verify(pkg, "acme.com:user:pwm_ctrl", "1.2", "ipdrv_pwm_ctrl")
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["matched"], "1.*")
        self.assertEqual(len(record["maps"]), 2)
        self.assertEqual(record["id_register"]["magic_value"], 0x5057)

    def test_version_the_driver_does_not_implement_fails(self):
        pkg = write_package(self.root / "pkg", manifest())
        with self.assertRaises(IpmanError) as ctx:
            dmod.verify(pkg, "acme.com:user:pwm_ctrl", "3.1", "ipdrv_pwm_ctrl")
        self.assertIn("does not implement", str(ctx.exception))
        self.assertIn("It claims", str(ctx.exception))

    def test_ip_the_driver_does_not_implement_fails(self):
        pkg = write_package(self.root / "pkg", manifest())
        with self.assertRaises(IpmanError):
            dmod.verify(pkg, "acme.com:user:other", "1.0", "ipdrv_pwm_ctrl")

    def test_target_mismatch_fails(self):
        pkg = write_package(self.root / "pkg", manifest())
        with self.assertRaises(IpmanError) as ctx:
            dmod.verify(pkg, "acme.com:user:pwm_ctrl", "1.2", "ipdrv_wrong")
        self.assertIn("declares target", str(ctx.exception))

    def test_missing_manifest_is_tolerated_by_default(self):
        (self.root / "bare").mkdir()
        record = dmod.verify(self.root / "bare", "a.com:user:x", "1.0", "ipdrv_x")
        self.assertEqual(record["status"], "no-manifest")

    def test_missing_manifest_fails_when_required(self):
        (self.root / "bare").mkdir()
        with self.assertRaises(IpmanError):
            dmod.verify(self.root / "bare", "a.com:user:x", "1.0", "ipdrv_x",
                        require=True)

    def test_manifest_in_a_subdir_is_found_first(self):
        pkg = self.root / "repo"
        write_package(pkg, manifest(target="ipdrv_root"))
        write_package(pkg, manifest(target="ipdrv_sub"), subdir="drivers/pwm")
        found = dmod.manifest_path(pkg, "drivers/pwm")
        self.assertEqual(json.loads(found.read_text())["target"], "ipdrv_sub")

    def test_register_model_drift_fails(self):
        pkg = self.root / "pkg"
        write_package(pkg, manifest())
        rdl = pkg / "rdl" / "x.rdl"
        rdl.parent.mkdir(parents=True)
        rdl.write_text("addrmap x {};\n")
        data = manifest(register_model={"source": "rdl/x.rdl",
                                        "sha256": sha256_file(rdl)})
        write_package(pkg, data)
        # Clean first, then after the register description is edited.
        self.assertEqual(dmod.verify(pkg, "acme.com:user:pwm_ctrl", "1.2",
                                     "ipdrv_pwm_ctrl")["status"], "ok")
        rdl.write_text("addrmap x { reg {} r @ 0; };\n")
        with self.assertRaises(IpmanError) as ctx:
            dmod.verify(pkg, "acme.com:user:pwm_ctrl", "1.2", "ipdrv_pwm_ctrl")
        self.assertIn("drifted apart", str(ctx.exception))

    def test_register_model_absent_from_package_warns_only(self):
        pkg = self.root / "pkg"
        write_package(pkg, manifest(register_model={"source": "rdl/gone.rdl",
                                                    "sha256": "a" * 64}))
        record = dmod.verify(pkg, "acme.com:user:pwm_ctrl", "1.2", "ipdrv_pwm_ctrl")
        self.assertEqual(record["status"], "ok")
        self.assertTrue(any("not in the package" in w for w in record["warnings"]))


class TestVersionTests(unittest.TestCase):
    def test_major_glob(self):
        self.assertEqual(mapgen.version_test("1.*"), "v.major == 1")

    def test_exact_version(self):
        self.assertEqual(mapgen.version_test("1.2"),
                         "(v.major == 1 && v.minor == 2)")

    def test_catchall(self):
        self.assertEqual(mapgen.version_test("*"), "true")

    def test_unsupported_pattern_is_a_clean_error(self):
        with self.assertRaises(IpmanError) as ctx:
            mapgen.version_test("1.?")
        self.assertIn("runtime version test", str(ctx.exception))


class TestMapGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = write_package(Path(tmp) / "pkg", manifest())
            cls.record = dmod.verify(pkg, "acme.com:user:pwm_ctrl", "1.2",
                                     "ipdrv_pwm_ctrl")
        cls.header = mapgen.generate([cls.record], db_version="1.2.0")

    def test_includes_every_map_header(self):
        self.assertIn('#include "pwm_ctrl_v1.hpp"', self.header)
        self.assertIn('#include "pwm_ctrl_v2.hpp"', self.header)

    def test_declares_the_variant(self):
        self.assertIn("using Map = std::variant<acme::PwmCtrlV1, acme::PwmCtrlV2>;",
                      self.header)

    def test_presence_macro(self):
        self.assertIn("#define IPMAN_HAS_PWM_CTRL 1", self.header)

    def test_probe_decodes_the_declared_bit_fields(self):
        self.assertIn("((raw >> 16) & 0xFFFFu) == kIdMagic", self.header)
        self.assertIn("((raw >> 8) & 0xFFu)", self.header)
        self.assertIn("(raw & 0xFFu)", self.header)

    def test_probe_reads_at_the_declared_offset(self):
        self.assertIn("kIdOffset   = 0x00;", self.header)
        self.assertIn("read_word(base, kIdOffset)", self.header)

    def test_bind_dispatches_on_the_manifest_rules(self):
        self.assertIn("if (v.major == 1)", self.header)
        self.assertIn("std::in_place_type<acme::PwmCtrlV1>", self.header)
        self.assertIn("if (v.major == 2)", self.header)
        self.assertIn("std::in_place_type<acme::PwmCtrlV2>", self.header)

    def test_records_what_the_build_configured_for(self):
        self.assertIn('kBuiltFor   = "1.2";', self.header)
        self.assertIn('kDriverDbVersion = "1.2.0";', self.header)

    def test_header_is_self_contained(self):
        for include in ("<cstdint>", "<optional>", "<variant>"):
            self.assertIn("#include %s" % include, self.header)
        self.assertIn("#ifndef IPMAN_MAPS_HPP", self.header)
        self.assertIn("#endif  /* IPMAN_MAPS_HPP */", self.header)

    def test_no_maps_still_produces_a_usable_header(self):
        header = mapgen.generate([{"status": "no-manifest", "maps": []}])
        self.assertIn("#ifndef IPMAN_MAPS_HPP", header)
        self.assertIn("struct Probe", header)
        self.assertNotIn("std::variant<", header)


class TestMapCollection(unittest.TestCase):
    def _record(self, target, maps, id_register=None):
        return {"status": "ok", "ip": "acme.com:user:pwm_ctrl",
                "ip_name": "pwm_ctrl", "ip_version": "1.2", "target": target,
                "id_register": id_register or dmod.normalise_id_register(ID_REGISTER),
                "maps": maps}

    def test_maps_from_two_driver_packages_merge(self):
        # The same IP at two hardware versions resolves to two driver packages;
        # both contribute alternatives to one union.
        groups = mapgen.collect([
            self._record("ipdrv_pwm_ctrl_v1_2",
                         [{"match": "1.*", "type": "acme::V1", "header": "v1.hpp"}]),
            self._record("ipdrv_pwm_ctrl_v2_0",
                         [{"match": "2.*", "type": "acme::V2", "header": "v2.hpp"}]),
        ])
        self.assertEqual(len(groups), 1)
        self.assertEqual([m["type"] for m in groups[0]["maps"]],
                         ["acme::V1", "acme::V2"])
        self.assertEqual(len(groups[0]["drivers"]), 2)

    def test_duplicate_map_types_are_not_repeated(self):
        same = [{"match": "1.*", "type": "acme::V1", "header": "v1.hpp"}]
        groups = mapgen.collect([self._record("a", same), self._record("b", same)])
        self.assertEqual(len(groups[0]["maps"]), 1)

    def test_disagreeing_id_registers_are_rejected(self):
        other = dmod.normalise_id_register(dict(ID_REGISTER, offset="0x10"))
        with self.assertRaises(IpmanError) as ctx:
            mapgen.collect([
                self._record("a", [{"match": "1.*", "type": "acme::V1",
                                    "header": "v1.hpp"}]),
                self._record("b", [{"match": "2.*", "type": "acme::V2",
                                    "header": "v2.hpp"}], id_register=other),
            ])
        self.assertIn("disagree about the ID register", str(ctx.exception))

    def test_records_without_maps_are_skipped(self):
        self.assertEqual(mapgen.collect([{"status": "ok", "maps": []}]), [])
        self.assertEqual(mapgen.collect([{"status": "no-manifest", "maps": []}]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
