#!/usr/bin/env python3
"""Inventory entity-link-relevant slots from extracted WC3 object files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from text_only_verify import parse_object_auto
from wts_tool import parse as parse_wts


UNIT_FIELDS = {"uabi", "uhab", "utip", "utub"}
ABILITY_FIELDS = {"anam", "atp1", "aret"}
ABILITY_FIELD_ROLES = {"anam": "canonical", "atp1": "button", "aret": "learn"}
TRIGSTR_RE = re.compile(r"^TRIGSTR_(\d+)$")


def referenced_storage_value(ref: Any, texts: dict[str, dict[str, Any]]) -> str | None:
    """Return the exact value expected in an object string slot."""
    if not isinstance(ref, dict):
        return None
    if ref.get("kind") == "direct":
        return ref.get("value") if isinstance(ref.get("value"), str) else None
    if ref.get("kind") in {"wts", "text_key"}:
        row = texts.get(ref.get("key"))
        return row.get("storage_ref") if isinstance(row, dict) and isinstance(row.get("storage_ref"), str) else None
    return None


def decode_id(value: bytes, location: str) -> str:
    try:
        return value.decode("latin-1")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{location}: invalid four-byte object ID") from exc


def decode_value(value: bytes, encoding: str | None, location: str) -> str:
    if encoding:
        return value.decode(encoding)
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{location}: non-UTF-8 object string; pass --encoding") from exc


def effective_rawcode(obj: dict[str, Any], location: str) -> str:
    new_id = decode_id(obj["new_id"], location)
    return decode_id(obj["old_id"], location) if obj["new_id"] == b"\0\0\0\0" else new_id


def build_inventory(root: Path, encoding: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"object root is not a directory: {root}")
    files: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    slots: list[dict[str, Any]] = []
    wts_entries: list[dict[str, Any]] = []
    seen_entity_keys: set[str] = set()
    seen_slot_keys: set[str] = set()
    seen_wts_keys: set[tuple[str, str]] = set()
    for path in sorted(root.rglob("war3map.wts")):
        relative = path.relative_to(root).as_posix()
        map_key = path.parent.relative_to(root).as_posix()
        files.append({
            "path": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "object_type": "wts",
            "layout_has_levels": None,
        })
        for string_id, value in parse_wts(path, encoding):
            normalized_id = str(int(string_id))
            identity = (map_key, normalized_id)
            if identity in seen_wts_keys:
                raise ValueError(f"duplicate WTS identity across files: map={map_key} STRING {normalized_id}")
            seen_wts_keys.add(identity)
            wts_entries.append({
                "map_key": map_key,
                "id": normalized_id,
                "value": value,
                "file": relative,
                "source_location": f"{relative}:STRING {string_id}",
            })
    for suffix, object_type, visible_fields in (
        ("*.w3u", "unit", UNIT_FIELDS),
        ("*.w3a", "ability", ABILITY_FIELDS),
    ):
        for path in sorted(root.rglob(suffix)):
            relative = path.relative_to(root).as_posix()
            parsed, has_levels = parse_object_auto(path)
            files.append({
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "object_type": object_type,
                "layout_has_levels": has_levels,
            })
            for table_index, table in enumerate(parsed["tables"]):
                for object_index, obj in enumerate(table):
                    rawcode = effective_rawcode(obj, f"{relative}:{table_index}:{object_index}")
                    relevant_mods = []
                    for mod_index, mod in enumerate(obj["mods"]):
                        field = decode_id(mod["field"], relative)
                        if field not in visible_fields:
                            continue
                        if mod["type"] != 3:
                            raise ValueError(f"{relative}:{rawcode}:{field}: expected string field")
                        slot_key = f"{relative}:table:{table_index}:object:{object_index}:mod:{mod_index}"
                        if slot_key in seen_slot_keys:
                            raise ValueError(f"duplicate inventory slot key: {slot_key}")
                        seen_slot_keys.add(slot_key)
                        row = {
                            "key": slot_key,
                            "entity_key": f"{relative}:table:{table_index}:object:{object_index}",
                            "object_type": object_type,
                            "map_key": path.parent.relative_to(root).as_posix(),
                            "rawcode": rawcode,
                            "field": field,
                            "level": mod["level"],
                            "data_pointer": mod["data_pointer"],
                            "value": decode_value(mod["value"], encoding, slot_key),
                        }
                        slots.append(row)
                        relevant_mods.append(row)
                    if not relevant_mods:
                        continue
                    entity_key = f"{relative}:table:{table_index}:object:{object_index}"
                    if entity_key in seen_entity_keys:
                        raise ValueError(f"duplicate inventory entity key: {entity_key}")
                    seen_entity_keys.add(entity_key)
                    entities.append({
                        "key": entity_key,
                        "file": relative,
                        "map_key": path.parent.relative_to(root).as_posix(),
                        "object_type": object_type,
                        "rawcode": rawcode,
                        "old_rawcode": decode_id(obj["old_id"], entity_key),
                        "table_index": table_index,
                        "object_index": object_index,
                        "slot_keys": [row["key"] for row in relevant_mods],
                    })
    canonical = {"files": files, "entities": entities, "slots": slots, "wts_entries": wts_entries}
    fingerprint = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return {"schema_version": 1, "root": str(root), "fingerprint": fingerprint, **canonical}


def validate_entity_coverage(manifest: dict[str, Any], inventory: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    inv_entities = {row["key"]: row for row in inventory["entities"]}
    inv_slots = {row["key"]: row for row in inventory["slots"]}
    inv_wts = {(row["map_key"], row["id"]): row for row in inventory.get("wts_entries", [])}
    required_entities = set(inv_entities)
    actual_entities: dict[str, dict[str, Any]] = {}
    actual_slots: set[str] = set()
    claimed_direct_by_slot: dict[str, set[str]] = {}
    texts = {
        row.get("key"): row for row in manifest.get("texts", [])
        if isinstance(row, dict) and isinstance(row.get("key"), str)
    }
    manifest_by_id: dict[Any, dict[str, Any]] = {}
    for row in manifest["entities"]:
        if not isinstance(row, dict):
            continue
        if row.get("id") in manifest_by_id:
            issues.append({"key": str(row.get("id")), "code": "duplicate_release_entity_id", "source_location": str(row.get("source_location", row.get("id"))), "message": "entity id must be unique across all release manifests"})
        manifest_by_id[row.get("id")] = row

    def validate_slot_text(slot: dict[str, Any], ref: Any, owner_key: str, location: str) -> None:
        expected_value = referenced_storage_value(ref, texts)
        if expected_value is None:
            issues.append({"key": owner_key, "code": "inventory_text_reference_missing", "source_location": location, "message": "surface lacks a direct value or WTS storage_ref"})
            return
        if slot["value"] != expected_value:
            issues.append({"key": owner_key, "code": "inventory_text_reference_mismatch", "source_location": location, "message": "object slot value does not match its declared direct/WTS reference", "expected_value": expected_value, "actual_value": slot["value"]})
            return
        if not isinstance(ref, dict) or ref.get("kind") not in {"wts", "text_key"}:
            return
        match = TRIGSTR_RE.fullmatch(expected_value)
        text_row = texts.get(ref.get("key"))
        if match is None or text_row is None:
            issues.append({"key": owner_key, "code": "inventory_wts_link_missing", "source_location": location, "message": "WTS-linked surface requires a TRIGSTR_<id> storage_ref and an existing text row"})
            return
        normalized_id = str(int(match.group(1)))
        derived_record_key = f"{slot['map_key']}:wts:{normalized_id}"
        if ref.get("key") != derived_record_key or text_row.get("record_key") != derived_record_key:
            issues.append({"key": owner_key, "code": "inventory_wts_record_key_mismatch", "source_location": location, "message": "WTS text key/record_key must be derived from parsed map directory and TRIGSTR id", "expected_record_key": derived_record_key, "actual_text_key": ref.get("key"), "actual_record_key": text_row.get("record_key")})
        wts_row = inv_wts.get((slot["map_key"], normalized_id))
        if wts_row is None:
            issues.append({"key": owner_key, "code": "inventory_wts_link_missing", "source_location": location, "message": "TRIGSTR id is absent from this parsed map's war3map.wts", "map": slot["map_key"], "storage_ref": expected_value})
        elif wts_row["value"] != text_row.get("text"):
            issues.append({"key": owner_key, "code": "inventory_wts_text_mismatch", "source_location": wts_row["source_location"], "message": "parsed WTS value differs from the manifest/final writer text", "expected_text": text_row.get("text"), "actual_text": wts_row["value"]})

    for row in manifest["entities"]:
        if not isinstance(row, dict):
            continue
        key = row.get("inventory_key")
        location = str(row.get("source_location", row.get("id", "entity")))
        if not isinstance(key, str) or key not in inv_entities:
            issues.append({"key": str(row.get("id", "entity")), "code": "inventory_entity_missing", "source_location": location, "message": "entity inventory_key is absent from parsed object inventory"})
            continue
        if key in actual_entities:
            issues.append({"key": str(row.get("id")), "code": "duplicate_inventory_entity", "source_location": location, "message": "object inventory entity is claimed more than once"})
        actual_entities[key] = row
        expected = inv_entities[key]
        if row.get("object_type") != expected["object_type"] or row.get("rawcode") != expected["rawcode"]:
            issues.append({"key": str(row.get("id")), "code": "inventory_entity_mismatch", "source_location": location, "message": "manifest entity type/rawcode differs from parsed object inventory"})
        scope = row.get("scope", {})
        if not isinstance(scope, dict) or scope.get("map") != expected["map_key"]:
            issues.append({"key": str(row.get("id")), "code": "inventory_map_scope_mismatch", "source_location": location, "message": "manifest map scope differs from the parsed object's relative directory", "expected_map": expected["map_key"], "actual_map": scope.get("map") if isinstance(scope, dict) else None})

        if row.get("object_type") == "unit":
            scan = row.get("ability_scan", {})
            for slot_key in scan.get("inventory_keys", []) if isinstance(scan, dict) else []:
                slot = inv_slots.get(slot_key)
                if slot is None or slot["entity_key"] != key or slot["field"] not in {"uabi", "uhab"}:
                    issues.append({"key": str(row.get("id")), "code": "inventory_ability_scan_mismatch", "source_location": location, "message": "ability_scan inventory key is not this unit's parsed uabi/uhab slot"})
                else:
                    actual_slots.add(slot_key)
            for binding in scan.get("bindings", []) if isinstance(scan, dict) else []:
                if binding.get("resolution") != "direct":
                    continue
                slot_key = binding.get("inventory_key")
                target = manifest_by_id.get(binding.get("ability_entity_id"), {})
                slot = inv_slots.get(slot_key)
                if slot is None or slot["entity_key"] != key or slot["field"] not in {"uabi", "uhab"} or binding.get("field") != slot["field"]:
                    issues.append({"key": str(binding.get("key", "binding")), "code": "inventory_binding_mismatch", "source_location": str(binding.get("source_location", location)), "message": "direct binding is not backed by this unit's parsed uabi/uhab slot"})
                else:
                    target_rawcode = target.get("rawcode")
                    if target_rawcode not in {item.strip() for item in slot["value"].split(",") if item.strip()}:
                        issues.append({"key": str(binding.get("key", "binding")), "code": "inventory_binding_mismatch", "source_location": str(binding.get("source_location", location)), "message": "ability rawcode is absent from parsed uabi/uhab value"})
                    elif isinstance(target_rawcode, str):
                        claimed_direct_by_slot.setdefault(slot_key, set()).add(target_rawcode)
            review = row.get("description_review", {})
            surfaces = review.get("surfaces", []) if isinstance(review, dict) else []
            if not isinstance(surfaces, list) or not surfaces:
                issues.append({"key": str(row.get("id")), "code": "inventory_description_surface_missing", "source_location": location, "message": "description_review requires non-empty surfaces linking each slot to its final text"})
                surfaces = []
            for surface in surfaces:
                slot_key = surface.get("inventory_key") if isinstance(surface, dict) else None
                slot = inv_slots.get(slot_key)
                if slot is None or slot["entity_key"] != key or slot["field"] not in {"utip", "utub"}:
                    issues.append({"key": str(row.get("id")), "code": "inventory_description_mismatch", "source_location": location, "message": "description_review inventory key is not this unit's parsed utip/utub slot"})
                else:
                    actual_slots.add(slot_key)
                    validate_slot_text(slot, surface.get("text"), str(row.get("id")), location)
        elif row.get("object_type") == "ability":
            for name in row.get("display_names", []):
                slot_key = name.get("inventory_key") if isinstance(name, dict) else None
                slot = inv_slots.get(slot_key)
                normalized_level = None if slot is None or slot["level"] in {None, 0} else slot["level"]
                if slot is None or slot["entity_key"] != key or slot["field"] not in ABILITY_FIELDS:
                    issues.append({"key": str(row.get("id")), "code": "inventory_display_name_mismatch", "source_location": location, "message": "display name is not backed by this ability's parsed name/tooltip slot"})
                elif name.get("role") != ABILITY_FIELD_ROLES[slot["field"]] or name.get("level") != normalized_level or name.get("data_pointer") != slot["data_pointer"]:
                    issues.append({"key": str(row.get("id")), "code": "inventory_display_role_mismatch", "source_location": location, "message": "display role/level/data_pointer differs from the verified object field slot", "field": slot["field"], "expected_role": ABILITY_FIELD_ROLES[slot["field"]], "actual_role": name.get("role"), "expected_level": normalized_level, "actual_level": name.get("level"), "expected_data_pointer": slot["data_pointer"], "actual_data_pointer": name.get("data_pointer")})
                else:
                    actual_slots.add(slot_key)
                    validate_slot_text(slot, name.get("text"), str(row.get("id")), location)

    for slot_key, slot in inv_slots.items():
        if slot["field"] not in {"uabi", "uhab"}:
            continue
        listed = {item.strip() for item in slot["value"].split(",") if item.strip()}
        claimed = claimed_direct_by_slot.get(slot_key, set())
        if listed != claimed:
            issues.append({"key": slot_key, "code": "inventory_ability_list_mismatch", "source_location": slot_key, "message": "direct bindings do not exactly cover the parsed ability-list value", "missing_rawcodes": sorted(listed - claimed), "extra_rawcodes": sorted(claimed - listed)})

    missing_entities = sorted(required_entities - set(actual_entities))
    extra_entities = sorted(set(actual_entities) - required_entities)
    required_slots = set(inv_slots)
    missing_slots = sorted(required_slots - actual_slots)
    if missing_entities or extra_entities:
        issues.append({"key": "inventory", "code": "inventory_entity_coverage_mismatch", "source_location": str(inventory["root"]), "message": "manifest entity coverage differs from parsed object inventory", "missing": missing_entities, "extra": extra_entities})
    if missing_slots:
        issues.append({"key": "inventory", "code": "inventory_slot_coverage_mismatch", "source_location": str(inventory["root"]), "message": "manifest omits parsed ability-list/description/name slots", "missing": missing_slots})
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory WC3 object slots needed by entity-link audit")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--encoding")
    args = parser.parse_args()
    try:
        result = build_inventory(args.root, args.encoding)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"files": len(result["files"]), "entities": len(result["entities"]), "slots": len(result["slots"]), "wts_entries": len(result["wts_entries"])}))
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
