from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from term_registry import RegistryError, database_summary, import_bundle, resolve_name  # noqa: E402


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def materialize_evidence(root: Path, bundle: dict) -> None:
    entities = {row["entity_key"]: row for row in bundle["entities"]}
    for source in bundle["sources"]:
        entries = []
        for row in bundle["names"]:
            if row.get("source_key") != source["source_key"]:
                continue
            entity = entities[row["entity_key"]]
            entries.append({
                "record_kind": "name", "entry_locator": row["entry_locator"],
                "product": "warcraft_iii", "entity_key": row["entity_key"],
                "scope": entity["scope"], "evidence_status": row["evidence_status"],
                "object_type": entity["object_type"], "rawcode": entity.get("rawcode"),
                "stable_key": entity["stable_key"], "source_locale": row["source_locale"],
                "source_name": row["source_name"], "target_locale": row["target_locale"],
                "target_name": row["target_name"], "client_version": row.get("client_version"),
                "distribution": row["distribution"], "name_role": row.get("name_role", "canonical"),
                "level": row.get("level"), "form": row.get("form"),
            })
        for row in bundle["aliases"]:
            if row.get("source_key") != source["source_key"]:
                continue
            entity = entities[row["entity_key"]]
            entries.append({
                "record_kind": "alias", "entry_locator": row["entry_locator"],
                "product": "warcraft_iii", "entity_key": row["entity_key"],
                "scope": entity["scope"], "evidence_status": row["evidence_status"],
                "object_type": entity["object_type"], "rawcode": entity.get("rawcode"),
                "stable_key": entity["stable_key"], "locale": row["locale"],
                "alias": row["alias"], "alias_kind": row["alias_kind"],
                "client_version": row.get("client_version"), "distribution": row.get("distribution"),
            })
        source_identity = {key: source.get(key) for key in ("source_key", "product", "source_kind", "client_version", "distribution", "locale")}
        payload = json.dumps({"schema_version": 1, "source": source_identity, "entries": entries}, ensure_ascii=False, sort_keys=True).encode()
        (root / source["locator"]).write_bytes(payload)
        source["sha256"] = digest(payload)


class TermRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db = self.root / "terms.sqlite"
        (self.root / "client-en.txt").write_bytes(b"fixture-en")
        (self.root / "client-zh.txt").write_bytes(b"fixture-zh")
        (self.root / "client-zh-2.txt").write_bytes(b"fixture-zh-2")
        (self.root / "client-zhtw.txt").write_bytes(b"fixture-zhtw")
        (self.root / "map.w3a").write_bytes(b"fixture-map")
        self.bundle = {
            "schema_version": 1,
            "sources": [
                {
                    "source_key": "client-zh-2",
                    "product": "warcraft_iii",
                    "source_kind": "extracted_client_string",
                    "locator": "client-zh-2.txt",
                    "sha256": digest(b"fixture-zh-2"),
                    "client_version": "2.0.0",
                    "distribution": "reforged",
                    "locale": "zh-CN",
                },
                {
                    "source_key": "client-zhtw",
                    "product": "warcraft_iii",
                    "source_kind": "extracted_client_string",
                    "locator": "client-zhtw.txt",
                    "sha256": digest(b"fixture-zhtw"),
                    "client_version": "1.31.1",
                    "distribution": "classic",
                    "locale": "zh-TW",
                },
                {
                    "source_key": "client-en",
                    "product": "warcraft_iii",
                    "source_kind": "extracted_client_string",
                    "locator": "client-en.txt",
                    "sha256": digest(b"fixture-en"),
                    "client_version": "1.31.1",
                    "distribution": "classic",
                    "locale": "en-US",
                },
                {
                    "source_key": "client-zh",
                    "product": "warcraft_iii",
                    "source_kind": "extracted_client_string",
                    "locator": "client-zh.txt",
                    "sha256": digest(b"fixture-zh"),
                    "client_version": "1.31.1",
                    "distribution": "classic",
                    "locale": "zh-CN",
                },
                {
                    "source_key": "campaign-map",
                    "product": "warcraft_iii",
                    "source_kind": "campaign_term_decision",
                    "locator": "map.w3a",
                    "sha256": digest(b"fixture-map"),
                    "client_version": "1.31.1",
                    "distribution": "classic",
                    "locale": "zh-CN",
                },
            ],
            "entities": [
                {
                    "entity_key": "global:ability:A000",
                    "scope": {"kind": "global"},
                    "object_type": "ability",
                    "rawcode": "A000",
                    "stable_key": "A000",
                },
                {
                    "entity_key": "campaign:c/map:m:ability:A000",
                    "scope": {"kind": "map", "campaign": "c", "map": "m"},
                    "object_type": "ability",
                    "rawcode": "A000",
                    "stable_key": "A000",
                    "inherits_entity_key": "global:ability:A000",
                },
                {
                    "entity_key": "campaign:c/map:m:ability:A010",
                    "scope": {"kind": "map", "campaign": "c", "map": "m"},
                    "object_type": "ability",
                    "rawcode": "A010",
                    "stable_key": "A010",
                    "inherits_entity_key": "global:ability:A000",
                },
            ],
            "names": [
                {
                    "entity_key": "global:ability:A000",
                    "source_locale": "en-US",
                    "source_name": "Fixture Storm",
                    "target_locale": "zh-CN",
                    "target_name": "夹具风暴",
                    "client_version": "1.31.1",
                    "distribution": "classic",
                    "evidence_status": "official_reference",
                    "source_key": "client-zh",
                    "entry_locator": "FixtureStorm.Name",
                    "name_role": "canonical",
                },
                {
                    "entity_key": "global:ability:A000",
                    "source_locale": "en-US",
                    "source_name": "Fixture Storm",
                    "target_locale": "zh-CN",
                    "target_name": "重制夹具风暴",
                    "client_version": "2.0.0",
                    "distribution": "reforged",
                    "evidence_status": "official_reference",
                    "source_key": "client-zh-2",
                    "entry_locator": "FixtureStorm.Name",
                    "name_role": "canonical",
                },
                {
                    "entity_key": "global:ability:A000",
                    "source_locale": "en-US",
                    "source_name": "Fixture Storm",
                    "target_locale": "zh-TW",
                    "target_name": "測試風暴",
                    "client_version": "1.31.1",
                    "distribution": "classic",
                    "evidence_status": "official_reference",
                    "source_key": "client-zhtw",
                    "entry_locator": "FixtureStorm.Name",
                    "name_role": "canonical",
                },
                {
                    "entity_key": "campaign:c/map:m:ability:A000",
                    "source_locale": "en-US",
                    "source_name": "Author Storm",
                    "target_locale": "zh-CN",
                    "target_name": "作者风暴",
                    "client_version": "1.31.1",
                    "distribution": "classic",
                    "evidence_status": "campaign_override",
                    "source_key": "campaign-map",
                    "entry_locator": "decisions/A000/button",
                    "name_role": "canonical",
                },
            ],
            "aliases": [
                {
                    "entity_key": "campaign:c/map:m:ability:A000",
                    "locale": "zh-CN",
                    "alias": "风暴别称",
                    "alias_kind": "author_intended",
                    "evidence_status": "campaign_override",
                    "client_version": "1.31.1",
                    "distribution": "classic",
                    "source_key": "campaign-map",
                    "entry_locator": "decisions/A000/alias",
                }
            ],
        }
        materialize_evidence(self.root, self.bundle)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_bundle(self, value: dict, name: str = "bundle.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def load(self) -> None:
        materialize_evidence(self.root, self.bundle)
        import_bundle(self.db, self.write_bundle(self.bundle), self.root)

    def test_import_and_exact_query(self) -> None:
        self.load()
        result = resolve_name(
            self.db,
            object_type="ability",
            rawcode="A000",
            target_locale="zh-CN",
            client_version="1.31.1",
            distribution="classic",
        )
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected"]["target_name"], "夹具风暴")
        self.assertEqual(result["selected"]["evidence_status"], "official_reference")

    def test_canonical_extracted_evidence_format_imports_directly(self) -> None:
        evidence_path = self.root / "canonical-extracted.json"
        entry = {
            "record_kind": "name", "entry_locator": "Objects/A100/Name",
            "product": "warcraft_iii", "entity_key": "global:ability:A100",
            "scope": {"kind": "global"}, "object_type": "ability", "rawcode": "A100",
            "stable_key": "A100", "inherits_entity_key": None,
            "source_locale": "en-US", "source_name": "Fixture Bolt",
            "target_locale": "zh-CN", "target_name": "夹具之箭",
            "client_version": "1.31.1", "distribution": "classic",
            "name_role": "canonical", "level": None, "form": None,
            "evidence_status": "official_reference",
        }
        payload = {
            "schema_version": 1,
            "source": {
                "source_key": "fixture-canonical", "product": "warcraft_iii",
                "source_kind": "extracted_client_string", "client_version": "1.31.1",
                "distribution": "classic", "locale": "zh-CN",
                "notes": "Synthetic normalized extraction fixture; not authoritative data.",
            },
            "entries": [entry],
        }
        evidence_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        imported_db = self.root / "canonical.sqlite"
        completed = subprocess.run([
            sys.executable, str(ROOT / "scripts" / "term_registry.py"), "import-evidence",
            "--db", str(imported_db), "--input", str(evidence_path),
            "--source-root", str(self.root),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result, {"sources": 1, "entities": 1, "names": 1, "aliases": 0})
        selected = resolve_name(
            imported_db, object_type="ability", rawcode="A100", source_locale="en-US",
            target_locale="zh-CN", client_version="1.31.1", distribution="classic",
        )
        self.assertEqual(selected["selected"]["target_name"], "夹具之箭")

    def test_version_and_region_are_not_silently_fallbacked(self) -> None:
        self.load()
        missing_version = resolve_name(
            self.db, object_type="ability", rawcode="A000", target_locale="zh-CN",
            client_version=None, distribution="classic",
        )
        self.assertEqual(missing_version["status"], "ambiguous")
        self.assertEqual(missing_version["reason"], "client_version_and_distribution_required")
        unavailable_version = resolve_name(
            self.db, object_type="ability", rawcode="A000", target_locale="zh-CN",
            client_version="1.36.0", distribution="reforged",
        )
        self.assertEqual(unavailable_version["status"], "ambiguous")
        self.assertEqual(unavailable_version["reason"], "no_exact_version_distribution_evidence")
        wrong_region = resolve_name(
            self.db, object_type="ability", rawcode="A000", target_locale="zh-HK",
            client_version="1.31.1", distribution="classic",
        )
        self.assertEqual(wrong_region["status"], "ambiguous")
        self.assertEqual(wrong_region["reason"], "no_exact_target_locale")
        self.assertEqual({row["target_locale"] for row in wrong_region["candidates"]}, {"zh-CN", "zh-TW"})

    def test_query_cli_exit_codes_are_stable(self) -> None:
        self.load()
        base = [
            sys.executable, str(ROOT / "scripts" / "term_registry.py"), "query",
            "--db", str(self.db), "--object-type", "ability", "--rawcode", "A000",
            "--source-locale", "en-US", "--target-locale", "zh-CN", "--distribution", "classic",
        ]
        selected = subprocess.run(base + ["--client-version", "1.31.1"], capture_output=True, text=True, check=False)
        ambiguous = subprocess.run(base, capture_output=True, text=True, check=False)
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual(ambiguous.returncode, 2, ambiguous.stderr)

    def test_map_scoped_override_beats_global_for_that_map_only(self) -> None:
        self.load()
        result = resolve_name(
            self.db, object_type="ability", rawcode="A000", campaign="c", map_key="m",
            target_locale="zh-CN", client_version="1.31.1", distribution="classic",
        )
        self.assertEqual(result["selected"]["target_name"], "作者风暴")
        self.assertEqual(result["selected"]["evidence_status"], "campaign_override")
        other_map = resolve_name(
            self.db, object_type="ability", rawcode="A000", campaign="c", map_key="other",
            target_locale="zh-CN", client_version="1.31.1", distribution="classic",
        )
        self.assertEqual(other_map["selected"]["target_name"], "夹具风暴")

    def test_exact_official_name_beats_override_on_the_same_entity(self) -> None:
        self.bundle["names"].append({
            "entity_key": "campaign:c/map:m:ability:A000",
            "source_locale": "en-US", "source_name": "Author Storm",
            "target_locale": "zh-CN", "target_name": "官方实体名",
            "client_version": "1.31.1", "distribution": "classic",
            "evidence_status": "official_reference", "source_key": "client-zh",
            "entry_locator": "CustomObjects/A000/Name", "name_role": "canonical",
        })
        self.load()
        result = resolve_name(
            self.db, object_type="ability", rawcode="A000", campaign="c", map_key="m",
            source_locale="en-US", target_locale="zh-CN",
            client_version="1.31.1", distribution="classic",
        )
        self.assertEqual(result["selected"]["target_name"], "官方实体名")
        self.assertEqual(result["selected"]["evidence_status"], "official_reference")

    def test_import_records_inheritance_alias_and_source_inventory(self) -> None:
        self.load()
        summary = database_summary(self.db)
        self.assertEqual(summary["sources"], 5)
        self.assertEqual(summary["entities"], 3)
        self.assertEqual(summary["aliases"], 1)
        self.assertEqual(summary["evidence"]["campaign_override"], 1)

    def test_name_can_be_inherited_from_a_version_matched_base_entity(self) -> None:
        self.load()
        result = resolve_name(
            self.db, object_type="ability", rawcode="A010", campaign="c", map_key="m",
            target_locale="zh-CN", client_version="1.31.1", distribution="classic",
        )
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected"]["target_name"], "夹具风暴")
        self.assertTrue(result["selected"]["inherited"])
        self.assertEqual(result["selected"]["resolved_for_entity_key"], "campaign:c/map:m:ability:A010")

    def test_conflicting_canonical_name_is_rejected_transactionally(self) -> None:
        self.load()
        conflict_entry = {
            "record_kind": "name", "entry_locator": "FixtureStorm.Conflict",
            "product": "warcraft_iii", "entity_key": "global:ability:A000",
            "scope": {"kind": "global"}, "evidence_status": "official_reference",
            "object_type": "ability", "rawcode": "A000", "stable_key": "A000",
            "source_locale": "en-US", "source_name": "Fixture Storm",
            "target_locale": "zh-CN", "target_name": "冲突译名",
            "client_version": "1.31.1", "distribution": "classic",
            "name_role": "canonical", "level": None, "form": None,
        }
        conflict_source = {
            "source_key": "client-zh-conflict", "product": "warcraft_iii",
            "source_kind": "extracted_client_string", "client_version": "1.31.1",
            "distribution": "classic", "locale": "zh-CN",
        }
        conflict_payload = json.dumps({"schema_version": 1, "source": conflict_source, "entries": [conflict_entry]}, ensure_ascii=False, sort_keys=True).encode()
        (self.root / "conflict-evidence.json").write_bytes(conflict_payload)
        conflict = {
            "schema_version": 1,
            "sources": [{
                "source_key": "client-zh-conflict", "product": "warcraft_iii",
                "source_kind": "extracted_client_string", "locator": "conflict-evidence.json",
                "sha256": digest(conflict_payload), "client_version": "1.31.1",
                "distribution": "classic", "locale": "zh-CN",
            }],
            "entities": [],
            "names": [{
                "entity_key": "global:ability:A000",
                "source_locale": "en-US",
                "source_name": "Fixture Storm",
                "target_locale": "zh-CN",
                "target_name": "冲突译名",
                "client_version": "1.31.1",
                "distribution": "classic",
                "evidence_status": "official_reference",
                "source_key": "client-zh-conflict",
                "entry_locator": "FixtureStorm.Conflict",
                "name_role": "canonical",
            }],
            "aliases": [],
        }
        with self.assertRaisesRegex(RegistryError, "conflicting canonical targets"):
            import_bundle(self.db, self.write_bundle(conflict, "conflict.json"), self.root)
        self.assertEqual(database_summary(self.db)["names"], 4)

    def test_strong_evidence_locator_must_match_entity_and_names(self) -> None:
        broken = json.loads(json.dumps(self.bundle))
        broken["names"][0]["target_name"] = "证据文件里不存在的名称"
        with self.assertRaisesRegex(RegistryError, "evidence entry content mismatch"):
            import_bundle(self.db, self.write_bundle(broken, "false-evidence.json"), self.root)

    def test_bundle_cannot_relabel_evidence_source_identity(self) -> None:
        broken = json.loads(json.dumps(self.bundle))
        source = next(row for row in broken["sources"] if row["source_key"] == "client-zh")
        original = json.loads((self.root / source["locator"]).read_text(encoding="utf-8"))
        original["source"]["source_kind"] = "verified_community_excerpt"
        payload = json.dumps(original, ensure_ascii=False, sort_keys=True).encode()
        source["locator"] = "relabelled-source.json"
        source["sha256"] = digest(payload)
        (self.root / source["locator"]).write_bytes(payload)
        with self.assertRaisesRegex(RegistryError, "evidence source identity mismatch"):
            import_bundle(self.db, self.write_bundle(broken, "relabelled-bundle.json"), self.root)

    def test_strong_evidence_without_source_is_rejected(self) -> None:
        broken = json.loads(json.dumps(self.bundle))
        broken["names"][0].pop("source_key")
        with self.assertRaisesRegex(RegistryError, "source_key: required"):
            import_bundle(self.db, self.write_bundle(broken), self.root)

    def test_source_hash_is_checked_when_source_root_is_supplied(self) -> None:
        broken = json.loads(json.dumps(self.bundle))
        broken["sources"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(RegistryError, "hash mismatch"):
            import_bundle(self.db, self.write_bundle(broken), self.root)

    def test_non_wc3_product_is_rejected(self) -> None:
        broken = json.loads(json.dumps(self.bundle))
        broken["sources"][0]["product"] = "world_of_warcraft"
        with self.assertRaisesRegex(RegistryError, "WoW"):
            import_bundle(self.db, self.write_bundle(broken), self.root)

    def test_cross_map_inheritance_is_rejected(self) -> None:
        broken = json.loads(json.dumps(self.bundle))
        broken["entities"].extend([
            {
                "entity_key": "campaign:c/map:other:ability:A020",
                "scope": {"kind": "map", "campaign": "c", "map": "other"},
                "object_type": "ability", "rawcode": "A020", "stable_key": "A020",
            },
            {
                "entity_key": "campaign:c/map:m:ability:A021",
                "scope": {"kind": "map", "campaign": "c", "map": "m"},
                "object_type": "ability", "rawcode": "A021", "stable_key": "A021",
                "inherits_entity_key": "campaign:c/map:other:ability:A020",
            },
        ])
        with self.assertRaisesRegex(RegistryError, "may not cross campaign/map scope"):
            import_bundle(self.db, self.write_bundle(broken), self.root)

    def test_importing_sources_requires_source_root(self) -> None:
        with self.assertRaisesRegex(RegistryError, "source-root is required"):
            import_bundle(self.db, self.write_bundle(self.bundle))

    def test_strong_evidence_source_kind_is_enforced(self) -> None:
        broken = json.loads(json.dumps(self.bundle))
        broken["sources"][3]["source_kind"] = "verified_community_excerpt"
        with self.assertRaisesRegex(RegistryError, "incompatible with source_kind"):
            import_bundle(self.db, self.write_bundle(broken), self.root)

    def test_webpage_evidence_cannot_claim_a_rawcode(self) -> None:
        broken = json.loads(json.dumps(self.bundle))
        broken["sources"][3]["source_kind"] = "blizzard_official_excerpt"
        with self.assertRaisesRegex(RegistryError, "cannot establish a rawcode"):
            import_bundle(self.db, self.write_bundle(broken), self.root)


if __name__ == "__main__":
    unittest.main()
