from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from shared_lore_registry import load, load_many, query, validate  # noqa: E402


class SharedLoreRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "assets" / "shared-lore-terms.json"
        self.value = load(self.path)

    def test_bundled_registry_validates(self) -> None:
        report = validate(self.value)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["terms"], 32)

    def test_query_selects_shared_character_for_wc3(self) -> None:
        result = query(self.value, "Arthas", "zh-TW", "warcraft_iii")
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected"]["target_name"], "阿薩斯")

    def test_query_does_not_return_wrong_locale(self) -> None:
        result = query(self.value, "Arthas", "zh-CN", "warcraft_iii")
        self.assertEqual(result["status"], "no_match")

    def test_official_source_must_be_blizzard(self) -> None:
        value = json.loads(json.dumps(self.value))
        value["sources"][0]["urls"] = {"zh-TW": "https://example.invalid/not-blizzard"}
        self.assertFalse(validate(value)["passed"])

    def test_unknown_product_is_rejected(self) -> None:
        value = json.loads(json.dumps(self.value))
        value["terms"][0]["product_scope"] = ["warcraft_iii", "diablo"]
        self.assertFalse(validate(value)["passed"])

    def test_official_evidence_outranks_community_candidate(self) -> None:
        value = json.loads(json.dumps(self.value))
        value["sources"].append({
            "source_key": "community-arthas-spelling",
            "publisher": "community",
            "source_kind": "verified_community_reference",
            "urls": {"zh-TW": "https://example.invalid/community"},
            "retrieved_at": "2026-09-13",
        })
        value["terms"].append({
            "term_key": "lore:arthas",
            "entity_type": "character",
            "product_scope": ["warcraft_iii", "world_of_warcraft"],
            "source_name": "Arthas",
            "target_locale": "zh-TW",
            "target_name": "阿尔萨斯",
            "evidence_status": "verified_community_reference",
            "source_key": "community-arthas-spelling",
            "source_locator": "community:arthas",
        })
        self.assertTrue(validate(value)["passed"])
        result = query(value, "Arthas", "zh-TW", "warcraft_iii")
        self.assertEqual(result["selected"]["target_name"], "阿薩斯")

    def test_cli_validate(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "shared_lore_registry.py"), "validate", "--input", str(self.path)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_community_roster_merges_without_overriding_official_layer(self) -> None:
        community = ROOT / "assets" / "warcraft-iii-community-terms.json"
        wow = ROOT / "assets" / "world-of-warcraft-community-terms.json"
        client = ROOT / "assets" / "world-of-warcraft-client-terms.json"
        merged = load_many([self.path, community, wow, client])
        report = validate(merged)
        self.assertTrue(report["passed"], report)
        self.assertGreaterEqual(len(load(client)["terms"]), 1000)
        self.assertEqual(report["terms"], 202 + len(load(wow)["terms"]) + len(load(client)["terms"]))
        result = query(merged, "Blizzard", "zh-CN", "warcraft_iii")
        self.assertEqual(result["selected"]["target_name"], "暴风雪")

    def test_wow_roster_is_product_scoped(self) -> None:
        community = ROOT / "assets" / "warcraft-iii-community-terms.json"
        wow = ROOT / "assets" / "world-of-warcraft-community-terms.json"
        client = ROOT / "assets" / "world-of-warcraft-client-terms.json"
        merged = load_many([self.path, community, wow, client])
        result = query(merged, "Thrall", "zh-CN", "world_of_warcraft")
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected"]["target_name"], "萨尔")
        self.assertEqual(query(merged, "Thrall", "zh-CN", "warcraft_iii")["status"], "no_match")

    def test_client_layer_provides_paired_ui_translation(self) -> None:
        client = ROOT / "assets" / "world-of-warcraft-client-terms.json"
        value = load(client)
        result = query(value, "Alliance", "zh-CN", "world_of_warcraft")
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected"]["target_name"], "联盟")


if __name__ == "__main__":
    unittest.main()
