from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from entity_term_audit import ManifestError, audit_manifest, final_text_bindings, read_manifest
from object_link_inventory import build_inventory, validate_entity_coverage
from term_registry import RegistryError, validate_database

BAD_RE = re.compile(
    r"\ufffd|<unk>|训练屠夫|交易伤害|造成的破坏|土地单位|空气单位|"
    r"原始内容存档|令人惊艳|拼写偷窃|列车马克斯|马克斯门|"
    r"分钟人|剪切采集器|重现债券|命中点|联盟国|接受命中|"
    r"脱离了方程式|正在爬行着|电话(?=[\u4e00-\u9fff])|"
    r"运行到最近的外哨|加里森|侵略奥拉|复活 a |还原健康|"
    r"拼写荒原|死路一条|行动上咒语|"
    r"心灵怪|受心灵束缚|米亚斯玛|魅惑怪|魅惑体|"
    r"吉尔塔拉斯|飞地联盟|"
    r"[\u4e00-\u9fff]{1,4}(?:哈哈|天天){3,}|"
    r"(.)\1{12,}"
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def expand(patterns: list[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        p = Path(pattern)
        if p.is_file():
            found.append(p)
        else:
            found.extend(Path(item) for item in glob.glob(pattern, recursive=True))
    return sorted(set(found))


def records_from(path: Path) -> list[dict]:
    value = read_json(path)
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("records"), list):
        return value["records"]
    raise ValueError(f"{path}: expected a record list or an object with records")


def stable_key(row: dict, index: int) -> str:
    return str(row.get("id", row.get("key", index)))


def record_fingerprint(rows: list[dict]) -> str:
    canonical = [{"key": stable_key(row, i), "record": row} for i, row in enumerate(rows)]
    raw = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail closed on incomplete semantic review evidence.")
    parser.add_argument("--records", action="append", required=True)
    parser.add_argument("--reviews", action="append", required=True)
    parser.add_argument("--glossary", type=Path, required=True)
    parser.add_argument(
        "--entity-manifest",
        action="append",
        default=[],
        help="entity-link evidence manifest; repeat for each disjoint scope",
    )
    parser.add_argument("--term-db", type=Path)
    parser.add_argument("--term-source-root", type=Path)
    parser.add_argument("--object-root", type=Path)
    parser.add_argument("--object-encoding")
    parser.add_argument("--expected-campaign")
    parser.add_argument("--expected-source-locale")
    parser.add_argument("--expected-target-locale")
    parser.add_argument("--expected-client-version")
    parser.add_argument("--expected-distribution")
    parser.add_argument(
        "--require-entity-audit",
        action="store_true",
        help="release mode: fail when no entity manifest/database was supplied",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    issues: list[dict] = []
    all_rows: list[tuple[Path, dict, str]] = []
    record_paths = expand(args.records)
    review_paths = expand(args.reviews)
    if not record_paths:
        issues.append({"location": "records", "issue": "no record file matched the supplied paths"})
    if not review_paths:
        issues.append({"location": "reviews", "issue": "no review manifest matched the supplied paths"})
    for path in record_paths:
        try:
            rows = records_from(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append({"location": str(path), "issue": str(exc)})
            continue
        if not all(isinstance(row, dict) for row in rows):
            issues.append({"location": str(path), "issue": "every record must be an object"})
            continue
        keys = [stable_key(row, i) for i, row in enumerate(rows)]
        if len(keys) != len(set(keys)):
            issues.append({"location": str(path), "issue": "duplicate stable key"})
        for i, row in enumerate(rows):
            all_rows.append((path, row, keys[i]))

    expected_by_path: dict[str, set[str]] = defaultdict(set)
    for path, _, key in all_rows:
        expected_by_path[str(path.resolve())].add(key)

    seen_review_keys: dict[str, Counter[str]] = defaultdict(Counter)
    for review_path in review_paths:
        try:
            review = read_json(review_path)
        except (OSError, json.JSONDecodeError) as exc:
            issues.append({"location": str(review_path), "issue": str(exc)})
            continue
        if not isinstance(review, dict):
            issues.append({"location": str(review_path), "issue": "review must be an object manifest, not an array"})
            continue
        keys = review.get("reviewed_keys")
        if not isinstance(keys, list) or not keys:
            issues.append({"location": str(review_path), "issue": "missing reviewed_keys coverage"})
            continue
        if len(keys) != len(set(map(str, keys))):
            issues.append({"location": str(review_path), "issue": "duplicate reviewed key"})
        normalized_keys = list(map(str, keys))
        if normalized_keys != sorted(normalized_keys):
            issues.append({"location": str(review_path), "issue": "reviewed_keys must be sorted as strings"})
        if review.get("reviewed_count") != len(keys):
            issues.append({"location": str(review_path), "issue": "reviewed_count does not match reviewed_keys"})
        if review.get("issues") != []:
            issues.append({"location": str(review_path), "issue": "unresolved semantic review issues"})
        source_fingerprint = review.get("source_fingerprint")
        if not isinstance(source_fingerprint, str) or not re.fullmatch(r"[0-9A-Fa-f]{64}", source_fingerprint):
            issues.append({"location": str(review_path), "issue": "source_fingerprint must be a 64-character hexadecimal SHA256"})
        owner = review.get("record_file")
        if not isinstance(owner, str) or not owner:
            issues.append({"location": str(review_path), "issue": "record_file is required"})
        else:
            owner_path = Path(owner)
            if not owner_path.is_absolute():
                owner_path = Path.cwd() / owner_path
            owner_path = owner_path.resolve()
            owner_name = str(owner_path)
            seen_review_keys[owner_name].update(normalized_keys)
            expected = expected_by_path.get(owner_name)
            if expected is None:
                issues.append({"location": str(review_path), "issue": "record_file is not one of the supplied record files"})
            else:
                extra = sorted(set(normalized_keys) - expected)
                if extra:
                    issues.append({"location": str(review_path), "issue": f"reviewed_keys contains keys absent from record_file: {extra[:20]}"})
            if owner_path.is_file() and isinstance(source_fingerprint, str) and re.fullmatch(r"[0-9A-Fa-f]{64}", source_fingerprint):
                try:
                    actual = record_fingerprint(records_from(owner_path))
                    if actual != source_fingerprint.upper():
                        issues.append({"location": str(review_path), "issue": "stale source_fingerprint"})
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    issues.append({"location": str(review_path), "issue": f"invalid record_file: {exc}"})
            elif not owner_path.is_file():
                issues.append({"location": str(review_path), "issue": f"record_file not found: {owner_path}"})

    for owner, expected in expected_by_path.items():
        counts = seen_review_keys.get(owner, Counter())
        missing = expected - set(counts)
        duplicate = sorted(key for key, count in counts.items() if count != 1 and key in expected)
        if missing:
            issues.append({"location": owner, "issue": f"unreviewed keys: {len(missing)}"})
        if duplicate:
            issues.append({"location": owner, "issue": f"keys reviewed other than exactly once: {duplicate[:20]}"})

    by_source: dict[tuple[str, str, str], dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    allowed_decisions = {"translate", "preserve_identity", "preserve_internal"}
    allowed_surfaces = {
        "campaign_text", "dialogue", "quest", "ui", "credits", "script_visible",
        "unit_name", "unit_description", "unit_ubertip",
        "ability_name", "ability_button", "ability_learn", "ability_tooltip",
        "item_name", "item_description", "other_visible", "internal",
    }
    for path, row, key in all_rows:
        decision = row.get("decision")
        location = f"{path}:{key}"
        if decision not in allowed_decisions:
            issues.append({"location": location, "issue": f"decision must be one of {sorted(allowed_decisions)}"})
            continue
        surface = row.get("surface")
        if not isinstance(surface, str) or surface not in allowed_surfaces:
            issues.append({"location": location, "issue": f"surface must be one of {sorted(allowed_surfaces)}"})
        if str(row.get("status", "")).lower() != "final":
            issues.append({"location": location, "issue": "record status must be final"})
        if decision == "preserve_internal":
            if row.get("visibility") != "internal" or not isinstance(row.get("visibility_evidence"), str) or not row["visibility_evidence"].strip():
                issues.append({"location": location, "issue": "preserve_internal requires visibility=internal and non-empty visibility_evidence"})
            if str(row.get("provenance", "")).strip().lower() != "source_reviewed_preservation":
                issues.append({"location": location, "issue": "preserve_internal requires source_reviewed_preservation provenance"})
            continue
        source = str(row.get("source", "")).replace("\r\n", "\n").replace("\r", "\n")
        target = str(row.get("translation", ""))
        provenance = str(row.get("provenance", "")).strip().lower()
        allowed_provenance = {"agent_authored", "human_authored"}
        if row.get("decision") == "preserve_identity":
            allowed_provenance.add("source_reviewed_preservation")
        if provenance not in allowed_provenance:
            issues.append(
                {
                    "location": f"{path}:{key}",
                    "issue": (
                        "missing or disallowed translation provenance; "
                        f"expected one of {sorted(allowed_provenance)}"
                    ),
                }
            )
        entity_identity = str(row.get("entity_key", row.get("entity_id", "__legacy_unscoped__")))
        surface = str(row.get("surface", "__unspecified_surface__"))
        by_source[(source, entity_identity, surface)][target].append(
            (f"{path}:{key}", str(row.get("consistency_exception", "")).strip())
        )
        if row.get("decision") in {"translate", "preserve_identity"} and BAD_RE.search(target):
            issues.append({"location": f"{path}:{key}", "issue": "known machine-translation artifact"})
    accepted_consistency_exceptions: list[dict] = []
    for (source, entity_identity, surface), targets in by_source.items():
        if len(targets) > 1:
            rows = [item for locations in targets.values() for item in locations]
            if all(reason for _, reason in rows):
                accepted_consistency_exceptions.append(
                    {
                        "source": source,
                        "entity_identity": entity_identity,
                        "surface": surface,
                        "records": [{"location": location, "reason": reason} for location, reason in rows],
                    }
                )
            else:
                issues.append(
                    {
                        "location": "same-source-consistency",
                        "source": source,
                        "entity_identity": entity_identity,
                        "surface": surface,
                        "issue": f"{len(targets)} competing translations without per-record reasons",
                    }
                )

    try:
        glossary = read_json(args.glossary)
        entries = glossary["entries"] if isinstance(glossary, dict) else glossary
        for entry in entries:
            source_term = str(entry.get("source", ""))
            target_term = str(entry.get("target", ""))
            entry_entity = entry.get("entity_key", entry.get("entity_id"))
            entry_surface = entry.get("surface")
            if not source_term or not target_term:
                continue
            old_targets: set[str] = set()
            for _, row, key in all_rows:
                row_entity = row.get("entity_key", row.get("entity_id"))
                identity_matches = entry_entity is None or entry_entity == row_entity
                surface_matches = entry_surface is None or entry_surface == row.get("surface")
                if source_term in str(row.get("source", "")) and identity_matches and surface_matches and row.get("decision") in {"translate", "preserve_identity"}:
                    target = str(row.get("translation", ""))
                    if target_term not in target and source_term not in {"Exodus II: The Worlds Forsaken"}:
                        issues.append({"location": f"glossary:{source_term}/{key}", "issue": "canonical target missing"})
                    old_targets.add(target)
            if len(old_targets) > 1:
                # This is informational unless a source occurrence omitted the canonical target above.
                pass
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        issues.append({"location": str(args.glossary), "issue": f"invalid glossary: {exc}"})

    entity_reports: list[dict] = []
    audit_records: dict[str, tuple[Path, dict, str]] = {}
    for path, row, key in all_rows:
        audit_key = row.get("audit_key")
        if audit_key is None:
            continue
        if not isinstance(audit_key, str) or not audit_key:
            issues.append({"location": f"{path}:{key}", "issue": "audit_key must be a non-empty string"})
        elif audit_key in audit_records:
            issues.append({"location": f"{path}:{key}", "issue": f"duplicate audit_key: {audit_key}"})
        else:
            audit_records[audit_key] = (path, row, key)
    expected_context = {
        "campaign": args.expected_campaign,
        "source_locale": args.expected_source_locale,
        "target_locale": args.expected_target_locale,
        "client_version": args.expected_client_version,
        "distribution": args.expected_distribution,
    }
    if args.require_entity_audit and (
        not args.entity_manifest or args.term_db is None or args.term_source_root is None
        or args.object_root is None or any(value is None for value in expected_context.values())
    ):
        issues.append(
            {
                "location": "entity-term-audit",
                "issue": "release mode requires --entity-manifest, --term-db, --term-source-root, --object-root, and every --expected-* context value",
            }
        )
    if args.term_db is not None and args.term_source_root is not None:
        try:
            registry_report = validate_database(args.term_db, args.term_source_root)
            for item in registry_report["issues"]:
                issues.append({"location": item["location"], "issue": f"invalid terminology registry: {item['issue']}"})
        except (OSError, sqlite3.Error, RegistryError) as exc:
            issues.append({"location": str(args.term_db), "issue": f"invalid terminology registry: {exc}"})

    consumed_audit_keys: Counter[str] = Counter()
    loaded_entity_manifests: list[dict] = []
    if args.entity_manifest:
        if args.term_db is None:
            issues.append({"location": "entity-term-audit", "issue": "--term-db is required with --entity-manifest"})
        else:
            manifest_paths = expand(args.entity_manifest)
            if not manifest_paths:
                issues.append({"location": "entity-term-audit", "issue": "no entity manifest matched the supplied paths"})
            for manifest_path in manifest_paths:
                try:
                    entity_manifest = read_manifest(manifest_path)
                    loaded_entity_manifests.append(entity_manifest)
                    for field, expected_value in expected_context.items():
                        if expected_value is not None and entity_manifest["context"].get(field) != expected_value:
                            issues.append({
                                "location": str(manifest_path),
                                "issue": f"entity manifest {field} differs from release --expected-{field.replace('_', '-')}",
                                "expected": expected_value,
                                "actual": entity_manifest["context"].get(field),
                            })
                    for binding in final_text_bindings(entity_manifest):
                        consumed_audit_keys[binding["record_key"]] += 1
                        record = audit_records.get(binding["record_key"])
                        if record is None:
                            issues.append({
                                "location": binding["source_location"],
                                "stable_key": binding["record_key"],
                                "issue": "entity text has no matching final writer record audit_key",
                            })
                            continue
                        record_path, record_row, record_key = record
                        final_text = str(record_row.get("translation", ""))
                        if final_text != binding["text"]:
                            issues.append({
                                "location": binding["source_location"],
                                "stable_key": binding["record_key"],
                                "issue": "entity text differs from final writer payload",
                                "entity_text": binding["text"],
                                "final_text": final_text,
                                "record_location": f"{record_path}:{record_key}",
                            })
                    entity_report = audit_manifest(entity_manifest, args.term_db)
                    entity_reports.append({"manifest": str(manifest_path), **entity_report})
                    for item in entity_report["issues"]:
                        issues.append(
                            {
                                "location": item["source_location"],
                                "stable_key": item["key"],
                                "code": item["code"],
                                "issue": item["message"],
                                **{
                                    key: value
                                    for key, value in item.items()
                                    if key not in {"source_location", "key", "code", "message"}
                                },
                            }
                        )
                except (OSError, json.JSONDecodeError, RegistryError, ManifestError) as exc:
                    issues.append({"location": str(manifest_path), "issue": f"invalid entity manifest: {exc}"})

    object_inventory_summary: dict = {}
    if args.object_root is not None:
        try:
            object_inventory = build_inventory(args.object_root, args.object_encoding)
            object_inventory_summary = {
                "root": object_inventory["root"],
                "fingerprint": object_inventory["fingerprint"],
                "file_count": len(object_inventory["files"]),
                "entity_count": len(object_inventory["entities"]),
                "slot_count": len(object_inventory["slots"]),
                "wts_entry_count": len(object_inventory["wts_entries"]),
            }
            combined = {
                "texts": [row for manifest in loaded_entity_manifests for row in manifest["texts"]],
                "entities": [row for manifest in loaded_entity_manifests for row in manifest["entities"]],
            }
            for item in validate_entity_coverage(combined, object_inventory):
                issues.append({
                    "location": item["source_location"], "stable_key": item["key"],
                    "code": item["code"], "issue": item["message"],
                    **{key: value for key, value in item.items() if key not in {"source_location", "key", "code", "message"}},
                })
        except (OSError, UnicodeError, ValueError) as exc:
            issues.append({"location": str(args.object_root), "issue": f"invalid object inventory root: {exc}"})

    if args.require_entity_audit:
        entity_surfaces = {"unit_description", "unit_ubertip", "ability_name", "ability_button", "ability_learn", "ability_tooltip"}
        for path, row, key in all_rows:
            surface = row.get("surface")
            if surface not in entity_surfaces:
                continue
            audit_key = row.get("audit_key")
            if not isinstance(audit_key, str) or not audit_key:
                issues.append({"location": f"{path}:{key}", "issue": f"{surface} record requires audit_key"})
            elif consumed_audit_keys[audit_key] != 1:
                issues.append({"location": f"{path}:{key}", "issue": f"entity-linked record must be consumed exactly once; got {consumed_audit_keys[audit_key]}"})

    report = {
        "issues": issues,
        "record_count": len(all_rows),
        "review_count": len(expand(args.reviews)),
        "entity_audit": {
            "required": args.require_entity_audit,
            "manifest_count": len(entity_reports),
            "reports": entity_reports,
        },
        "accepted_consistency_exceptions": accepted_consistency_exceptions,
        "object_inventory": object_inventory_summary,
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(all_rows), "reviews": report["review_count"], "issues": len(issues)}))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
