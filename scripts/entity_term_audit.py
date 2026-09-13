#!/usr/bin/env python3
"""Audit unit-to-ability name mentions using resolved entity identities.

The input is an evidence manifest, not a translation worksheet.  This script
only validates names and bindings; it never changes source or localized text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from term_registry import RegistryError, connect, resolve_name


COLOR_RE = re.compile(r"\|c[0-9A-Fa-f]{8}|\|r", re.IGNORECASE)
LINEBREAK_RE = re.compile(r"\|n", re.IGNORECASE)
ALLOWED_FIELDS = {"uabi", "uhab", "manual_verified"}
RESOLVED_BINDINGS = {"direct", "inherited"}
MENTION_NAME_ROLES = {"button", "learn"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ManifestError(ValueError):
    pass


def normalize_display(value: str) -> str:
    """Remove display-only markup while preserving lexical content."""
    value = COLOR_RE.sub("", value)
    value = LINEBREAK_RE.sub("\n", value)
    value = value.replace("&&", "\0").replace("&", "").replace("\0", "&")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", value).strip()


def edit_distance_at_most_one(left: str, right: str) -> bool:
    """Small deterministic comparator for likely one-character name variants."""
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    short, long = (left, right) if len(left) < len(right) else (right, left)
    index_short = index_long = differences = 0
    while index_short < len(short) and index_long < len(long):
        if short[index_short] == long[index_long]:
            index_short += 1
            index_long += 1
        else:
            differences += 1
            index_long += 1
            if differences > 1:
                return False
    return True


def likely_name_occurrences(description: str, expected_names: set[str]) -> list[dict[str, Any]]:
    """Find exact or one-edit variants of bound ability names without global word scanning."""
    plain = normalize_display(description)
    candidates: list[tuple[int, int, int, str, str]] = []
    for expected in sorted({normalize_display(name) for name in expected_names if normalize_display(name)}):
        length = len(expected)
        lengths = {length}
        if length >= 3:
            lengths.update({length - 1, length + 1})
        for width in sorted(lengths):
            for start in range(0, len(plain) - width + 1):
                actual = plain[start:start + width]
                distance = 0 if actual == expected else 1
                if distance == 0 or (length >= 2 and edit_distance_at_most_one(actual, expected)):
                    candidates.append((distance, start, start + width, actual, expected))
    chosen: list[tuple[int, int, int, str, str]] = []
    occupied: set[int] = set()
    for candidate in sorted(candidates, key=lambda row: (row[0], row[1], abs(len(row[3]) - len(row[4])), row[4])):
        _, start, end, _, _ = candidate
        if any(index in occupied for index in range(start, end)):
            continue
        chosen.append(candidate)
        occupied.update(range(start, end))
    return [
        {"actual_name": actual, "expected_name": expected, "start": start, "end": end, "edit_distance": distance}
        for distance, start, end, actual, expected in sorted(chosen, key=lambda row: (row[1], row[2], row[4]))
    ]


def reference_identity(ref: Any) -> str:
    return json.dumps(ref, ensure_ascii=False, separators=(",", ":"), sort_keys=True) if isinstance(ref, dict) else "null"


def read_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ManifestError("manifest must be a JSON object")
    if value.get("schema_version") != 1:
        raise ManifestError("manifest.schema_version must be 1")
    unknown = sorted(set(value) - {"schema_version", "source_fingerprint", "evidence_files", "context", "texts", "entities", "mentions", "aliases", "exceptions"})
    if unknown:
        raise ManifestError(f"manifest has unknown top-level fields: {unknown}")
    if not isinstance(value.get("source_fingerprint"), str) or not SHA256_RE.fullmatch(value["source_fingerprint"]):
        raise ManifestError("manifest.source_fingerprint must be a 64-character hexadecimal SHA256")
    evidence_files = value.get("evidence_files")
    if not isinstance(evidence_files, list) or not evidence_files:
        raise ManifestError("manifest.evidence_files must be a non-empty array")
    canonical_evidence: list[dict[str, str]] = []
    for index, row in enumerate(evidence_files):
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise ManifestError(f"manifest.evidence_files[{index}] requires only path and sha256")
        relative = Path(row.get("path", ""))
        expected = row.get("sha256")
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ManifestError(f"manifest.evidence_files[{index}].path must be a safe relative path")
        if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
            raise ManifestError(f"manifest.evidence_files[{index}].sha256 is invalid")
        evidence_path = path.parent / relative
        if not evidence_path.is_file():
            raise ManifestError(f"manifest evidence file is missing: {relative}")
        actual = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        if actual != expected.lower():
            raise ManifestError(f"manifest evidence hash mismatch: {relative}")
        canonical_evidence.append({"path": relative.as_posix(), "sha256": expected.lower()})
    actual_fingerprint = hashlib.sha256(
        json.dumps(canonical_evidence, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if actual_fingerprint != value["source_fingerprint"].lower():
        raise ManifestError("manifest.source_fingerprint does not match evidence_files")
    for key in ("context", "texts", "entities", "mentions"):
        expected = dict if key == "context" else list
        if not isinstance(value.get(key), expected):
            raise ManifestError(f"manifest.{key}: {expected.__name__} required")
    if not isinstance(value.get("aliases", []), list):
        raise ManifestError("manifest.aliases: list required")
    if not isinstance(value.get("exceptions", []), list):
        raise ManifestError("manifest.exceptions: list required")
    if not value["entities"]:
        raise ManifestError("manifest.entities must not be empty release evidence")
    value["_manifest_dir"] = str(path.parent)
    return value


def issue(
    issues: list[dict[str, Any]], key: str, code: str, source_location: str,
    message: str, **details: Any,
) -> None:
    issues.append({
        "key": key,
        "code": code,
        "source_location": source_location,
        "message": message,
        **details,
    })


def text_value(
    ref: Any,
    texts: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
    owner_key: str,
    fallback_location: str,
) -> tuple[str | None, str]:
    if not isinstance(ref, dict):
        issue(issues, owner_key, "invalid_text_reference", fallback_location, "text reference must be an object")
        return None, fallback_location
    kind = ref.get("kind")
    if kind == "direct":
        value = ref.get("value")
        location = str(ref.get("source_location", fallback_location))
        if not isinstance(value, str):
            issue(issues, owner_key, "invalid_direct_text", location, "direct text requires a string value")
            return None, location
        return value, location
    if kind in {"wts", "text_key"}:
        key = ref.get("key")
        if not isinstance(key, str) or key not in texts:
            issue(issues, owner_key, "missing_text_reference", fallback_location, "referenced text key is absent", text_key=key)
            return None, fallback_location
        return str(texts[key]["text"]), str(texts[key].get("source_location", key))
    issue(issues, owner_key, "invalid_text_reference_kind", fallback_location, "text reference kind must be direct, wts, or text_key", actual_kind=kind)
    return None, fallback_location


def final_text_bindings(manifest: dict[str, Any]) -> list[dict[str, str]]:
    """Return every manifest text value that must equal a final writer record."""
    result: dict[str, dict[str, str]] = {}
    def add_binding(record_key: str, value: str, source_location: str) -> None:
        existing = result.get(record_key)
        if existing is not None and existing["text"] != value:
            raise ManifestError(f"record_key {record_key!r} is linked to conflicting final texts")
        result[record_key] = {"record_key": record_key, "text": value, "source_location": source_location}

    for index, row in enumerate(manifest["texts"]):
        if isinstance(row, dict) and isinstance(row.get("text"), str):
            record_key = row.get("record_key")
            if not isinstance(record_key, str) or not record_key:
                raise ManifestError(f"texts[{index}].record_key is required for final-payload linkage")
            add_binding(record_key, row["text"], str(row.get("source_location", f"texts[{index}]")))
    refs: list[dict[str, Any]] = []
    for entity in manifest["entities"]:
        if isinstance(entity, dict):
            refs.extend(
                name.get("text") for name in entity.get("display_names", [])
                if isinstance(name, dict) and isinstance(name.get("text"), dict)
            )
            review = entity.get("description_review")
            if isinstance(review, dict):
                refs.extend(
                    surface.get("text") for surface in review.get("surfaces", [])
                    if isinstance(surface, dict) and isinstance(surface.get("text"), dict)
                )
    refs.extend(
        mention.get("description") for mention in manifest["mentions"]
        if isinstance(mention, dict) and isinstance(mention.get("description"), dict)
    )
    for index, ref in enumerate(refs):
        if ref.get("kind") != "direct":
            continue
        record_key = ref.get("record_key")
        if not isinstance(record_key, str) or not record_key:
            raise ManifestError(f"direct text reference {index} requires record_key for final-payload linkage")
        add_binding(record_key, str(ref.get("value", "")), str(ref.get("source_location", f"direct-ref:{index}")))
    return list(result.values())


def evidence_file_paths(manifest: dict[str, Any]) -> set[str]:
    return {
        item["path"] for item in manifest.get("evidence_files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }


def rawcodes_from_base_evidence(manifest: dict[str, Any], binding: dict[str, Any]) -> tuple[set[str], str | None]:
    """Return inherited ability rawcodes proven by the hashed base-data evidence.

    The manifest records the selected rawcode list for quick review, but when a
    manifest was loaded from disk this function also checks the referenced JSON
    evidence entry so the binding cannot be justified by self-report alone.
    """
    source = binding.get("base_data_source")
    locator = binding.get("base_entry_locator")
    rawcodes = binding.get("inherited_rawcodes")
    if not isinstance(source, str) or not source.strip():
        return set(), "inherited ability binding requires a non-empty base_data_source"
    if source not in evidence_file_paths(manifest):
        return set(), "base_data_source must name a hashed manifest evidence file"
    if not isinstance(locator, str) or not locator.strip():
        return set(), "inherited ability binding requires base_entry_locator"
    if not isinstance(rawcodes, list) or not rawcodes or not all(isinstance(item, str) and len(item) == 4 for item in rawcodes):
        return set(), "inherited ability binding requires non-empty inherited_rawcodes"

    manifest_dir = manifest.get("_manifest_dir")
    if not isinstance(manifest_dir, str):
        return set(rawcodes), None
    try:
        evidence_path = (Path(manifest_dir) / source).resolve()
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return set(), f"base_data_source must be UTF-8 JSON evidence: {exc}"
    entries = evidence.get("entries") if isinstance(evidence, dict) else None
    if not isinstance(entries, list):
        return set(), "base_data_source JSON must contain an entries array"
    matches = [
        row for row in entries
        if isinstance(row, dict)
        and row.get("entry_locator") == locator
        and row.get("record_kind") == "ability_list"
    ]
    if len(matches) != 1:
        return set(), "base_entry_locator must resolve to exactly one ability_list evidence entry"
    evidence_rawcodes = matches[0].get("rawcodes")
    if not isinstance(evidence_rawcodes, list) or not all(isinstance(item, str) and len(item) == 4 for item in evidence_rawcodes):
        return set(), "ability_list evidence entry requires four-character rawcodes"
    if set(evidence_rawcodes) != set(rawcodes):
        return set(), "inherited_rawcodes differ from base-data evidence"
    return set(rawcodes), None


def registry_aliases(
    db_path: Path, entity_key: str, locale: str, version: str, distribution: str
) -> dict[str, set[str]]:
    with connect(db_path) as connection:
        result: dict[str, set[str]] = defaultdict(set)
        for row in connection.execute(
                """SELECT alias,source_key FROM aliases WHERE entity_key=? AND locale=?
                   AND (client_version IS NULL OR client_version=?)
                   AND (distribution IS NULL OR distribution=?)
                   AND evidence_status != 'unverified' AND source_key IS NOT NULL""",
                (entity_key, locale, version, distribution),
            ):
            result[row[0]].add(row[1])
        return dict(result)


def audit_manifest(manifest: dict[str, Any], db_path: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    applied_exceptions: list[dict[str, Any]] = []
    context = manifest["context"]
    required_context = ("campaign", "source_locale", "target_locale", "client_version", "distribution")
    missing_context = [key for key in required_context if not isinstance(context.get(key), str) or not context[key]]
    if missing_context:
        raise ManifestError(f"manifest.context missing non-empty fields: {missing_context}")

    texts: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(manifest["texts"]):
        location = f"texts[{index}]"
        if not isinstance(row, dict) or not isinstance(row.get("key"), str) or not isinstance(row.get("record_key"), str) or not isinstance(row.get("text"), str):
            issue(issues, location, "invalid_text_record", location, "text record requires string key, record_key, and text")
            continue
        key = row["key"]
        if key in texts:
            issue(issues, key, "duplicate_text_key", str(row.get("source_location", location)), "duplicate text key")
        else:
            texts[key] = row

    entities: dict[str, dict[str, Any]] = {}
    identities: dict[tuple[Any, ...], str] = {}
    for index, row in enumerate(manifest["entities"]):
        location = f"entities[{index}]"
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            issue(issues, location, "invalid_entity", location, "entity requires a string id")
            continue
        entity_id = row["id"]
        if entity_id in entities:
            issue(issues, entity_id, "duplicate_entity_id", location, "duplicate entity id")
            continue
        scope = row.get("scope")
        if not isinstance(scope, dict):
            issue(issues, entity_id, "invalid_entity_scope", location, "entity scope object is required")
            continue
        if scope.get("campaign") != context["campaign"] or not isinstance(scope.get("map"), str) or not scope["map"]:
            issue(issues, entity_id, "entity_scope_mismatch", location, "entity scope must use the manifest campaign and a non-empty map")
            continue
        object_type = row.get("object_type")
        stable_key = row.get("stable_key")
        rawcode = row.get("rawcode")
        if not isinstance(object_type, str) or not isinstance(stable_key, str) or not stable_key:
            issue(issues, entity_id, "invalid_entity_identity", location, "object_type and stable_key are required")
            continue
        if rawcode is not None and (not isinstance(rawcode, str) or len(rawcode) != 4):
            issue(issues, entity_id, "invalid_rawcode", location, "rawcode must be null or exactly four characters")
            continue
        identity = (scope.get("campaign"), scope.get("map"), object_type, stable_key)
        if identity in identities:
            issue(issues, entity_id, "duplicate_entity_identity", location, "scope/type/stable key duplicates another entity", other_entity_id=identities[identity])
        else:
            identities[identity] = entity_id
        entities[entity_id] = row

    display_names: dict[tuple[str, str, Any, Any], tuple[str, str]] = {}
    bindings: dict[str, set[str]] = {}
    description_reviews: dict[str, set[str]] = {}
    registry_entity_keys: dict[str, str] = {}
    for entity_id, row in entities.items():
        location = str(row.get("source_location", entity_id))
        scope = row["scope"]
        if row.get("object_type") == "unit":
            scan = row.get("ability_scan")
            if not isinstance(scan, dict) or scan.get("status") != "complete" or not isinstance(scan.get("bindings"), list):
                issue(issues, entity_id, "ability_coverage_missing", location, "unit requires a complete ability_scan with bindings")
                continue
            seen_binding_keys: set[str] = set()
            targets: set[str] = set()
            for binding_index, binding in enumerate(scan["bindings"]):
                binding_location = f"{location}:binding:{binding_index}"
                if not isinstance(binding, dict) or not isinstance(binding.get("key"), str):
                    issue(issues, f"{entity_id}:binding:{binding_index}", "invalid_binding", binding_location, "binding requires a stable key")
                    continue
                key = binding["key"]
                source_location = str(binding.get("source_location", binding_location))
                if key in seen_binding_keys:
                    issue(issues, key, "duplicate_binding_key", source_location, "duplicate ability binding key")
                seen_binding_keys.add(key)
                field = binding.get("field")
                if field not in ALLOWED_FIELDS:
                    issue(issues, key, "unverified_binding_field", source_location, "binding field is not in the verified contract", actual_field=field)
                resolution = binding.get("resolution")
                if resolution not in RESOLVED_BINDINGS:
                    issue(issues, key, "unresolved_ability_reference", source_location, "dynamic or unresolved ability reference blocks release", resolution=resolution)
                    continue
                target = binding.get("ability_entity_id")
                if not isinstance(target, str) or target not in entities or entities[target].get("object_type") != "ability":
                    issue(issues, key, "wrong_ability_binding", source_location, "binding target must be an existing ability entity", ability_entity_id=target)
                    continue
                if target in targets:
                    issue(issues, key, "duplicate_ability_binding", source_location, "unit binds the same ability more than once", ability_entity_id=target)
                targets.add(target)
                if entities[target].get("scope") != row.get("scope"):
                    issue(issues, key, "wrong_ability_binding", source_location, "unit and bound ability must have the same campaign/map scope", ability_entity_id=target)
                if resolution == "inherited":
                    inherited_rawcodes, inherited_error = rawcodes_from_base_evidence(manifest, binding)
                    if inherited_error is not None:
                        issue(issues, key, "base_data_missing", source_location, inherited_error)
                    elif entities[target].get("rawcode") not in inherited_rawcodes:
                        issue(
                            issues, key, "base_data_missing", source_location,
                            "bound ability rawcode is absent from inherited base-data ability list",
                            ability_rawcode=entities[target].get("rawcode"),
                            inherited_rawcodes=sorted(inherited_rawcodes),
                        )
                    if not isinstance(entities[target].get("inherits"), str) or not entities[target]["inherits"].strip():
                        issue(issues, key, "base_data_missing", source_location, "inherited binding target must declare its base entity in inherits")
            bindings[entity_id] = targets
            review = row.get("description_review")
            if not isinstance(review, dict) or review.get("status") != "complete":
                issue(issues, entity_id, "description_coverage_missing", location, "unit requires a complete description_review")
            elif not isinstance(review.get("source_locations"), list) or not review["source_locations"] or not all(isinstance(item, str) and item for item in review["source_locations"]):
                issue(issues, entity_id, "description_coverage_missing", location, "description_review requires non-empty source_locations")
            elif not isinstance(review.get("mention_keys"), list) or not all(isinstance(item, str) for item in review["mention_keys"]):
                issue(issues, entity_id, "description_coverage_missing", location, "description_review.mention_keys must be an array of strings")
            else:
                description_reviews[entity_id] = set(review["mention_keys"])

        if row.get("object_type") == "ability":
            if row.get("inherits") and row.get("base_data_status") != "available":
                issue(issues, entity_id, "base_data_missing", location, "inherited ability entity requires base_data_status=available")
            names = row.get("display_names")
            if not isinstance(names, list) or not names:
                issue(issues, entity_id, "ability_name_missing", location, "ability requires at least one display_names row")
                continue
            for name_index, name in enumerate(names):
                name_key = f"{entity_id}:name:{name_index}"
                if not isinstance(name, dict) or not isinstance(name.get("role"), str):
                    issue(issues, name_key, "invalid_display_name", location, "display name requires a role")
                    continue
                if not isinstance(name.get("source_name"), str) or not name["source_name"]:
                    issue(issues, name_key, "source_display_name_missing", location, "display name requires the exact original source_name")
                    continue
                value, value_location = text_value(name.get("text"), texts, issues, name_key, location)
                identity = (entity_id, name["role"], name.get("level"), name.get("form"))
                if identity in display_names:
                    issue(issues, name_key, "duplicate_display_name_identity", value_location, "duplicate role/level/form display name")
                elif value is not None:
                    display_names[identity] = (value, value_location)
                    result = resolve_name(
                        db_path,
                        object_type="ability",
                        rawcode=row.get("rawcode"),
                        stable_key=row.get("stable_key"),
                        campaign=scope.get("campaign"),
                        map_key=scope.get("map"),
                        target_locale=context["target_locale"],
                        source_locale=context["source_locale"],
                        client_version=context["client_version"],
                        distribution=context["distribution"],
                        name_role=name["role"],
                        level=name.get("level"),
                        form=name.get("form"),
                    )
                    if result["status"] != "selected":
                        issue(issues, name_key, "term_decision_unresolved", value_location, "terminology registry has no exact final decision for this display role/level/form", registry_status=result["status"], registry_reason=result["reason"])
                    else:
                        registry_entity_keys[entity_id] = result["selected"]["entity_key"]
                        expected = result["selected"]["target_name"]
                        expected_source = result["selected"]["source_name"]
                        if normalize_display(name["source_name"]) != normalize_display(expected_source):
                            issue(issues, name_key, "source_name_not_registry_entity", value_location, "original ability display name differs from the selected registry entity", expected_source_name=expected_source, actual_source_name=name["source_name"], ability_entity_id=entity_id)
                        if normalize_display(value) != normalize_display(expected):
                            issue(issues, name_key, "display_name_not_canonical", value_location, "actual ability display name differs from the registry decision", expected_name=expected, actual_name=value, ability_entity_id=entity_id)

    explicit_aliases: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(manifest.get("aliases", [])):
        location = f"aliases[{index}]"
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) and row[key] for key in ("entity_id", "alias", "reason", "source_location", "registry_source_key")):
            issue(issues, location, "invalid_alias", location, "alias requires entity_id, alias, reason, source_location, and registry_source_key")
            continue
        if row["entity_id"] not in entities:
            issue(issues, location, "invalid_alias_entity", row["source_location"], "alias references an unknown entity")
            continue
        keys = row.get("mention_keys")
        if not isinstance(keys, list) or not keys or not all(isinstance(item, str) for item in keys):
            issue(issues, location, "invalid_alias_scope", row["source_location"], "mention_keys must be a non-empty array of strings")
            continue
        explicit_aliases.setdefault(row["entity_id"], []).append(row)

    exceptions: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for index, row in enumerate(manifest.get("exceptions", [])):
        location = f"exceptions[{index}]"
        required = ("key", "code", "expected_name", "actual_name", "reason", "source_location", "evidence_path")
        if not isinstance(row, dict) or not all(isinstance(row.get(name), str) and row[name] for name in required):
            issue(issues, location, "invalid_exception", location, "exception requires key, code, expected_name, actual_name, reason, and source_location")
            continue
        if row["evidence_path"] not in {item["path"] for item in manifest["evidence_files"]}:
            issue(issues, row["key"], "invalid_exception_evidence", row["source_location"], "exception evidence_path is not a hashed manifest evidence file")
            continue
        if row["code"] != "mention_name_mismatch":
            issue(issues, row["key"], "invalid_exception_code", row["source_location"], "only exact mention_name_mismatch exceptions are supported")
            continue
        identity = (row["key"], row["code"], normalize_display(row["expected_name"]), normalize_display(row["actual_name"]))
        if identity in exceptions:
            issue(issues, row["key"], "duplicate_exception", row["source_location"], "duplicate exact exception")
        exceptions[identity] = row

    seen_mention_keys: set[str] = set()
    declared_occurrences: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for index, mention in enumerate(manifest["mentions"]):
        fallback_key = f"mentions[{index}]"
        if not isinstance(mention, dict) or not isinstance(mention.get("key"), str):
            issue(issues, fallback_key, "invalid_mention", fallback_key, "mention requires a stable key")
            continue
        key = mention["key"]
        source_location = str(mention.get("source_location", key))
        if key in seen_mention_keys:
            issue(issues, key, "duplicate_mention_key", source_location, "duplicate mention key")
            continue
        seen_mention_keys.add(key)
        if mention.get("status") != "resolved":
            issue(issues, key, "unresolved_mention", source_location, "mention is not resolved to an ability entity", status=mention.get("status"))
            continue
        owner = mention.get("owner_entity_id")
        ability = mention.get("ability_entity_id")
        if owner not in entities or ability not in entities:
            issue(issues, key, "unknown_mention_entity", source_location, "mention owner or ability entity is absent", owner_entity_id=owner, ability_entity_id=ability)
            continue
        if ability not in bindings.get(owner, set()):
            issue(issues, key, "mention_not_bound_to_owner", source_location, "mentioned ability is not in the owner's resolved ability list", owner_entity_id=owner, ability_entity_id=ability)
            continue
        role = str(mention.get("expected_role", "button"))
        if role not in MENTION_NAME_ROLES:
            issue(
                issues, key, "mention_role_not_skill_bar", source_location,
                "description mentions must compare against the ability button or learning display name, not a canonical/editor name",
                actual_role=role,
                allowed_roles=sorted(MENTION_NAME_ROLES),
            )
            continue
        level, form = mention.get("level"), mention.get("form")
        name_identity = (ability, role, level, form)
        if name_identity not in display_names:
            issue(issues, key, "expected_display_name_missing", source_location, "ability has no exact role/level/form display name", expected_role=role, level=level, form=form)
            continue
        displayed, displayed_location = display_names[name_identity]
        ability_row = entities[ability]
        scope = ability_row["scope"]
        decision = resolve_name(
            db_path,
            object_type="ability",
            rawcode=ability_row.get("rawcode"),
            stable_key=ability_row.get("stable_key"),
            campaign=scope.get("campaign"),
            map_key=scope.get("map"),
            target_locale=context["target_locale"],
            source_locale=context["source_locale"],
            client_version=context["client_version"],
            distribution=context["distribution"],
            name_role=role,
            level=level,
            form=form,
        )
        if decision["status"] != "selected":
            issue(issues, key, "term_decision_unresolved", source_location, "no exact registry decision for mention role/level/form", registry_status=decision["status"], registry_reason=decision["reason"])
            continue
        expected = decision["selected"]["target_name"]
        if normalize_display(displayed) != normalize_display(expected):
            issue(issues, key, "display_name_not_canonical", displayed_location, "actual ability display name differs from the registry decision", expected_name=expected, actual_name=displayed, ability_entity_id=ability)
        observed = mention.get("observed_name")
        if not isinstance(observed, str) or not observed:
            issue(issues, key, "observed_name_missing", source_location, "mention must record the exact name span observed in the description")
            continue
        description, description_location = text_value(mention.get("description"), texts, issues, key, source_location)
        if description is None:
            continue
        span = mention.get("span")
        if (
            not isinstance(span, list) or len(span) != 2
            or not all(isinstance(item, int) and not isinstance(item, bool) for item in span)
            or not (0 <= span[0] < span[1] <= len(description))
            or description[span[0]:span[1]] != observed
        ):
            issue(issues, key, "mention_span_not_found", description_location, "span must select the exact observed_name in the unmodified description", actual_name=observed, span=span)
            continue
        declared_occurrences[(owner, reference_identity(mention.get("description")))][normalize_display(observed)] += 1
        accepted = {expected}
        registry_key = registry_entity_keys.get(ability)
        registry_alias_map: dict[str, set[str]] = {}
        if registry_key:
            registry_alias_map = registry_aliases(db_path, registry_key, context["target_locale"], context["client_version"], context["distribution"])
            accepted.update(registry_alias_map)
        for alias in explicit_aliases.get(ability, []):
            if key in alias["mention_keys"] and alias["registry_source_key"] in registry_alias_map.get(alias["alias"], set()):
                accepted.add(alias["alias"])
            elif key in alias["mention_keys"]:
                issue(issues, key, "alias_not_in_registry", alias["source_location"], "manifest alias is not backed by an accepted registry alias", actual_name=alias["alias"], registry_source_key=alias["registry_source_key"])
        if normalize_display(observed) not in {normalize_display(item) for item in accepted}:
            exception_identity = (key, "mention_name_mismatch", normalize_display(expected), normalize_display(observed))
            if exception_identity in exceptions:
                exception = exceptions.pop(exception_identity)
                applied_exceptions.append({
                    "key": key,
                    "code": "mention_name_mismatch",
                    "expected_name": expected,
                    "actual_name": observed,
                    "reason": exception["reason"],
                    "source_location": exception["source_location"],
                })
            else:
                issue(issues, key, "mention_name_mismatch", description_location, "description mention does not use the resolved ability name or an explicit alias", expected_name=expected, actual_name=observed, accepted_aliases=sorted(accepted - {expected}), ability_entity_id=ability)

    for exception in exceptions.values():
        issue(issues, exception["key"], "unused_exception", exception["source_location"], "exception did not match an actual diagnostic")

    mentions_by_owner: dict[str, set[str]] = defaultdict(set)
    for mention in manifest["mentions"]:
        if isinstance(mention, dict) and isinstance(mention.get("key"), str) and isinstance(mention.get("owner_entity_id"), str):
            mentions_by_owner[mention["owner_entity_id"]].add(mention["key"])
    for unit_id, declared in description_reviews.items():
        actual = mentions_by_owner.get(unit_id, set())
        missing = sorted(actual - declared)
        invented = sorted(declared - actual)
        if missing or invented:
            issue(issues, unit_id, "description_coverage_mismatch", str(entities[unit_id].get("source_location", unit_id)), "description_review mention_keys do not exactly match unit mentions", missing=missing, invented=invented)

    # A blank mention list is not accepted on trust: scan only for names of
    # abilities actually bound to this unit.  Exact names are always checked;
    # names of two or more characters also get a one-edit check, which catches
    # common added/missing/substituted-character discrepancies while avoiding a
    # noisy whole-corpus fuzzy search.
    for unit_id, ability_ids in bindings.items():
        review = entities[unit_id].get("description_review", {})
        surfaces = review.get("surfaces", []) if isinstance(review, dict) else []
        expected_names = {
            value
            for (ability_id, role, _level, _form), (value, _location) in display_names.items()
            if ability_id in ability_ids and role in MENTION_NAME_ROLES
        }
        for surface_index, surface in enumerate(surfaces if isinstance(surfaces, list) else []):
            ref = surface.get("text") if isinstance(surface, dict) else None
            surface_key = reference_identity(ref)
            description, description_location = text_value(
                ref, texts, issues, f"{unit_id}:description:{surface_index}",
                str(entities[unit_id].get("source_location", unit_id)),
            )
            if description is None:
                continue
            detected = Counter(item["actual_name"] for item in likely_name_occurrences(description, expected_names))
            declared_counts = declared_occurrences.get((unit_id, surface_key), Counter())
            for actual_name, count in sorted(detected.items()):
                missing_count = count - declared_counts[normalize_display(actual_name)]
                for ordinal in range(max(0, missing_count)):
                    detail = next(item for item in likely_name_occurrences(description, expected_names) if item["actual_name"] == actual_name)
                    issue(
                        issues, f"{unit_id}:description:{surface_index}:candidate:{actual_name}:{ordinal}",
                        "undeclared_potential_mention", description_location,
                        "description contains an exact or one-edit variant of a bound ability name that is absent from mentions",
                        **detail,
                    )

    if not any(row.get("object_type") == "unit" for row in entities.values()):
        issue(issues, "manifest", "unit_coverage_missing", "manifest", "release evidence requires at least one unit entity")
    if not any(row.get("object_type") == "ability" for row in entities.values()):
        issue(issues, "manifest", "ability_coverage_missing", "manifest", "release evidence requires at least one ability entity")
    if not any(bindings.values()):
        issue(issues, "manifest", "ability_binding_coverage_missing", "manifest", "release evidence requires at least one resolved unit-to-ability binding")

    issues.sort(key=lambda row: (row["key"], row["code"], row["source_location"]))
    return {
        "schema_version": 1,
        "passed": not issues,
        "entity_count": len(entities),
        "mention_count": len(manifest["mentions"]),
        "applied_exceptions": sorted(applied_exceptions, key=lambda row: row["key"]),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Warcraft III ability mentions by entity identity")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--term-db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = read_manifest(args.manifest)
        report = audit_manifest(manifest, args.term_db)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"entities": report["entity_count"], "mentions": report["mention_count"], "issues": len(report["issues"])}))
        return 0 if report["passed"] else 1
    except (OSError, json.JSONDecodeError, sqlite3.Error, RegistryError, ManifestError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
