from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from shared_lore_registry import load, query, validate  # noqa: E402


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

    def test_cli_validate(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "shared_lore_registry.py"), "validate", "--input", str(self.path)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
