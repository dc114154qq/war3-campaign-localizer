#!/usr/bin/env python3
"""Build a product-scoped WoW client-string registry from paired locale files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ASSIGNMENT = re.compile(r'^([A-Z0-9_]+)\s*=\s*"(.*)";\s*$')


def parse_lua(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ASSIGNMENT.match(line)
        if not match:
            continue
        try:
            value = json.loads('"' + match.group(2) + '"')
        except json.JSONDecodeError:
            continue
        if isinstance(value, str):
            values[match.group(1)] = value
    return values


def useful(source: str, target: str) -> bool:
    if not source.strip() or not target.strip() or source == target:
        return False
    if len(source) > 180 or len(target) > 240:
        return False
    if source.startswith(("http://", "https://", "<html", "|c")):
        return False
    if "@" in source or "\\" in source:
        return False
    # Skip pure formatting/placeholder rows; keep ordinary strings containing a placeholder.
    if re.fullmatch(r"[%dsgf%0-9. -]+", source, flags=re.IGNORECASE):
        return False
    if not any(ch.isalpha() for ch in source):
        return False
    return True


def build(en_path: Path, zh_path: Path) -> dict:
    english = parse_lua(en_path)
    chinese = parse_lua(zh_path)
    terms = []
    for key in sorted(english.keys() & chinese.keys()):
        source = english[key]
        target = chinese[key]
        if not useful(source, target):
            continue
        terms.append({
            "term_key": f"wow:client:{key.casefold()}",
            "entity_type": "client_ui_string",
            "product_scope": ["world_of_warcraft"],
            "source_name": source,
            "target_locale": "zh-CN",
            "target_name": target,
            "evidence_status": "verified_community_reference",
            "source_key": "wow-globalstrings-zhcn-client",
            "source_locator": f"GlobalStrings/zhCN.lua:{key}",
        })
    return {
        "schema_version": 1,
        "scope": "shared_lore",
        "sources": [{
            "source_key": "wow-globalstrings-zhcn-client",
            "publisher": "tekkub/wow-globalstrings community mirror",
            "source_kind": "verified_community_reference",
            "urls": {
                "en-US": "https://github.com/tekkub/wow-globalstrings/blob/master/GlobalStrings/enUS.lua",
                "zh-CN": "https://github.com/tekkub/wow-globalstrings/blob/master/GlobalStrings/zhCN.lua",
            },
            "retrieved_at": "2026-09-13",
            "notes": "Paired English and Simplified Chinese GlobalStrings.lua values extracted from WoW client UI files. This is client evidence mirrored by a community repository, not a Blizzard API export.",
        }],
        "terms": terms,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source_dir / "enUS.lua", args.source_dir / "zhCN.lua")
    if len(result["terms"]) < 1000:
        raise SystemExit(f"paired client terms below target: {len(result['terms'])}")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"terms": len(result["terms"]), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
