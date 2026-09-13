from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "semantic_review_gate.py"


def fingerprint(records: list[dict]) -> str:
    canonical = [
        {"key": str(row.get("id", row.get("key", index))), "record": row}
        for index, row in enumerate(records)
    ]
    raw = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest().upper()


class TranslationProvenanceTests(unittest.TestCase):
    def run_rows(self, records: list[dict]) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record_path = root / "records.json"
            review_path = root / "review.json"
            glossary_path = root / "glossary.json"
            report_path = root / "report.json"
            record_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            keys = [str(row["id"]) for row in records]
            review_path.write_text(json.dumps({
                "segment": "test", "record_file": str(record_path),
                "source_fingerprint": fingerprint(records), "reviewed_keys": keys,
                "reviewed_count": len(keys), "issues": [],
            }, ensure_ascii=False), encoding="utf-8")
            glossary_path.write_text('{"entries": []}', encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(GATE), "--records", str(record_path),
                "--reviews", str(review_path), "--glossary", str(glossary_path),
                "--out", str(report_path),
            ], capture_output=True, text=True, check=False)
            return result, json.loads(report_path.read_text(encoding="utf-8"))

    def run_gate(self, provenance: str | None, extra_args: list[str] | None = None) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record_path = root / "records.json"
            review_path = root / "review.json"
            glossary_path = root / "glossary.json"
            report_path = root / "report.json"
            record = {
                "id": "1",
                "source": "Main Quest",
                "translation": "主线任务",
                "decision": "translate",
                "status": "final",
                "surface": "quest",
            }
            if provenance is not None:
                record["provenance"] = provenance
            records = [record]
            record_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            review_path.write_text(
                json.dumps(
                    {
                        "segment": "test",
                        "record_file": str(record_path),
                        "source_fingerprint": fingerprint(records),
                        "reviewed_keys": ["1"],
                        "reviewed_count": 1,
                        "issues": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            glossary_path.write_text(
                json.dumps({"entries": [{"source": "Main Quest", "target": "主线任务"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            command = [
                    sys.executable,
                    str(GATE),
                    "--records",
                    str(record_path),
                    "--reviews",
                    str(review_path),
                    "--glossary",
                    str(glossary_path),
                    "--out",
                    str(report_path),
                ]
            command.extend(extra_args or [])
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
            return result, json.loads(report_path.read_text(encoding="utf-8"))

    def test_agent_authored_translation_passes(self) -> None:
        result, report = self.run_gate("agent_authored")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(report["issues"], [])

    def test_missing_provenance_fails(self) -> None:
        result, report = self.run_gate(None)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(
            any("missing or disallowed translation provenance" in issue["issue"] for issue in report["issues"])
        )

    def test_machine_translation_provenance_fails(self) -> None:
        result, report = self.run_gate("machine_translation")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(
            any("missing or disallowed translation provenance" in issue["issue"] for issue in report["issues"])
        )

    def test_release_mode_requires_entity_audit_inputs(self) -> None:
        result, report = self.run_gate("agent_authored", ["--require-entity-audit"])
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("requires --entity-manifest" in issue["issue"] for issue in report["issues"]))

    def test_same_source_on_different_entities_does_not_conflict(self) -> None:
        rows = [
            {"id": "1", "source": "Charge", "translation": "冲锋", "decision": "translate", "status": "final", "provenance": "agent_authored", "entity_key": "ability:A001", "surface": "ui"},
            {"id": "2", "source": "Charge", "translation": "蓄力", "decision": "translate", "status": "final", "provenance": "agent_authored", "entity_key": "ability:A002", "surface": "ui"},
        ]
        result, report = self.run_rows(rows)
        self.assertEqual(result.returncode, 0, report["issues"])

    def test_within_entity_split_requires_per_record_reasons(self) -> None:
        rows = [
            {"id": "1", "source": "Charge", "translation": "冲锋", "decision": "translate", "status": "final", "provenance": "agent_authored", "entity_key": "ability:A001", "surface": "ui"},
            {"id": "2", "source": "Charge", "translation": "蓄力", "decision": "translate", "status": "final", "provenance": "agent_authored", "entity_key": "ability:A001", "surface": "ui"},
        ]
        result, report = self.run_rows(rows)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any(item["location"] == "same-source-consistency" for item in report["issues"]))
        for row in rows:
            row["consistency_exception"] = "不同剧情状态下作者有意改变按钮语气"
        result, report = self.run_rows(rows)
        self.assertEqual(result.returncode, 0, report["issues"])
        self.assertEqual(len(report["accepted_consistency_exceptions"]), 1)

    def test_preserve_internal_requires_evidence_and_provenance(self) -> None:
        rows = [{"id": "1", "source": "Visible text", "decision": "preserve_internal", "status": "final", "surface": "internal"}]
        result, report = self.run_rows(rows)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("preserve_internal requires" in item["issue"] for item in report["issues"]))

    def test_invalid_decision_fails(self) -> None:
        rows = [{"id": "1", "source": "Text", "translation": "文本", "decision": "skip", "status": "final", "surface": "ui", "provenance": "agent_authored"}]
        result, report = self.run_rows(rows)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("decision must be" in item["issue"] for item in report["issues"]))


if __name__ == "__main__":
    unittest.main()
