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
        {"key": str(row.get("id", row.get("key", index))), "source": str(row.get("source", ""))}
        for index, row in enumerate(records)
    ]
    raw = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest().upper()


class TranslationProvenanceTests(unittest.TestCase):
    def run_gate(self, provenance: str | None) -> tuple[subprocess.CompletedProcess[str], dict]:
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
            result = subprocess.run(
                [
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
                ],
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


if __name__ == "__main__":
    unittest.main()
