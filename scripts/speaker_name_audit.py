from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PATTERNS = {
    "createActor": re.compile(
        r'ScreenplayFactory\.createActor\([^\n]*?,\s*"((?:\\.|[^"\\])*)"\s*\)'
    ),
    "BlzSetUnitName": re.compile(
        r'BlzSetUnitName\([^\n]*?,\s*"((?:\\.|[^"\\])*)"\s*\)'
    ),
    "BlzSetHeroProperName": re.compile(
        r'BlzSetHeroProperName\([^\n]*?,\s*"((?:\\.|[^"\\])*)"\s*\)'
    ),
}
LATIN = re.compile(r"[A-Za-z]")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit visible speaker/unit names in Lua.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--allow", action="append", default=[], help="Approved identity/name text.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    allowed = set(args.allow)
    findings = []
    for path in sorted(args.root.glob("*/war3map.lua")):
        text = path.read_text(encoding="utf-8-sig")
        for kind, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                value = match.group(1)
                if value in allowed or not LATIN.search(value):
                    continue
                findings.append(
                    {
                        "map": path.parent.name,
                        "kind": kind,
                        "value": value,
                        "line": text.count("\n", 0, match.start()) + 1,
                    }
                )
    report = {"findings": findings, "count": len(findings)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
