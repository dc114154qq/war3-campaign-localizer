#!/usr/bin/env python3
"""Deterministic Warcraft III terminology evidence registry.

This tool stores evidence and resolves names for audit.  It never rewrites a
translation and deliberately refuses version/locale fallbacks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


DB_SCHEMA_VERSION = 2
BUNDLE_SCHEMA_VERSION = 1
EVIDENCE = {
    "official_reference",
    "verified_community_reference",
    "campaign_override",
    "unverified",
}
SOURCE_KINDS = {
    "official_reference": {"extracted_client_string", "blizzard_official_excerpt"},
    "verified_community_reference": {"verified_community_excerpt"},
    "campaign_override": {"campaign_term_decision"},
}
STRONG_EVIDENCE = EVIDENCE - {"unverified"}
SCOPES = {"global", "campaign", "map"}
PRODUCT = "warcraft_iii"
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
RAWCODE_RE = re.compile(r"^.{4}$", re.DOTALL)


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    source_key TEXT PRIMARY KEY,
    product TEXT NOT NULL CHECK (product = 'warcraft_iii'),
    source_kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    client_version TEXT,
    distribution TEXT,
    locale TEXT,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS entities (
    entity_key TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('global','campaign','map')),
    campaign_key TEXT,
    map_key TEXT,
    object_type TEXT NOT NULL,
    rawcode TEXT,
    stable_key TEXT NOT NULL,
    inherits_entity_key TEXT REFERENCES entities(entity_key),
    notes TEXT NOT NULL DEFAULT '',
    CHECK (rawcode IS NULL OR length(rawcode) = 4),
    CHECK (
      (scope_kind = 'global' AND campaign_key IS NULL AND map_key IS NULL) OR
      (scope_kind = 'campaign' AND campaign_key IS NOT NULL AND map_key IS NULL) OR
      (scope_kind = 'map' AND campaign_key IS NOT NULL AND map_key IS NOT NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS entity_identity_idx ON entities(
    scope_kind, ifnull(campaign_key,''), ifnull(map_key,''), object_type, stable_key
);
CREATE INDEX IF NOT EXISTS entity_rawcode_idx
ON entities(object_type, rawcode, scope_kind, campaign_key, map_key);
CREATE TABLE IF NOT EXISTS names (
    name_id INTEGER PRIMARY KEY,
    entity_key TEXT NOT NULL REFERENCES entities(entity_key),
    source_locale TEXT NOT NULL,
    source_name TEXT NOT NULL,
    target_locale TEXT NOT NULL,
    target_name TEXT NOT NULL,
    client_version TEXT,
    distribution TEXT NOT NULL,
    evidence_status TEXT NOT NULL CHECK (evidence_status IN
      ('official_reference','verified_community_reference','campaign_override','unverified')),
    source_key TEXT REFERENCES sources(source_key),
    entry_locator TEXT NOT NULL,
    name_role TEXT NOT NULL DEFAULT 'canonical',
    level INTEGER,
    form TEXT,
    canonical INTEGER NOT NULL DEFAULT 1 CHECK (canonical IN (0,1)),
    notes TEXT NOT NULL DEFAULT '',
    CHECK (level IS NULL OR level >= 0)
);
CREATE INDEX IF NOT EXISTS name_lookup_idx ON names(
    entity_key, target_locale, client_version, distribution,
    name_role, level, form, evidence_status, canonical
);
CREATE TABLE IF NOT EXISTS aliases (
    alias_id INTEGER PRIMARY KEY,
    entity_key TEXT NOT NULL REFERENCES entities(entity_key),
    locale TEXT NOT NULL,
    alias TEXT NOT NULL,
    alias_kind TEXT NOT NULL,
    evidence_status TEXT NOT NULL CHECK (evidence_status IN
      ('official_reference','verified_community_reference','campaign_override','unverified')),
    entry_locator TEXT NOT NULL,
    client_version TEXT,
    distribution TEXT,
    source_key TEXT REFERENCES sources(source_key),
    notes TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS alias_identity_idx ON aliases(
    entity_key, locale, alias, alias_kind, ifnull(client_version,''), ifnull(distribution,'')
);
"""


class RegistryError(ValueError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        connection.executescript(SCHEMA)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, DB_SCHEMA_VERSION}:
            raise RegistryError(f"unsupported database schema version {version}")
        connection.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)",
            ("schema_version", str(DB_SCHEMA_VERSION)),
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)",
            ("content_policy", "evidence_only_no_automatic_replacement"),
        )


def require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RegistryError(f"{location}: expected object")
    return value


def require_string(row: dict[str, Any], key: str, location: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{location}.{key}: non-empty string required")
    return value


def optional_string(row: dict[str, Any], key: str, location: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{location}.{key}: string or null required")
    return value


def reject_unknown(row: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(row) - allowed)
    if unknown:
        raise RegistryError(f"{location}: unknown fields {unknown}")


def validate_scope(row: dict[str, Any], location: str) -> tuple[str, str | None, str | None]:
    scope = require_object(row.get("scope"), f"{location}.scope")
    reject_unknown(scope, {"kind", "campaign", "map"}, f"{location}.scope")
    kind = require_string(scope, "kind", f"{location}.scope")
    campaign = optional_string(scope, "campaign", f"{location}.scope")
    map_key = optional_string(scope, "map", f"{location}.scope")
    if kind not in SCOPES:
        raise RegistryError(f"{location}.scope.kind: expected one of {sorted(SCOPES)}")
    valid = (
        (kind == "global" and campaign is None and map_key is None)
        or (kind == "campaign" and campaign is not None and map_key is None)
        or (kind == "map" and campaign is not None and map_key is not None)
    )
    if not valid:
        raise RegistryError(f"{location}.scope: campaign/map fields do not match scope kind")
    return kind, campaign, map_key


def validate_bundle(value: Any) -> dict[str, Any]:
    bundle = require_object(value, "bundle")
    reject_unknown(bundle, {"schema_version", "sources", "entities", "names", "aliases"}, "bundle")
    if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise RegistryError(f"bundle.schema_version must be {BUNDLE_SCHEMA_VERSION}")
    for key in ("sources", "entities", "names", "aliases"):
        if not isinstance(bundle.get(key, []), list):
            raise RegistryError(f"bundle.{key}: array required")
    return bundle


def normalized_hash(value: str, location: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise RegistryError(f"{location}: expected 64 hexadecimal SHA256 characters")
    return value.lower()


def verify_source_file(row: dict[str, Any], source_root: Path | None, location: str) -> None:
    if source_root is None:
        return
    locator = require_string(row, "locator", location)
    if "://" in locator:
        raise RegistryError(f"{location}.locator: URL locators are not hash-verifiable; save a small evidence file locally")
    locator_path = Path(locator)
    if locator_path.is_absolute() or ".." in locator_path.parts:
        raise RegistryError(f"{location}.locator: --source-root requires a safe relative locator")
    source_path = source_root / locator_path
    if not source_path.is_file():
        raise RegistryError(f"{location}.locator: source file not found under --source-root: {locator}")
    actual = hashlib.sha256(source_path.read_bytes()).hexdigest()
    expected = normalized_hash(require_string(row, "sha256", location), f"{location}.sha256")
    if actual != expected:
        raise RegistryError(f"{location}.sha256: source file hash mismatch for {locator}")


def load_evidence_entries(
    source: dict[str, Any], source_root: Path | None, location: str,
) -> dict[str, dict[str, Any]]:
    """Load the canonical, locator-addressable evidence excerpt format."""
    if source_root is None:
        raise RegistryError(f"{location}: --source-root is required to verify strong evidence content")
    verify_source_file(source, source_root, location)
    path = source_root / Path(source["locator"])
    try:
        value = read_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"{location}: evidence source must be UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("entries"), list) or not isinstance(value.get("source"), dict):
        raise RegistryError(f"{location}: evidence source requires schema_version 1, a source object, and an entries array")
    unknown = sorted(set(value) - {"schema_version", "entries", "notes", "source_capture", "source"})
    if unknown:
        raise RegistryError(f"{location}: evidence source has unknown fields {unknown}")
    expected_source = {
        key: source[key]
        for key in ("source_key", "product", "source_kind", "client_version", "distribution", "locale")
    }
    source_mismatches = {
        key: {"expected": expected, "actual": value["source"].get(key)}
        for key, expected in expected_source.items() if value["source"].get(key) != expected
    }
    if source_mismatches:
        raise RegistryError(f"{location}: evidence source identity mismatch: {source_mismatches}")
    entries: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(value["entries"]):
        if not isinstance(raw, dict) or not isinstance(raw.get("entry_locator"), str) or not raw["entry_locator"]:
            raise RegistryError(f"{location}: entries[{index}] requires a non-empty entry_locator")
        locator = raw["entry_locator"]
        if locator in entries:
            raise RegistryError(f"{location}: duplicate evidence entry_locator {locator!r}")
        entries[locator] = raw
    return entries


def bundle_from_evidence(path: Path, source_root: Path) -> dict[str, Any]:
    """Convert one canonical extracted-evidence JSON file into an import bundle."""
    root = source_root.resolve()
    resolved = path.resolve()
    try:
        locator = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise RegistryError("import-evidence input must be located under --source-root") from exc
    value = read_json(resolved)
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("source"), dict) or not isinstance(value.get("entries"), list):
        raise RegistryError("canonical evidence requires schema_version 1, source object, and entries array")
    source_meta = value["source"]
    allowed_source = {"source_key", "product", "source_kind", "client_version", "distribution", "locale", "notes"}
    unknown_source = sorted(set(source_meta) - allowed_source)
    if unknown_source:
        raise RegistryError(f"evidence.source has unknown fields {unknown_source}")
    source_key = require_string(source_meta, "source_key", "evidence.source")
    source = {
        **source_meta,
        "locator": locator,
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }
    entities: dict[str, dict[str, Any]] = {}
    names: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    for index, raw in enumerate(value["entries"]):
        row = require_object(raw, f"evidence.entries[{index}]")
        entity_key = require_string(row, "entity_key", f"evidence.entries[{index}]")
        entity = {
            "entity_key": entity_key,
            "scope": require_object(row.get("scope"), f"evidence.entries[{index}].scope"),
            "object_type": require_string(row, "object_type", f"evidence.entries[{index}]"),
            "rawcode": row.get("rawcode"),
            "stable_key": require_string(row, "stable_key", f"evidence.entries[{index}]"),
            "inherits_entity_key": row.get("inherits_entity_key"),
        }
        previous = entities.get(entity_key)
        if previous is not None and previous != entity:
            raise RegistryError(f"evidence.entries[{index}]: conflicting repeated entity definition")
        entities[entity_key] = entity
        common = {
            "entity_key": entity_key,
            "evidence_status": require_string(row, "evidence_status", f"evidence.entries[{index}]"),
            "source_key": source_key,
            "entry_locator": require_string(row, "entry_locator", f"evidence.entries[{index}]"),
            "client_version": row.get("client_version"),
            "distribution": row.get("distribution"),
        }
        kind = row.get("record_kind")
        if kind == "name":
            names.append({
                **common,
                "source_locale": row.get("source_locale"), "source_name": row.get("source_name"),
                "target_locale": row.get("target_locale"), "target_name": row.get("target_name"),
                "name_role": row.get("name_role", "canonical"), "level": row.get("level"),
                "form": row.get("form"), "canonical": row.get("canonical", True),
            })
        elif kind == "alias":
            aliases.append({
                **common, "locale": row.get("locale"), "alias": row.get("alias"),
                "alias_kind": row.get("alias_kind"),
            })
        else:
            raise RegistryError(f"evidence.entries[{index}].record_kind must be name or alias")
    return {"schema_version": 1, "sources": [source], "entities": list(entities.values()), "names": names, "aliases": aliases}


def import_evidence(db_path: Path, evidence_path: Path, source_root: Path) -> dict[str, int]:
    bundle = bundle_from_evidence(evidence_path, source_root)
    initialize(db_path)
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        result = insert_bundle(connection, bundle, source_root)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def verify_evidence_content(
    *, record_kind: str, row: dict[str, Any], entity: dict[str, Any],
    source: dict[str, Any], source_root: Path | None,
    cache: dict[str, dict[str, dict[str, Any]]], location: str,
) -> None:
    source_key = source["source_key"]
    if source_key not in cache:
        cache[source_key] = load_evidence_entries(source, source_root, f"source:{source_key}")
    locator = row["entry_locator"]
    evidence = cache[source_key].get(locator)
    if evidence is None:
        raise RegistryError(f"{location}: entry_locator {locator!r} is absent from source evidence")
    common = {
        "record_kind": record_kind,
        "entry_locator": locator,
        "product": PRODUCT,
        "entity_key": entity["entity_key"],
        "object_type": entity["object_type"],
        "rawcode": entity["rawcode"],
        "stable_key": entity["stable_key"],
        "scope": {
            "kind": entity["scope_kind"],
            **({"campaign": entity["campaign_key"]} if entity["campaign_key"] is not None else {}),
            **({"map": entity["map_key"]} if entity["map_key"] is not None else {}),
        },
        "client_version": row["client_version"],
        "distribution": row["distribution"],
        "evidence_status": row["evidence_status"],
    }
    if record_kind == "name":
        common.update({
            "source_locale": row["source_locale"], "source_name": row["source_name"],
            "target_locale": row["target_locale"], "target_name": row["target_name"],
            "name_role": row["name_role"], "level": row["level"], "form": row["form"],
        })
    else:
        common.update({
            "locale": row["locale"], "alias": row["alias"], "alias_kind": row["alias_kind"],
        })
    mismatches = {
        key: {"expected": expected, "actual": evidence.get(key)}
        for key, expected in common.items() if evidence.get(key) != expected
    }
    if mismatches:
        raise RegistryError(f"{location}: evidence entry content mismatch: {mismatches}")


def insert_bundle(connection: sqlite3.Connection, bundle: dict[str, Any], source_root: Path | None) -> dict[str, int]:
    sources = bundle.get("sources", [])
    entities = bundle.get("entities", [])
    names = bundle.get("names", [])
    aliases = bundle.get("aliases", [])
    if sources and source_root is None:
        raise RegistryError("--source-root is required whenever a bundle imports source records")
    known_source_keys = {row[0] for row in connection.execute("SELECT source_key FROM sources")}
    known_entity_keys = {row[0] for row in connection.execute("SELECT entity_key FROM entities")}

    for index, raw in enumerate(sources):
        location = f"sources[{index}]"
        row = require_object(raw, location)
        reject_unknown(
            row,
            {"source_key", "product", "source_kind", "locator", "sha256", "client_version", "distribution", "locale", "notes"},
            location,
        )
        source_key = require_string(row, "source_key", location)
        product = require_string(row, "product", location)
        if product != PRODUCT:
            raise RegistryError(f"{location}.product: must be {PRODUCT!r}; WoW and other products are not accepted")
        verify_source_file(row, source_root, location)
        values = (
            source_key,
            product,
            require_string(row, "source_kind", location),
            require_string(row, "locator", location),
            normalized_hash(require_string(row, "sha256", location), f"{location}.sha256"),
            optional_string(row, "client_version", location),
            optional_string(row, "distribution", location),
            optional_string(row, "locale", location),
            str(row.get("notes", "")),
        )
        try:
            connection.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?)", values)
        except sqlite3.IntegrityError as exc:
            raise RegistryError(f"{location}: duplicate or conflicting source {source_key!r}: {exc}") from exc
        known_source_keys.add(source_key)

    source_metadata = {
        row["source_key"]: row
        for row in connection.execute("SELECT * FROM sources")
    }
    evidence_cache: dict[str, dict[str, dict[str, Any]]] = {}

    pending = [require_object(raw, f"entities[{i}]") for i, raw in enumerate(entities)]
    while pending:
        progressed = False
        for row in pending[:]:
            index = entities.index(row)
            location = f"entities[{index}]"
            reject_unknown(row, {"entity_key", "scope", "object_type", "rawcode", "stable_key", "inherits_entity_key", "notes"}, location)
            parent = optional_string(row, "inherits_entity_key", location)
            if parent and parent not in known_entity_keys:
                continue
            kind, campaign, map_key = validate_scope(row, location)
            rawcode = optional_string(row, "rawcode", location)
            if rawcode is not None and not RAWCODE_RE.fullmatch(rawcode):
                raise RegistryError(f"{location}.rawcode: rawcode must contain exactly four characters")
            entity_key = require_string(row, "entity_key", location)
            object_type = require_string(row, "object_type", location)
            if parent:
                parent_row = connection.execute("SELECT * FROM entities WHERE entity_key=?", (parent,)).fetchone()
                if parent_row["object_type"] != object_type:
                    raise RegistryError(f"{location}: inherited entity must have the same object_type as its parent")
                allowed_parent_scope = (
                    parent_row["scope_kind"] == "global"
                    or (
                        kind in {"campaign", "map"}
                        and parent_row["scope_kind"] == "campaign"
                        and parent_row["campaign_key"] == campaign
                    )
                    or (
                        kind == "map"
                        and parent_row["scope_kind"] == "map"
                        and parent_row["campaign_key"] == campaign
                        and parent_row["map_key"] == map_key
                    )
                )
                if not allowed_parent_scope:
                    raise RegistryError(f"{location}: inheritance may not cross campaign/map scope")
            values = (
                entity_key, kind, campaign, map_key,
                object_type, rawcode,
                require_string(row, "stable_key", location), parent, str(row.get("notes", "")),
            )
            try:
                connection.execute("INSERT INTO entities VALUES (?,?,?,?,?,?,?,?,?)", values)
            except sqlite3.IntegrityError as exc:
                raise RegistryError(f"{location}: duplicate or conflicting entity {entity_key!r}: {exc}") from exc
            known_entity_keys.add(entity_key)
            pending.remove(row)
            progressed = True
        if not progressed:
            unresolved = [row.get("inherits_entity_key") for row in pending]
            raise RegistryError(f"entities: missing or cyclic inheritance parents: {unresolved}")

    for index, raw in enumerate(names):
        location = f"names[{index}]"
        row = require_object(raw, location)
        reject_unknown(
            row,
            {"entity_key", "source_locale", "source_name", "target_locale", "target_name", "client_version", "distribution", "evidence_status", "source_key", "entry_locator", "name_role", "level", "form", "canonical", "notes"},
            location,
        )
        entity_key = require_string(row, "entity_key", location)
        if entity_key not in known_entity_keys:
            raise RegistryError(f"{location}.entity_key: unknown entity {entity_key!r}")
        evidence = require_string(row, "evidence_status", location)
        if evidence not in EVIDENCE:
            raise RegistryError(f"{location}.evidence_status: expected one of {sorted(EVIDENCE)}")
        source_key = optional_string(row, "source_key", location)
        if evidence in STRONG_EVIDENCE and not source_key:
            raise RegistryError(f"{location}.source_key: required for {evidence}")
        if source_key and source_key not in known_source_keys:
            raise RegistryError(f"{location}.source_key: unknown source {source_key!r}")
        entry_locator = require_string(row, "entry_locator", location)
        if evidence in STRONG_EVIDENCE and source_metadata[source_key]["source_kind"] not in SOURCE_KINDS[evidence]:
            raise RegistryError(f"{location}: {evidence} is incompatible with source_kind {source_metadata[source_key]['source_kind']!r}")
        if evidence == "official_reference" and source_metadata[source_key]["source_kind"] == "blizzard_official_excerpt":
            entity_rawcode = connection.execute("SELECT rawcode FROM entities WHERE entity_key=?", (entity_key,)).fetchone()[0]
            if entity_rawcode is not None:
                raise RegistryError(f"{location}: a Blizzard webpage excerpt cannot establish a rawcode; use a rawcode-free stable entity key")
        client_version = optional_string(row, "client_version", location)
        distribution = require_string(row, "distribution", location)
        target_locale = require_string(row, "target_locale", location)
        if evidence in STRONG_EVIDENCE and client_version is None:
            raise RegistryError(f"{location}.client_version: exact version required for {evidence}")
        if evidence in STRONG_EVIDENCE:
            source = source_metadata[source_key]
            expected = (client_version, distribution, target_locale)
            actual = (source["client_version"], source["distribution"], source["locale"])
            if actual != expected:
                raise RegistryError(
                    f"{location}: evidenced name version/distribution/target locale {expected} "
                    f"does not match source evidence {actual}"
                )
            entity = dict(connection.execute("SELECT * FROM entities WHERE entity_key=?", (entity_key,)).fetchone())
            verify_evidence_content(
                record_kind="name", row={
                    **row, "client_version": client_version, "distribution": distribution,
                    "target_locale": target_locale, "name_role": str(row.get("name_role", "canonical")),
                    "level": row.get("level"), "form": row.get("form"),
                }, entity=entity, source=dict(source), source_root=source_root,
                cache=evidence_cache, location=location,
            )
        level = row.get("level")
        if level is not None and (not isinstance(level, int) or isinstance(level, bool) or level < 0):
            raise RegistryError(f"{location}.level: non-negative integer or null required")
        canonical = row.get("canonical", True)
        if not isinstance(canonical, bool):
            raise RegistryError(f"{location}.canonical: boolean required")
        identity = (
            entity_key,
            target_locale,
            client_version,
            distribution,
            str(row.get("name_role", "canonical")),
            level,
            optional_string(row, "form", location),
            evidence,
            1 if canonical else 0,
        )
        if canonical:
            existing = connection.execute(
                """SELECT DISTINCT target_name FROM names WHERE entity_key=? AND target_locale=?
                   AND client_version IS ? AND distribution=? AND name_role=? AND level IS ?
                   AND form IS ? AND evidence_status=? AND canonical=?""",
                identity,
            ).fetchall()
            targets = {item[0] for item in existing} | {require_string(row, "target_name", location)}
            if len(targets) > 1:
                raise RegistryError(f"{location}: conflicting canonical targets for the same identity: {sorted(targets)}")
        connection.execute(
            """INSERT INTO names(entity_key,source_locale,source_name,target_locale,target_name,
               client_version,distribution,evidence_status,source_key,entry_locator,name_role,level,form,canonical,notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entity_key,
                require_string(row, "source_locale", location),
                require_string(row, "source_name", location),
                identity[1], require_string(row, "target_name", location), identity[2], identity[3],
                evidence, source_key, entry_locator, identity[4], level, identity[6], identity[8], str(row.get("notes", "")),
            ),
        )

    for index, raw in enumerate(aliases):
        location = f"aliases[{index}]"
        row = require_object(raw, location)
        reject_unknown(row, {"entity_key", "locale", "alias", "alias_kind", "evidence_status", "entry_locator", "client_version", "distribution", "source_key", "notes"}, location)
        entity_key = require_string(row, "entity_key", location)
        if entity_key not in known_entity_keys:
            raise RegistryError(f"{location}.entity_key: unknown entity {entity_key!r}")
        source_key = optional_string(row, "source_key", location)
        evidence = require_string(row, "evidence_status", location)
        if evidence not in EVIDENCE:
            raise RegistryError(f"{location}.evidence_status: expected one of {sorted(EVIDENCE)}")
        if evidence in STRONG_EVIDENCE and not source_key:
            raise RegistryError(f"{location}.source_key: required for {evidence}")
        if source_key and source_key not in known_source_keys:
            raise RegistryError(f"{location}.source_key: unknown source {source_key!r}")
        entry_locator = require_string(row, "entry_locator", location)
        if evidence in STRONG_EVIDENCE and source_metadata[source_key]["source_kind"] not in SOURCE_KINDS[evidence]:
            raise RegistryError(f"{location}: {evidence} is incompatible with source_kind {source_metadata[source_key]['source_kind']!r}")
        if evidence == "official_reference" and source_metadata[source_key]["source_kind"] == "blizzard_official_excerpt":
            entity_rawcode = connection.execute("SELECT rawcode FROM entities WHERE entity_key=?", (entity_key,)).fetchone()[0]
            if entity_rawcode is not None:
                raise RegistryError(f"{location}: a Blizzard webpage excerpt cannot establish a rawcode; use a rawcode-free stable entity key")
        locale = require_string(row, "locale", location)
        client_version = optional_string(row, "client_version", location)
        distribution = optional_string(row, "distribution", location)
        if evidence in STRONG_EVIDENCE and (client_version is None or distribution is None):
            raise RegistryError(f"{location}: exact client_version and distribution required for {evidence}")
        if evidence in STRONG_EVIDENCE:
            source = source_metadata[source_key]
            expected = (client_version, distribution, locale)
            actual = (source["client_version"], source["distribution"], source["locale"])
            if actual != expected:
                raise RegistryError(
                    f"{location}: evidenced alias version/distribution/locale {expected} "
                    f"does not match source evidence {actual}"
                )
            entity = dict(connection.execute("SELECT * FROM entities WHERE entity_key=?", (entity_key,)).fetchone())
            verify_evidence_content(
                record_kind="alias", row={
                    **row, "client_version": client_version, "distribution": distribution,
                    "locale": locale,
                }, entity=entity, source=dict(source), source_root=source_root,
                cache=evidence_cache, location=location,
            )
        try:
            connection.execute(
                """INSERT INTO aliases(entity_key,locale,alias,alias_kind,evidence_status,entry_locator,client_version,distribution,source_key,notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    entity_key, locale, require_string(row, "alias", location),
                    require_string(row, "alias_kind", location), evidence, entry_locator, client_version,
                    distribution, source_key, str(row.get("notes", "")),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise RegistryError(f"{location}: duplicate alias: {exc}") from exc
    return {"sources": len(sources), "entities": len(entities), "names": len(names), "aliases": len(aliases)}


def import_bundle(db_path: Path, bundle_path: Path, source_root: Path | None = None) -> dict[str, int]:
    initialize(db_path)
    bundle = validate_bundle(read_json(bundle_path))
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        result = insert_bundle(connection, bundle, source_root)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def entity_candidates(
    connection: sqlite3.Connection,
    object_type: str,
    rawcode: str | None,
    stable_key: str | None,
    campaign: str | None,
    map_key: str | None,
) -> list[sqlite3.Row]:
    if not rawcode and not stable_key:
        raise RegistryError("query requires --rawcode or --stable-key")
    clauses = ["object_type=?"]
    values: list[Any] = [object_type]
    if rawcode:
        clauses.append("rawcode=?")
        values.append(rawcode)
    if stable_key:
        clauses.append("stable_key=?")
        values.append(stable_key)
    rows = connection.execute(
        f"SELECT * FROM entities WHERE {' AND '.join(clauses)} ORDER BY entity_key", values
    ).fetchall()
    eligible: list[tuple[int, sqlite3.Row]] = []
    for row in rows:
        rank = -1
        if row["scope_kind"] == "map" and campaign == row["campaign_key"] and map_key == row["map_key"]:
            rank = 3
        elif row["scope_kind"] == "campaign" and campaign == row["campaign_key"]:
            rank = 2
        elif row["scope_kind"] == "global":
            rank = 1
        if rank >= 0:
            eligible.append((rank, row))
    if not eligible:
        return []
    best = max(rank for rank, _ in eligible)
    return [row for rank, row in eligible if rank == best]


def resolve_name(
    db_path: Path,
    *,
    object_type: str,
    target_locale: str,
    source_locale: str | None = None,
    client_version: str | None,
    distribution: str | None,
    rawcode: str | None = None,
    stable_key: str | None = None,
    campaign: str | None = None,
    map_key: str | None = None,
    name_role: str = "canonical",
    level: int | None = None,
    form: str | None = None,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        entities = entity_candidates(connection, object_type, rawcode, stable_key, campaign, map_key)
        result: dict[str, Any] = {
            "status": "no_match",
            "selected": None,
            "reason": "entity_not_found",
            "entity_candidates": [dict(row) for row in entities],
            "candidates": [],
        }
        if len(entities) != 1:
            if len(entities) > 1:
                result.update(status="ambiguous", reason="multiple_entities_at_same_scope")
            return result
        requested_entity = entities[0]
        current = requested_entity
        inheritance_chain: list[str] = []
        alternate_locale_candidates: list[dict[str, Any]] = []
        alternate_source_candidates: list[dict[str, Any]] = []
        while current is not None:
            if current["entity_key"] in inheritance_chain:
                result.update(status="ambiguous", reason="cyclic_entity_inheritance")
                return result
            inheritance_chain.append(current["entity_key"])
            source_clause = " AND n.source_locale=?" if source_locale else ""
            row_parameters: tuple[Any, ...] = (current["entity_key"], target_locale, name_role, level, form)
            if source_locale:
                row_parameters += (source_locale,)
            rows = connection.execute(
                f"""SELECT n.*, s.locator AS source_locator, s.sha256 AS source_sha256,
                          s.product AS source_product, e.scope_kind, e.campaign_key, e.map_key
                   FROM names n JOIN entities e USING(entity_key)
                   LEFT JOIN sources s USING(source_key)
                   WHERE n.entity_key=? AND n.target_locale=? AND n.name_role=?
                     AND n.level IS ? AND n.form IS ? AND n.canonical=1
                     {source_clause}
                   ORDER BY n.evidence_status,n.client_version,n.target_name,n.name_id""",
                row_parameters,
            ).fetchall()
            if source_locale:
                alternate_source_candidates.extend(
                    dict(row)
                    for row in connection.execute(
                        """SELECT n.*, s.locator AS source_locator, s.sha256 AS source_sha256,
                                  s.product AS source_product, e.scope_kind, e.campaign_key, e.map_key
                           FROM names n JOIN entities e USING(entity_key)
                           LEFT JOIN sources s USING(source_key)
                           WHERE n.entity_key=? AND n.target_locale=? AND n.source_locale<>?
                             AND n.name_role=? AND n.level IS ? AND n.form IS ? AND n.canonical=1
                           ORDER BY n.source_locale,n.evidence_status,n.client_version,n.target_name,n.name_id""",
                        (current["entity_key"], target_locale, source_locale, name_role, level, form),
                    )
                )
            alternate_locale_candidates.extend(
                dict(row)
                for row in connection.execute(
                    """SELECT n.*, s.locator AS source_locator, s.sha256 AS source_sha256,
                              s.product AS source_product, e.scope_kind, e.campaign_key, e.map_key
                       FROM names n JOIN entities e USING(entity_key)
                       LEFT JOIN sources s USING(source_key)
                       WHERE n.entity_key=? AND n.target_locale<>? AND n.name_role=?
                         AND n.level IS ? AND n.form IS ? AND n.canonical=1
                       ORDER BY n.target_locale,n.evidence_status,n.client_version,n.target_name,n.name_id""",
                    (current["entity_key"], target_locale, name_role, level, form),
                )
            )
            if rows:
                result["candidates"] = [dict(row) for row in rows]
                result["inheritance_chain"] = inheritance_chain
                if not client_version or not distribution:
                    result.update(status="ambiguous", reason="client_version_and_distribution_required")
                    return result
                exact = [row for row in rows if row["client_version"] == client_version and row["distribution"] == distribution]
                scoped_override = [row for row in exact if row["evidence_status"] == "campaign_override" and current["scope_kind"] != "global"]
                priority = [
                    [row for row in exact if row["evidence_status"] == "official_reference"],
                    scoped_override,
                    [row for row in exact if row["evidence_status"] == "verified_community_reference"],
                ]
                chosen: list[sqlite3.Row] = next((group for group in priority if group), [])
                if not chosen:
                    result.update(status="ambiguous", reason="no_exact_version_distribution_evidence")
                    return result
                targets = {row["target_name"] for row in chosen}
                if len(targets) != 1:
                    result.update(status="ambiguous", reason="conflicting_targets")
                    return result
                selected = dict(chosen[0])
                selected["supporting_source_count"] = len(chosen)
                selected["resolved_for_entity_key"] = requested_entity["entity_key"]
                selected["inherited"] = current["entity_key"] != requested_entity["entity_key"]
                result.update(status="selected", reason="exact_evidence_match", selected=selected)
                return result
            parent_key = current["inherits_entity_key"]
            current = (
                connection.execute("SELECT * FROM entities WHERE entity_key=?", (parent_key,)).fetchone()
                if parent_key else None
            )
        result["inheritance_chain"] = inheritance_chain
        if alternate_source_candidates:
            result.update(
                status="ambiguous",
                reason="no_exact_source_locale",
                candidates=alternate_source_candidates,
            )
        elif alternate_locale_candidates:
            result.update(
                status="ambiguous",
                reason="no_exact_target_locale",
                candidates=alternate_locale_candidates,
            )
        else:
            result["reason"] = "name_not_found_for_exact_locale_role_level_form"
        return result


def database_summary(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as connection:
        return {
            "schema_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "sources": connection.execute("SELECT count(*) FROM sources").fetchone()[0],
            "entities": connection.execute("SELECT count(*) FROM entities").fetchone()[0],
            "names": connection.execute("SELECT count(*) FROM names").fetchone()[0],
            "aliases": connection.execute("SELECT count(*) FROM aliases").fetchone()[0],
            "evidence": {
                row[0]: row[1]
                for row in connection.execute("SELECT evidence_status,count(*) FROM names GROUP BY evidence_status ORDER BY evidence_status")
            },
        }


def validate_database(db_path: Path, source_root: Path) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    with connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != DB_SCHEMA_VERSION:
            issues.append({"location": "database", "issue": f"schema version {version} != {DB_SCHEMA_VERSION}"})
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            issues.append({"location": "database", "issue": f"integrity_check: {integrity}"})
        for row in connection.execute("PRAGMA foreign_key_check"):
            issues.append({"location": "database", "issue": f"foreign key violation: {tuple(row)}"})
        required_columns = {
            "sources": {"source_key", "product", "source_kind", "locator", "sha256", "client_version", "distribution", "locale"},
            "entities": {"entity_key", "scope_kind", "campaign_key", "map_key", "object_type", "rawcode", "stable_key", "inherits_entity_key"},
            "names": {"entity_key", "source_locale", "source_name", "target_locale", "target_name", "client_version", "distribution", "evidence_status", "source_key", "entry_locator", "name_role", "level", "form", "canonical"},
            "aliases": {"entity_key", "locale", "alias", "alias_kind", "evidence_status", "entry_locator", "client_version", "distribution", "source_key"},
        }
        for table, required in required_columns.items():
            actual = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            missing = sorted(required - actual)
            if missing:
                issues.append({"location": table, "issue": f"missing schema columns: {missing}"})
        if issues:
            return {"passed": False, "issues": issues}

        sources = {row["source_key"]: row for row in connection.execute("SELECT * FROM sources")}
        for key, row in sources.items():
            try:
                verify_source_file(dict(row), source_root, f"source:{key}")
            except RegistryError as exc:
                issues.append({"location": f"source:{key}", "issue": str(exc)})

        evidence_cache: dict[str, dict[str, dict[str, Any]]] = {}
        for table in ("names", "aliases"):
            locale_column = "target_locale" if table == "names" else "locale"
            for row in connection.execute(f"SELECT * FROM {table}"):
                evidence = row["evidence_status"]
                if evidence not in STRONG_EVIDENCE:
                    continue
                source = sources.get(row["source_key"])
                location = f"{table}:{row['name_id' if table == 'names' else 'alias_id']}"
                if source is None:
                    issues.append({"location": location, "issue": "strong evidence row has no source"})
                    continue
                if not row["client_version"] or not row["distribution"]:
                    issues.append({"location": location, "issue": "strong evidence requires exact client_version and distribution"})
                if source["source_kind"] not in SOURCE_KINDS[evidence]:
                    issues.append({"location": location, "issue": "evidence status/source_kind mismatch"})
                if evidence == "official_reference" and source["source_kind"] == "blizzard_official_excerpt":
                    rawcode = connection.execute("SELECT rawcode FROM entities WHERE entity_key=?", (row["entity_key"],)).fetchone()[0]
                    if rawcode is not None:
                        issues.append({"location": location, "issue": "webpage evidence may not establish a rawcode entity"})
                expected = (row["client_version"], row["distribution"], row[locale_column])
                actual = (source["client_version"], source["distribution"], source["locale"])
                if expected != actual:
                    issues.append({"location": location, "issue": "version/distribution/locale differs from source"})
                if not row["entry_locator"]:
                    issues.append({"location": location, "issue": "missing entry_locator"})
                try:
                    entity = connection.execute("SELECT * FROM entities WHERE entity_key=?", (row["entity_key"],)).fetchone()
                    if entity is None:
                        raise RegistryError("evidence row refers to a missing entity")
                    verify_evidence_content(
                        record_kind="name" if table == "names" else "alias",
                        row=dict(row), entity=dict(entity), source=dict(source),
                        source_root=source_root, cache=evidence_cache, location=location,
                    )
                except RegistryError as exc:
                    issues.append({"location": location, "issue": str(exc)})

        conflicts = connection.execute(
            """SELECT entity_key,target_locale,client_version,distribution,name_role,level,form,
                      evidence_status,count(DISTINCT target_name) AS target_count
               FROM names WHERE canonical=1
               GROUP BY entity_key,target_locale,client_version,distribution,name_role,level,form,evidence_status
               HAVING target_count > 1"""
        ).fetchall()
        for row in conflicts:
            issues.append({"location": f"entity:{row['entity_key']}", "issue": "conflicting canonical targets in database"})

        entities = {row["entity_key"]: row for row in connection.execute("SELECT * FROM entities")}
        for key, row in entities.items():
            parent_key = row["inherits_entity_key"]
            if not parent_key:
                continue
            parent = entities.get(parent_key)
            if parent is None or parent["object_type"] != row["object_type"]:
                issues.append({"location": f"entity:{key}", "issue": "invalid inheritance parent/type"})
                continue
            allowed = (
                parent["scope_kind"] == "global"
                or (row["scope_kind"] in {"campaign", "map"} and parent["scope_kind"] == "campaign" and parent["campaign_key"] == row["campaign_key"])
                or (row["scope_kind"] == "map" and parent["scope_kind"] == "map" and parent["campaign_key"] == row["campaign_key"] and parent["map_key"] == row["map_key"])
            )
            if not allowed:
                issues.append({"location": f"entity:{key}", "issue": "inheritance crosses campaign/map scope"})
        return {"passed": not issues, "issues": issues, **database_summary(db_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Warcraft III terminology evidence registry")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create an empty registry without invented seed terms")
    init.add_argument("--db", type=Path, required=True)
    load = sub.add_parser("import-json", help="transactionally import a version-1 evidence bundle")
    load.add_argument("--db", type=Path, required=True)
    load.add_argument("--input", type=Path, required=True)
    load.add_argument("--source-root", type=Path)
    evidence_load = sub.add_parser("import-evidence", help="import one canonical extracted-evidence JSON file")
    evidence_load.add_argument("--db", type=Path, required=True)
    evidence_load.add_argument("--input", type=Path, required=True)
    evidence_load.add_argument("--source-root", type=Path, required=True)
    query = sub.add_parser("query", help="resolve one exact entity/name identity as JSON")
    query.add_argument("--db", type=Path, required=True)
    query.add_argument("--object-type", required=True)
    query.add_argument("--rawcode")
    query.add_argument("--stable-key")
    query.add_argument("--campaign")
    query.add_argument("--map", dest="map_key")
    query.add_argument("--target-locale", required=True)
    query.add_argument("--source-locale", required=True)
    query.add_argument("--client-version")
    query.add_argument("--distribution")
    query.add_argument("--name-role", default="canonical")
    query.add_argument("--level", type=int)
    query.add_argument("--form")
    summary = sub.add_parser("summary")
    summary.add_argument("--db", type=Path, required=True)
    validate = sub.add_parser("validate", help="recheck schema, FK, evidence files, metadata, and inheritance")
    validate.add_argument("--db", type=Path, required=True)
    validate.add_argument("--source-root", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            initialize(args.db)
            result = database_summary(args.db)
        elif args.command == "import-json":
            result = import_bundle(args.db, args.input, args.source_root)
        elif args.command == "import-evidence":
            result = import_evidence(args.db, args.input, args.source_root)
        elif args.command == "summary":
            result = database_summary(args.db)
        elif args.command == "validate":
            result = validate_database(args.db, args.source_root)
        else:
            result = resolve_name(
                args.db, object_type=args.object_type, rawcode=args.rawcode,
                stable_key=args.stable_key, campaign=args.campaign, map_key=args.map_key,
                target_locale=args.target_locale, source_locale=args.source_locale, client_version=args.client_version,
                distribution=args.distribution, name_role=args.name_role, level=args.level, form=args.form,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if args.command == "query" and result["status"] != "selected":
            return 2
        if args.command == "validate" and not result["passed"]:
            return 1
        return 0
    except (OSError, json.JSONDecodeError, sqlite3.Error, RegistryError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
