#!/usr/bin/env python3
"""Validate and query the product-separated Warcraft shared-lore registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse


SCHEMA_VERSION = 1
PRODUCTS = {"warcraft_iii", "world_of_warcraft"}
EVIDENCE = {"official_reference", "verified_community_reference", "campaign_override", "unverified"}
RANK = {"official_reference": 3, "campaign_override": 2, "verified_community_reference": 1, "unverified": 0}


class RegistryError(ValueError):
    pass


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read UTF-8 registry: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError(f"registry.schema_version must be {SCHEMA_VERSION}")
    if value.get("scope") != "shared_lore":
        raise RegistryError("registry.scope must be shared_lore")
    if not isinstance(value.get("sources"), list) or not isinstance(value.get("terms"), list):
        raise RegistryError("registry.sources and registry.terms must be arrays")
    return value


def validate(value: dict) -> dict:
    issues: list[dict[str, str]] = []
    sources: dict[str, dict] = {}
    for index, source in enumerate(value["sources"]):
        loc = f"sources[{index}]"
        if not isinstance(source, dict):
            issues.append({"location": loc, "issue": "source must be an object"})
            continue
        key = source.get("source_key")
        kind = source.get("source_kind")
        if not isinstance(key, str) or not key.strip():
            issues.append({"location": loc, "issue": "source_key is required"})
            continue
        if key in sources:
            issues.append({"location": loc, "issue": f"duplicate source_key {key}"})
            continue
        if kind not in EVIDENCE:
            issues.append({"location": loc, "issue": f"unsupported source_kind {kind!r}"})
        urls = source.get("urls")
        if not isinstance(urls, dict) or not urls:
            issues.append({"location": loc, "issue": "urls must be a non-empty object"})
        elif kind == "official_reference":
            if not any("blizzard.com" in urlparse(str(url)).netloc for url in urls.values()):
                issues.append({"location": loc, "issue": "official_reference must point to a Blizzard URL"})
        sources[key] = source

    identities: set[tuple] = set()
    for index, term in enumerate(value["terms"]):
        loc = f"terms[{index}]"
        if not isinstance(term, dict):
            issues.append({"location": loc, "issue": "term must be an object"})
            continue
        required = ("term_key", "entity_type", "source_name", "target_locale", "target_name", "evidence_status", "source_key", "source_locator")
        missing = [key for key in required if not isinstance(term.get(key), str) or not term[key].strip()]
        if missing:
            issues.append({"location": loc, "issue": f"missing required fields: {missing}"})
            continue
        if any(ch.isspace() for ch in term["term_key"]):
            issues.append({"location": loc, "issue": "term_key must not contain whitespace"})
        scope = term.get("product_scope")
        if not isinstance(scope, list) or not scope or not all(item in PRODUCTS for item in scope):
            issues.append({"location": loc, "issue": "product_scope must contain warcraft_iii and/or world_of_warcraft"})
            continue
        identity = (term["term_key"], term["target_locale"], tuple(sorted(scope)))
        if identity in identities:
            issues.append({"location": loc, "issue": "duplicate term identity"})
        identities.add(identity)
        evidence = term["evidence_status"]
        if evidence not in EVIDENCE:
            issues.append({"location": loc, "issue": f"unsupported evidence_status {evidence!r}"})
        source = sources.get(term["source_key"])
        if source is None:
            issues.append({"location": loc, "issue": f"unknown source_key {term['source_key']!r}"})
        elif evidence == "official_reference" and source.get("source_kind") != "official_reference":
            issues.append({"location": loc, "issue": "official_reference term must use an official_reference source"})
        if not isinstance(term["target_name"], str) or not term["target_name"].strip():
            issues.append({"location": loc, "issue": "target_name is required"})
    return {"passed": not issues, "issues": issues, "sources": len(sources), "terms": len(value["terms"])}


def query(value: dict, term: str, locale: str, product: str | None) -> dict:
    candidates = [
        row for row in value["terms"]
        if row.get("target_locale") == locale
        and (row.get("term_key") == term or row.get("source_name", "").casefold() == term.casefold())
        and (product is None or product in row.get("product_scope", []))
    ]
    result = {"status": "no_match", "query": {"term": term, "target_locale": locale, "product": product}, "candidates": candidates}
    if not candidates:
        return result
    highest = max(RANK.get(row.get("evidence_status"), -1) for row in candidates)
    best = [row for row in candidates if RANK.get(row.get("evidence_status"), -1) == highest]
    targets = {row.get("target_name") for row in best}
    if len(targets) != 1:
        result["status"] = "ambiguous"
        result["reason"] = "conflicting_targets_at_same_evidence_level"
        return result
    result["status"] = "selected"
    result["selected"] = best[0]
    result["reason"] = "highest_evidence_level"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Shared Warcraft lore registry")
    parser.add_argument("command", choices=("validate", "summary", "query"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--term")
    parser.add_argument("--target-locale", default="zh-TW")
    parser.add_argument("--product", choices=sorted(PRODUCTS))
    args = parser.parse_args()
    try:
        value = load(args.input)
        report = validate(value)
        if args.command == "validate":
            output = report
        elif args.command == "summary":
            by_evidence: dict[str, int] = {}
            by_locale: dict[str, int] = {}
            for row in value["terms"]:
                by_evidence[row["evidence_status"]] = by_evidence.get(row["evidence_status"], 0) + 1
                by_locale[row["target_locale"]] = by_locale.get(row["target_locale"], 0) + 1
            output = {**report, "by_evidence": by_evidence, "by_locale": by_locale}
        else:
            if not args.term:
                raise RegistryError("query requires --term")
            output = query(value, args.term, args.target_locale, args.product)
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        if args.command == "validate":
            return 0 if report["passed"] else 1
        if args.command == "query":
            return 0 if output["status"] == "selected" else 2
        return 0
    except RegistryError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
