from __future__ import annotations

import hashlib
import json
import subprocess
import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from entity_term_audit import audit_manifest, read_manifest  # noqa: E402
from term_registry import import_bundle  # noqa: E402
from object_link_inventory import build_inventory, validate_entity_coverage  # noqa: E402


def write_object_file(path: Path, rawcode: bytes, mods: list[tuple[bytes, str]], has_levels: bool) -> None:
    data = bytearray(struct.pack("<i", 2))
    for table_index in range(2):
        data += struct.pack("<i", 1 if table_index == 0 else 0)
        if table_index != 0:
            continue
        data += rawcode + b"\0\0\0\0" + struct.pack("<i", len(mods))
        for field, value in mods:
            data += field + struct.pack("<i", 3)
            if has_levels:
                data += struct.pack("<ii", 0, 0)
            data += value.encode("utf-8") + b"\0" + rawcode
    path.write_bytes(bytes(data))


def materialize_registry_evidence(root: Path, bundle: dict) -> None:
    entities = {row["entity_key"]: row for row in bundle["entities"]}
    for source in bundle["sources"]:
        entries = []
        for row in bundle["names"]:
            if row["source_key"] != source["source_key"]:
                continue
            entity = entities[row["entity_key"]]
            entries.append({
                "record_kind": "name", "entry_locator": row["entry_locator"],
                "product": "warcraft_iii", "entity_key": row["entity_key"],
                "scope": entity["scope"], "evidence_status": row["evidence_status"],
                "object_type": entity["object_type"], "rawcode": entity.get("rawcode"),
                "stable_key": entity["stable_key"], "source_locale": row["source_locale"],
                "source_name": row["source_name"], "target_locale": row["target_locale"],
                "target_name": row["target_name"], "client_version": row["client_version"],
                "distribution": row["distribution"], "name_role": row.get("name_role", "canonical"),
                "level": row.get("level"), "form": row.get("form"),
            })
        for row in bundle["aliases"]:
            if row["source_key"] != source["source_key"]:
                continue
            entity = entities[row["entity_key"]]
            entries.append({
                "record_kind": "alias", "entry_locator": row["entry_locator"],
                "product": "warcraft_iii", "entity_key": row["entity_key"],
                "scope": entity["scope"], "evidence_status": row["evidence_status"],
                "object_type": entity["object_type"], "rawcode": entity.get("rawcode"),
                "stable_key": entity["stable_key"], "locale": row["locale"],
                "alias": row["alias"], "alias_kind": row["alias_kind"],
                "client_version": row["client_version"], "distribution": row["distribution"],
            })
        source_identity = {key: source[key] for key in ("source_key", "product", "source_kind", "client_version", "distribution", "locale")}
        payload = json.dumps({"schema_version": 1, "source": source_identity, "entries": entries}, ensure_ascii=False, sort_keys=True).encode()
        (root / source["locator"]).write_bytes(payload)
        source["sha256"] = hashlib.sha256(payload).hexdigest()


class EntityTermAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db = self.root / "terms.sqlite"
        base_evidence = {
            "schema_version": 1,
            "notes": "Synthetic base-data fixture; not authoritative data.",
            "entries": [{
                "record_kind": "ability_list",
                "entry_locator": "base/n001/uabi",
                "owner_rawcode": "n001",
                "field": "uabi",
                "rawcodes": ["A003"],
            }],
        }
        evidence = json.dumps(base_evidence, ensure_ascii=False, sort_keys=True).encode()
        (self.root / "map-evidence.json").write_bytes(evidence)
        (self.root / "m").mkdir()
        write_object_file(self.root / "m" / "war3map.w3u", b"n001", [(b"uabi", "A001"), (b"utub", "TRIGSTR_20")], False)
        write_object_file(self.root / "m" / "war3map.w3a", b"A001", [(b"atp1", "TRIGSTR_10")], True)
        (self.root / "m" / "war3map.wts").write_text(
            "STRING 10\n{\n|cffffcc00烈|r焰风暴\n}\n\n"
            "STRING 20\n{\n可施放烈焰风暴，对附近敌人造成伤害。UnrelatedWord 不属于技能提及。\n}\n",
            encoding="utf-8",
        )
        entities = [
            {
                "entity_key": "map:m:ability:A001",
                "scope": {"kind": "map", "campaign": "c", "map": "m"},
                "object_type": "ability", "rawcode": "A001", "stable_key": "A001",
            },
            {
                "entity_key": "map:m2:ability:A001",
                "scope": {"kind": "map", "campaign": "c", "map": "m2"},
                "object_type": "ability", "rawcode": "A001", "stable_key": "A001",
            },
            {
                "entity_key": "map:m:ability:A002",
                "scope": {"kind": "map", "campaign": "c", "map": "m"},
                "object_type": "ability", "rawcode": "A002", "stable_key": "A002",
            },
            {
                "entity_key": "map:m:ability:A004",
                "scope": {"kind": "map", "campaign": "c", "map": "m"},
                "object_type": "ability", "rawcode": "A004", "stable_key": "A004",
            },
            {
                "entity_key": "global:ability:Abas",
                "scope": {"kind": "global"},
                "object_type": "ability", "rawcode": "Abas", "stable_key": "Abas",
            },
            {
                "entity_key": "map:m:ability:A003",
                "scope": {"kind": "map", "campaign": "c", "map": "m"},
                "object_type": "ability", "rawcode": "A003", "stable_key": "A003",
                "inherits_entity_key": "global:ability:Abas",
            },
        ]
        names = []

        def add(entity: str, role: str, target: str, level=None, form=None) -> None:
            is_map = entity.startswith("map:")
            names.append({
                "entity_key": entity,
                "source_locale": "en-US",
                "source_name": "Fixture Ability",
                "target_locale": "zh-CN",
                "target_name": target,
                "client_version": "1.31.1",
                "distribution": "classic",
                "evidence_status": "campaign_override" if is_map else "verified_community_reference",
                "source_key": "fixture-source" if is_map else "fixture-community",
                "entry_locator": f"decisions/{entity}/{role}/{level}/{form}",
                "name_role": role,
                "level": level,
                "form": form,
            })

        for entity, target in (
            ("map:m:ability:A001", "烈焰风暴"),
            ("map:m2:ability:A001", "冰晶风暴"),
            ("map:m:ability:A002", "冰霜新星"),
            ("map:m:ability:A004", "烈焰风暴"),
            ("global:ability:Abas", "基础怒吼"),
            ("map:m:ability:A003", "雷霆怒吼"),
        ):
            add(entity, "canonical", target)
            add(entity, "button", target)
        add("map:m:ability:A003", "learn", "学习雷霆怒吼")
        add("map:m:ability:A003", "button", "熊形态怒吼（2级）", level=2, form="bear")
        bundle = {
            "schema_version": 1,
            "sources": [
                {
                    "source_key": "fixture-source", "product": "warcraft_iii",
                    "source_kind": "campaign_term_decision", "locator": "fixture-source.json",
                    "sha256": hashlib.sha256(evidence).hexdigest(), "client_version": "1.31.1",
                    "distribution": "classic", "locale": "zh-CN",
                    "notes": "Synthetic campaign decision fixture; not authoritative data.",
                },
                {
                    "source_key": "fixture-community", "product": "warcraft_iii",
                    "source_kind": "verified_community_excerpt", "locator": "fixture-community.json",
                    "sha256": hashlib.sha256(evidence).hexdigest(), "client_version": "1.31.1",
                    "distribution": "classic", "locale": "zh-CN",
                    "notes": "Synthetic community fixture; not authoritative data.",
                },
            ],
            "entities": entities,
            "names": names,
            "aliases": [{
                "entity_key": "map:m:ability:A001", "locale": "zh-CN", "alias": "火焰雨",
                "alias_kind": "author_intended", "evidence_status": "campaign_override",
                "entry_locator": "decisions/A001/alias", "client_version": "1.31.1",
                "distribution": "classic", "source_key": "fixture-source",
            }],
        }
        materialize_registry_evidence(self.root, bundle)
        bundle_path = self.root / "bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        import_bundle(self.db, bundle_path, self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def manifest(
        self,
        *,
        map_key: str = "m",
        ability_id: str = "ability-a001",
        rawcode: str = "A001",
        display: str = "|cffffcc00烈|r焰风暴",
        description: str = "可施放烈焰风暴，对附近敌人造成伤害。UnrelatedWord 不属于技能提及。",
        observed: str = "烈焰风暴",
        role: str = "button",
        level=None,
        form=None,
        direct: bool = False,
    ) -> dict:
        scope = {"campaign": "c", "map": map_key}
        name_ref = (
            {"kind": "direct", "value": display, "record_key": f"{map_key}:direct:name", "source_location": f"{map_key}/war3map.w3a:A001:anam"}
            if direct else {"kind": "wts", "key": f"{map_key}:wts:10"}
        )
        description_ref = (
            {"kind": "direct", "value": description, "record_key": f"{map_key}:direct:description", "source_location": f"{map_key}/war3map.w3u:n001:utub"}
            if direct else {"kind": "wts", "key": f"{map_key}:wts:20"}
        )
        texts = [] if direct else [
            {"key": f"{map_key}:wts:10", "record_key": f"{map_key}:wts:10", "storage_ref": "TRIGSTR_10", "text": display, "source_location": f"{map_key}/war3map.wts:STRING 10"},
            {"key": f"{map_key}:wts:20", "record_key": f"{map_key}:wts:20", "storage_ref": "TRIGSTR_20", "text": description, "source_location": f"{map_key}/war3map.wts:STRING 20"},
        ]
        evidence_files = [{"path": "map-evidence.json", "sha256": hashlib.sha256((self.root / "map-evidence.json").read_bytes()).hexdigest()}]
        fingerprint = hashlib.sha256(
            json.dumps(evidence_files, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        start = description.index(observed)
        mention_key = f"{map_key}:n001:description:mention:0"
        return {
            "schema_version": 1,
            "source_fingerprint": fingerprint,
            "evidence_files": evidence_files,
            "context": {"campaign": "c", "source_locale": "en-US", "target_locale": "zh-CN", "client_version": "1.31.1", "distribution": "classic"},
            "texts": texts,
            "entities": [
                {
                    "id": f"unit-{map_key}", "scope": scope, "object_type": "unit",
                    "rawcode": "n001", "stable_key": "n001", "source_location": f"{map_key}/war3map.w3u:n001",
                    "inventory_key": "m/war3map.w3u:table:0:object:0",
                    "ability_scan": {
                        "status": "complete",
                        "inventory_keys": ["m/war3map.w3u:table:0:object:0:mod:0"],
                        "bindings": [{
                            "key": f"{map_key}:n001:uabi:A001", "field": "uabi", "resolution": "direct",
                            "ability_entity_id": ability_id, "source_location": f"{map_key}/war3map.w3u:n001:uabi",
                            "inventory_key": "m/war3map.w3u:table:0:object:0:mod:0",
                        }],
                    },
                    "description_review": {
                        "status": "complete",
                        "source_locations": [f"{map_key}/war3map.w3u:n001:utub"],
                        "surfaces": [{"inventory_key": "m/war3map.w3u:table:0:object:0:mod:1", "text": description_ref}],
                        "mention_keys": [mention_key],
                    },
                },
                {
                    "id": ability_id, "scope": scope, "object_type": "ability",
                    "rawcode": rawcode, "stable_key": rawcode, "source_location": f"{map_key}/war3map.w3a:{rawcode}",
                    "inventory_key": "m/war3map.w3a:table:0:object:0",
                    "display_names": [{"role": role, "level": level, "form": form, "data_pointer": 0, "source_name": "Fixture Ability", "inventory_key": "m/war3map.w3a:table:0:object:0:mod:0", "text": name_ref}],
                },
            ],
            "mentions": [{
                "key": mention_key, "status": "resolved",
                "owner_entity_id": f"unit-{map_key}", "ability_entity_id": ability_id,
                "expected_role": role, "level": level, "form": form, "observed_name": observed,
                "span": [start, start + len(observed)],
                "description": description_ref, "source_location": f"{map_key}/war3map.w3u:n001:utub",
            }],
            "aliases": [],
            "exceptions": [],
        }

    def codes(self, manifest: dict) -> set[str]:
        return {item["code"] for item in audit_manifest(manifest, self.db)["issues"]}

    def test_subtle_description_name_difference_fails(self) -> None:
        value = self.manifest(description="可施放烈焰风爆。", observed="烈焰风爆")
        report = audit_manifest(value, self.db)
        self.assertFalse(report["passed"])
        mismatch = next(item for item in report["issues"] if item["code"] == "mention_name_mismatch")
        self.assertEqual(mismatch["expected_name"], "烈焰风暴")
        self.assertEqual(mismatch["actual_name"], "烈焰风爆")

    def test_description_mention_cannot_fall_back_to_canonical_role(self) -> None:
        value = self.manifest(role="canonical")
        self.assertIn("mention_role_not_skill_bar", self.codes(value))

    def test_corrected_name_and_colored_hotkey_pass(self) -> None:
        report = audit_manifest(self.manifest(), self.db)
        self.assertTrue(report["passed"], report["issues"])

    def test_direct_text_reference_passes(self) -> None:
        report = audit_manifest(self.manifest(direct=True), self.db)
        self.assertTrue(report["passed"], report["issues"])

    def test_same_rawcode_in_another_map_resolves_separately(self) -> None:
        value = self.manifest(map_key="m2", display="冰晶风暴", description="可施放冰晶风暴。", observed="冰晶风暴")
        report = audit_manifest(value, self.db)
        self.assertTrue(report["passed"], report["issues"])

    def test_same_source_like_name_on_different_entity_is_not_conflated(self) -> None:
        value = self.manifest(ability_id="ability-a002", rawcode="A002", display="冰霜新星", description="可施放冰霜新星。", observed="冰霜新星")
        report = audit_manifest(value, self.db)
        self.assertTrue(report["passed"], report["issues"])

    def test_custom_inheritance_rename_passes_with_base_evidence(self) -> None:
        value = self.manifest(ability_id="ability-a003", rawcode="A003", display="雷霆怒吼", description="可施放雷霆怒吼。", observed="雷霆怒吼")
        ability = value["entities"][1]
        ability.update(inherits="global:ability:Abas", base_data_status="available")
        binding = value["entities"][0]["ability_scan"]["bindings"][0]
        binding.update(
            resolution="inherited", base_data_source="map-evidence.json",
            base_entry_locator="base/n001/uabi", inherited_rawcodes=["A003"],
        )
        report = audit_manifest(value, self.db)
        self.assertTrue(report["passed"], report["issues"])

    def test_missing_base_data_fails_closed(self) -> None:
        value = self.manifest(ability_id="ability-a003", rawcode="A003", display="雷霆怒吼", description="可施放雷霆怒吼。", observed="雷霆怒吼")
        value["entities"][1].update(inherits="global:ability:Abas", base_data_status="missing")
        value["entities"][0]["ability_scan"]["bindings"][0]["resolution"] = "inherited"
        self.assertIn("base_data_missing", self.codes(value))

    def test_inherited_binding_must_prove_target_rawcode(self) -> None:
        value = self.manifest(ability_id="ability-a003", rawcode="A003", display="雷霆怒吼", description="可施放雷霆怒吼。", observed="雷霆怒吼")
        value["entities"][1].update(inherits="global:ability:Abas", base_data_status="available")
        value["entities"][0]["ability_scan"]["bindings"][0].update(
            resolution="inherited", base_data_source="map-evidence.json",
            base_entry_locator="base/n001/uabi", inherited_rawcodes=["A999"],
        )
        self.assertIn("base_data_missing", self.codes(value))

    def test_loaded_inherited_binding_cross_checks_base_evidence_file(self) -> None:
        broken_base = {
            "schema_version": 1,
            "entries": [{
                "record_kind": "ability_list",
                "entry_locator": "base/n001/uabi",
                "owner_rawcode": "n001",
                "field": "uabi",
                "rawcodes": ["A004"],
            }],
        }
        (self.root / "map-evidence.json").write_text(json.dumps(broken_base, ensure_ascii=False), encoding="utf-8")
        value = self.manifest(ability_id="ability-a003", rawcode="A003", display="雷霆怒吼", description="可施放雷霆怒吼。", observed="雷霆怒吼")
        value["entities"][1].update(inherits="global:ability:Abas", base_data_status="available")
        value["entities"][0]["ability_scan"]["bindings"][0].update(
            resolution="inherited", base_data_source="map-evidence.json",
            base_entry_locator="base/n001/uabi", inherited_rawcodes=["A003"],
        )
        manifest_path = self.root / "inherited-manifest.json"
        manifest_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        loaded = read_manifest(manifest_path)
        self.assertIn("base_data_missing", {item["code"] for item in audit_manifest(loaded, self.db)["issues"]})

    def test_multilevel_form_and_learning_name(self) -> None:
        level = self.manifest(
            ability_id="ability-a003", rawcode="A003", role="button", level=2, form="bear",
            display="熊形态怒吼（2级）", description="获得熊形态怒吼（2级）。", observed="熊形态怒吼（2级）",
        )
        self.assertTrue(audit_manifest(level, self.db)["passed"])
        learn = self.manifest(
            ability_id="ability-a003", rawcode="A003", role="learn",
            display="学习雷霆怒吼", description="下一步：学习雷霆怒吼。", observed="学习雷霆怒吼",
        )
        self.assertTrue(audit_manifest(learn, self.db)["passed"])

    def test_unresolved_dynamic_reference_blocks_release(self) -> None:
        value = self.manifest()
        binding = value["entities"][0]["ability_scan"]["bindings"][0]
        binding.update(resolution="dynamic", ability_entity_id=None)
        self.assertIn("unresolved_ability_reference", self.codes(value))

    def test_explicit_author_alias_is_narrowly_accepted(self) -> None:
        value = self.manifest(description="可施放火焰雨。", observed="火焰雨")
        value["aliases"] = [{
            "entity_id": "ability-a001", "alias": "火焰雨", "reason": "作者在该段使用的正式别称",
            "source_location": "m/alias-review.json:1", "mention_keys": ["m:n001:description:mention:0"],
            "registry_source_key": "fixture-source",
        }]
        report = audit_manifest(value, self.db)
        self.assertTrue(report["passed"], report["issues"])

    def test_exact_reviewed_exception_is_applied_and_reported(self) -> None:
        value = self.manifest(description="作者界面有意写作烈焰风爆。", observed="烈焰风爆")
        value["exceptions"] = [{
            "key": "m:n001:description:mention:0",
            "code": "mention_name_mismatch",
            "expected_name": "烈焰风暴",
            "actual_name": "烈焰风爆",
            "reason": "有截图和作者说明证明这是该处有意的文字游戏",
            "source_location": "quality/exception-evidence.json:1",
            "evidence_path": "map-evidence.json",
        }]
        report = audit_manifest(value, self.db)
        self.assertTrue(report["passed"], report["issues"])
        self.assertEqual(len(report["applied_exceptions"]), 1)

    def test_missing_campaign_override_is_an_unresolved_decision(self) -> None:
        value = self.manifest(rawcode="A099", ability_id="ability-missing")
        self.assertIn("term_decision_unresolved", self.codes(value))

    def test_duplicate_and_wrong_binding_are_diagnosed(self) -> None:
        duplicate = self.manifest()
        duplicate["entities"][0]["ability_scan"]["bindings"].append(
            dict(duplicate["entities"][0]["ability_scan"]["bindings"][0])
        )
        codes = self.codes(duplicate)
        self.assertIn("duplicate_binding_key", codes)
        self.assertIn("duplicate_ability_binding", codes)
        wrong = self.manifest()
        wrong["entities"][0]["ability_scan"]["bindings"][0]["ability_entity_id"] = "missing"
        self.assertIn("wrong_ability_binding", self.codes(wrong))

    def test_unrelated_words_are_not_scanned_as_skill_mentions(self) -> None:
        report = audit_manifest(self.manifest(), self.db)
        self.assertFalse(any(item["code"] == "mention_name_mismatch" for item in report["issues"]))

        no_mention = self.manifest(description="该单位移动迅速；UnrelatedWord 不是技能名称。", observed="UnrelatedWord")
        no_mention["mentions"] = []
        no_mention["entities"][0]["description_review"]["mention_keys"] = []
        report = audit_manifest(no_mention, self.db)
        self.assertTrue(report["passed"], report["issues"])

    def test_omitting_a_subtle_name_variant_does_not_bypass_audit(self) -> None:
        value = self.manifest(description="可施放烈焰风爆。", observed="烈焰风爆")
        value["mentions"] = []
        value["entities"][0]["description_review"]["mention_keys"] = []
        report = audit_manifest(value, self.db)
        candidate = next(item for item in report["issues"] if item["code"] == "undeclared_potential_mention")
        self.assertEqual(candidate["expected_name"], "烈焰风暴")
        self.assertEqual(candidate["actual_name"], "烈焰风爆")

    def test_omitting_a_three_character_variant_does_not_bypass_audit(self) -> None:
        value = self.manifest(display="风暴锤", description="可施放风暴锥。", observed="风暴锥")
        value["mentions"] = []
        value["entities"][0]["description_review"]["mention_keys"] = []
        # Make this a fixture-only adjudication for the same entity.
        with __import__("sqlite3").connect(self.db) as connection:
            connection.execute("UPDATE names SET target_name='风暴锤' WHERE entity_key='map:m:ability:A001' AND name_role='canonical'")
        report = audit_manifest(value, self.db)
        self.assertTrue(any(item["code"] == "undeclared_potential_mention" for item in report["issues"]))

    def test_omitting_a_two_character_substitution_does_not_bypass_audit(self) -> None:
        value = self.manifest(display="闪烁", description="可使用闪耀。", observed="闪耀")
        value["mentions"] = []
        value["entities"][0]["description_review"]["mention_keys"] = []
        with __import__("sqlite3").connect(self.db) as connection:
            connection.execute("UPDATE names SET target_name='闪烁' WHERE entity_key='map:m:ability:A001' AND name_role='canonical'")
        report = audit_manifest(value, self.db)
        self.assertTrue(any(item["code"] == "undeclared_potential_mention" for item in report["issues"]))

    def test_observed_name_must_be_an_exact_span_not_a_substring(self) -> None:
        value = self.manifest(description="可施放超级烈焰风暴术。", observed="烈焰风暴")
        value["mentions"][0]["span"] = [3, 10]
        self.assertIn("mention_span_not_found", self.codes(value))

    def test_shared_wts_name_can_back_multiple_entities(self) -> None:
        value = self.manifest()
        value["entities"].append({
            "id": "ability-a004", "scope": {"campaign": "c", "map": "m"},
            "object_type": "ability", "rawcode": "A004", "stable_key": "A004",
            "source_location": "m/manifest:copy",
            "display_names": [{"role": "button", "source_name": "Fixture Ability", "text": {"kind": "wts", "key": "m:wts:10"}}],
        })
        report = audit_manifest(value, self.db)
        self.assertTrue(report["passed"], report["issues"])

    def test_cli_returns_nonzero_on_mismatch(self) -> None:
        manifest_path = self.root / "manifest.json"
        report_path = self.root / "report.json"
        manifest_path.write_text(json.dumps(self.manifest(description="施放烈焰风爆。", observed="烈焰风爆"), ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "entity_term_audit.py"), "--manifest", str(manifest_path), "--term-db", str(self.db), "--out", str(report_path)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertTrue(report_path.is_file())

    def test_cli_rejects_invalid_manifest_contract(self) -> None:
        manifest_path = self.root / "invalid-manifest.json"
        report_path = self.root / "invalid-report.json"
        value = self.manifest()
        value["context"].pop("client_version")
        manifest_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "entity_term_audit.py"), "--manifest", str(manifest_path), "--term-db", str(self.db), "--out", str(report_path)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(report_path.exists())

    def test_parsed_object_inventory_requires_exact_slot_coverage(self) -> None:
        inventory = build_inventory(self.root)
        value = self.manifest()
        self.assertEqual(validate_entity_coverage(value, inventory), [])
        value["entities"][0]["description_review"]["surfaces"] = []
        issues = validate_entity_coverage(value, inventory)
        self.assertTrue(any(item["code"] == "inventory_slot_coverage_mismatch" for item in issues))

    def test_parsed_object_inventory_rejects_false_text_and_partial_ability_list_links(self) -> None:
        inventory = build_inventory(self.root)
        wrong_text = self.manifest()
        wrong_text["texts"][1]["storage_ref"] = "TRIGSTR_999"
        self.assertTrue(any(item["code"] == "inventory_text_reference_mismatch" for item in validate_entity_coverage(wrong_text, inventory)))

        write_object_file(self.root / "m" / "war3map.w3u", b"n001", [(b"uabi", "A001,A002"), (b"utub", "TRIGSTR_20")], False)
        inventory = build_inventory(self.root)
        partial = self.manifest()
        issues = validate_entity_coverage(partial, inventory)
        mismatch = next(item for item in issues if item["code"] == "inventory_ability_list_mismatch")
        self.assertEqual(mismatch["missing_rawcodes"], ["A002"])

    def test_parsed_object_inventory_follows_trigstr_into_actual_wts(self) -> None:
        (self.root / "m" / "war3map.wts").write_text(
            "STRING 10\n{\n|cffffcc00烈|r焰风暴\n}\n\nSTRING 20\n{\n实际文件中的错误文本。\n}\n",
            encoding="utf-8",
        )
        inventory = build_inventory(self.root)
        wrong_copy = self.manifest()
        wrong_copy["texts"][1].update(key="m:wts:999", record_key="m:wts:999")
        wrong_copy["entities"][0]["description_review"]["surfaces"][0]["text"]["key"] = "m:wts:999"
        wrong_copy["mentions"][0]["description"]["key"] = "m:wts:999"
        issues = validate_entity_coverage(wrong_copy, inventory)
        self.assertTrue(any(item["code"] == "inventory_wts_text_mismatch" for item in issues))

    def test_parsed_object_inventory_rejects_relabelled_map_scope(self) -> None:
        value = self.manifest()
        value["entities"][0]["scope"]["map"] = "another-map"
        issues = validate_entity_coverage(value, build_inventory(self.root))
        self.assertTrue(any(item["code"] == "inventory_map_scope_mismatch" for item in issues))

    def test_parsed_object_inventory_enforces_display_field_role_and_level(self) -> None:
        value = self.manifest(role="canonical")
        issues = validate_entity_coverage(value, build_inventory(self.root))
        mismatch = next(item for item in issues if item["code"] == "inventory_display_role_mismatch")
        self.assertEqual(mismatch["field"], "atp1")
        self.assertEqual(mismatch["expected_role"], "button")

    def test_semantic_release_gate_consumes_entity_audit(self) -> None:
        manifest_value = self.manifest(description="施放烈焰风爆。", observed="烈焰风爆")
        (self.root / "m" / "war3map.wts").write_text(
            "STRING 10\n{\n|cffffcc00烈|r焰风暴\n}\n\nSTRING 20\n{\n施放烈焰风爆。\n}\n",
            encoding="utf-8",
        )
        records = [
            {
                "id": "1", "source": "Main Quest", "translation": "主线任务", "surface": "quest",
                "decision": "translate", "status": "final", "provenance": "agent_authored",
            },
            {
                "id": "2", "audit_key": "m:wts:10", "source": "Fixture Ability",
                "translation": "|cffffcc00烈|r焰风暴", "surface": "ability_button",
                "decision": "translate", "status": "final", "provenance": "agent_authored",
            },
            {
                "id": "3", "audit_key": "m:wts:20", "source": "Use Fixture Ability.",
                "translation": "施放烈焰风爆。", "surface": "unit_description",
                "decision": "translate", "status": "final", "provenance": "agent_authored",
            },
        ]
        canonical = [
            {"key": str(row["id"]), "record": row}
            for row in records
        ]
        fingerprint = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest().upper()
        record_path = self.root / "records.json"
        review_path = self.root / "review.json"
        glossary_path = self.root / "glossary.json"
        manifest_path = self.root / "gate-manifest.json"
        report_path = self.root / "gate-report.json"
        record_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        review_path.write_text(json.dumps({
            "segment": "test", "record_file": str(record_path), "source_fingerprint": fingerprint,
            "reviewed_keys": ["1", "2", "3"], "reviewed_count": 3, "issues": [],
        }, ensure_ascii=False), encoding="utf-8")
        glossary_path.write_text(json.dumps({"entries": [{"source": "Main Quest", "target": "主线任务"}]}, ensure_ascii=False), encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest_value, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts" / "semantic_review_gate.py"),
            "--records", str(record_path), "--reviews", str(review_path),
            "--glossary", str(glossary_path), "--entity-manifest", str(manifest_path),
            "--term-db", str(self.db), "--term-source-root", str(self.root),
            "--object-root", str(self.root),
            "--expected-campaign", "c", "--expected-source-locale", "en-US",
            "--expected-target-locale", "zh-CN", "--expected-client-version", "1.31.1",
            "--expected-distribution", "classic",
            "--require-entity-audit", "--out", str(report_path),
        ], capture_output=True, text=True, check=False)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["entity_audit"]["manifest_count"], 1)
        self.assertTrue(any(item.get("code") == "mention_name_mismatch" for item in report["issues"]))
        self.assertFalse(any("stale_source_fingerprint" in item["issue"] for item in report["issues"]))
        self.assertFalse(any(item.get("code", "").startswith("inventory_") for item in report["issues"]), report["issues"])
        wrong_context = subprocess.run([
            sys.executable, str(ROOT / "scripts" / "semantic_review_gate.py"),
            "--records", str(record_path), "--reviews", str(review_path),
            "--glossary", str(glossary_path), "--entity-manifest", str(manifest_path),
            "--term-db", str(self.db), "--term-source-root", str(self.root),
            "--object-root", str(self.root),
            "--expected-campaign", "c", "--expected-source-locale", "en-US",
            "--expected-target-locale", "zh-TW", "--expected-client-version", "1.31.1",
            "--expected-distribution", "classic",
            "--require-entity-audit", "--out", str(report_path),
        ], capture_output=True, text=True, check=False)
        wrong_context_report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(wrong_context.returncode, 1)
        self.assertTrue(any("target_locale differs" in item["issue"] for item in wrong_context_report["issues"]))
        records[2]["translation"] = "最终译文是另一内容。"
        record_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        canonical = [{"key": str(row["id"]), "record": row} for row in records]
        fingerprint = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest().upper()
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["source_fingerprint"] = fingerprint
        review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts" / "semantic_review_gate.py"),
            "--records", str(record_path), "--reviews", str(review_path),
            "--glossary", str(glossary_path), "--entity-manifest", str(manifest_path),
            "--term-db", str(self.db), "--term-source-root", str(self.root),
            "--object-root", str(self.root),
            "--expected-campaign", "c", "--expected-source-locale", "en-US",
            "--expected-target-locale", "zh-CN", "--expected-client-version", "1.31.1",
            "--expected-distribution", "classic",
            "--require-entity-audit", "--out", str(report_path),
        ], capture_output=True, text=True, check=False)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any(item["issue"] == "entity text differs from final writer payload" for item in report["issues"]))


if __name__ == "__main__":
    unittest.main()
