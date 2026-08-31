from __future__ import annotations

import argparse
import copy
import json
import re
import struct
from pathlib import Path

from campaign_inventory import parse_w3f
from wts_tool import read_text, write_json


SCRIPT_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
VISIBLE_OBJECT_FIELDS = {
    "unam",
    "unsf",
    "upro",
    "utip",
    "utub",
    "uhot",
    "uawt",
    "urev",
    "anam",
    "ansf",
    "atp1",
    "aub1",
    "aret",
    "arut",
    "ahky",
    "auhk",
    "fnam",
    "fnsf",
    "ftip",
    "fube",
    "gnam",
    "gnsf",
    "gtp1",
    "gub1",
    "ghk1",
    "ides",
    "utip",
    "utub",
    "ihot",
    "bnam",
    "dnam",
}


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, size: int) -> bytes:
        value = self.data[self.pos : self.pos + size]
        if len(value) != size:
            raise ValueError(f"unexpected EOF at {self.pos}")
        self.pos += size
        return value

    def i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def f32_bytes(self) -> bytes:
        return self.read(4)

    def zbytes(self) -> bytes:
        try:
            end = self.data.index(0, self.pos)
        except ValueError as exc:
            raise ValueError(f"unterminated string at {self.pos}") from exc
        value = self.data[self.pos:end]
        self.pos = end + 1
        return value


def parse_object(path: Path, has_levels: bool) -> dict:
    reader = Reader(path.read_bytes())
    result = {"version": reader.i32(), "tables": []}
    for _ in range(2):
        count = reader.i32()
        if count < 0 or count > 1_000_000:
            raise ValueError(f"implausible object count {count}")
        table = []
        for _ in range(count):
            obj = {
                "old_id": reader.read(4),
                "new_id": reader.read(4),
                "mods": [],
            }
            mod_count = reader.i32()
            if mod_count < 0 or mod_count > 1_000_000:
                raise ValueError(f"implausible modification count {mod_count}")
            for _ in range(mod_count):
                field = reader.read(4)
                value_type = reader.i32()
                level = reader.i32() if has_levels else 0
                data_pointer = reader.i32() if has_levels else 0
                if value_type == 0:
                    value = reader.read(4)
                elif value_type in (1, 2):
                    value = reader.f32_bytes()
                elif value_type == 3:
                    value = reader.zbytes()
                else:
                    raise ValueError(
                        f"unknown object value type {value_type} at {reader.pos}"
                    )
                obj["mods"].append(
                    {
                        "field": field,
                        "type": value_type,
                        "level": level,
                        "data_pointer": data_pointer,
                        "value": value,
                        "end_id": reader.read(4),
                    }
                )
            table.append(obj)
        result["tables"].append(table)
    if reader.pos != len(reader.data):
        raise ValueError(f"{len(reader.data) - reader.pos} trailing bytes")
    return result


def parse_object_auto(path: Path) -> tuple[dict, bool]:
    preferred = path.suffix.lower() in {".w3a", ".w3d", ".w3q"}
    failures = []
    for has_levels in (preferred, not preferred):
        try:
            return parse_object(path, has_levels), has_levels
        except Exception as exc:
            failures.append(f"has_levels={has_levels}: {exc}")
    raise ValueError(f"cannot parse {path}: {'; '.join(failures)}")


def object_command(args: argparse.Namespace) -> None:
    source, source_levels = parse_object_auto(Path(args.source))
    localized, localized_levels = parse_object_auto(Path(args.localized))
    errors = []
    changes = []
    allowed_fields = VISIBLE_OBJECT_FIELDS | set(args.allow_field)
    if source_levels != localized_levels:
        errors.append({"error": "object file layout type differs"})
    if source["version"] != localized["version"]:
        errors.append({"error": "object format version differs"})
    if len(source["tables"]) != len(localized["tables"]):
        errors.append({"error": "object table count differs"})

    for table_index, (source_table, localized_table) in enumerate(
        zip(source["tables"], localized["tables"])
    ):
        if len(source_table) != len(localized_table):
            errors.append(
                {
                    "location": f"table/{table_index}",
                    "error": "object count differs",
                }
            )
            continue
        for object_index, (source_obj, localized_obj) in enumerate(
            zip(source_table, localized_table)
        ):
            location = f"table/{table_index}/object/{object_index}"
            for key in ("old_id", "new_id"):
                if source_obj[key] != localized_obj[key]:
                    errors.append(
                        {"location": location, "error": f"{key} differs"}
                    )
            if len(source_obj["mods"]) != len(localized_obj["mods"]):
                errors.append(
                    {"location": location, "error": "modification count differs"}
                )
                continue
            for mod_index, (source_mod, localized_mod) in enumerate(
                zip(source_obj["mods"], localized_obj["mods"])
            ):
                mod_location = f"{location}/mod/{mod_index}"
                metadata = ("field", "type", "level", "data_pointer", "end_id")
                if any(source_mod[key] != localized_mod[key] for key in metadata):
                    errors.append(
                        {
                            "location": mod_location,
                            "error": "modification structure differs",
                        }
                    )
                    continue
                if source_mod["value"] == localized_mod["value"]:
                    continue
                field = source_mod["field"].decode("ascii", "replace")
                change = {
                    "location": mod_location,
                    "field": field,
                    "level": source_mod["level"],
                    "data_pointer": source_mod["data_pointer"],
                }
                if source_mod["type"] != 3:
                    errors.append(
                        {
                            **change,
                            "error": "non-string gameplay value changed",
                        }
                    )
                elif field not in allowed_fields:
                    errors.append(
                        {
                            **change,
                            "error": "string field is not approved as visible text",
                        }
                    )
                else:
                    changes.append(change)

    report = {
        "mode": "object",
        "source": str(Path(args.source).resolve()),
        "localized": str(Path(args.localized).resolve()),
        "layout_has_levels": source_levels,
        "approved_visible_fields": sorted(allowed_fields),
        "text_changes": changes,
        "errors": errors,
        "passed": not errors,
    }
    write_json(Path(args.report), report)
    print(json.dumps({"changes": len(changes), "errors": len(errors)}))
    if errors:
        raise SystemExit(1)


def script_command(args: argparse.Namespace) -> None:
    source = read_text(Path(args.source), args.encoding)
    localized = read_text(Path(args.localized), args.localized_encoding)
    source_matches = list(SCRIPT_STRING_RE.finditer(source))
    localized_matches = list(SCRIPT_STRING_RE.finditer(localized))
    errors = []
    changes = []
    if len(source_matches) != len(localized_matches):
        errors.append(
            {
                "error": "script string literal count differs",
                "source": len(source_matches),
                "localized": len(localized_matches),
            }
        )
    source_skeleton = SCRIPT_STRING_RE.sub('""', source)
    localized_skeleton = SCRIPT_STRING_RE.sub('""', localized)
    if source_skeleton != localized_skeleton:
        errors.append({"error": "non-string script code differs"})

    allowed = {int(value) for value in args.allow_string}
    for index, (source_match, localized_match) in enumerate(
        zip(source_matches, localized_matches)
    ):
        if source_match.group(0) == localized_match.group(0):
            continue
        item = {
            "string_index": index,
            "source_line": source.count("\n", 0, source_match.start()) + 1,
            "localized_line": localized.count("\n", 0, localized_match.start()) + 1,
            "source": source_match.group(0)[1:-1],
            "localized": localized_match.group(0)[1:-1],
        }
        if index not in allowed:
            errors.append({**item, "error": "string change is not allowlisted"})
        else:
            changes.append(item)
    unused = sorted(allowed - {item["string_index"] for item in changes})
    if unused:
        errors.append({"error": "allowlisted string indexes did not change", "indexes": unused})

    report = {
        "mode": "script",
        "source": str(Path(args.source).resolve()),
        "localized": str(Path(args.localized).resolve()),
        "text_changes": changes,
        "errors": errors,
        "passed": not errors,
    }
    write_json(Path(args.report), report)
    print(json.dumps({"changes": len(changes), "errors": len(errors)}))
    if errors:
        raise SystemExit(1)


def comparable_w3f(value: dict) -> dict:
    result = copy.deepcopy(value)
    for key in (
        "name",
        "difficulty",
        "author",
        "description",
        "direct_visible_text",
        "trigstr_ids",
        "bytes_consumed",
        "trailing_bytes",
    ):
        result.pop(key, None)
    for button in result["campaign_buttons"]:
        button.pop("chapter_title", None)
        button.pop("map_title", None)
    return result


def visible_w3f(value: dict) -> dict:
    return {
        "name": value["name"],
        "difficulty": value["difficulty"],
        "author": value["author"],
        "description": value["description"],
        "campaign_buttons": [
            {
                "chapter_title": item["chapter_title"],
                "map_title": item["map_title"],
            }
            for item in value["campaign_buttons"]
        ],
    }


def w3f_command(args: argparse.Namespace) -> None:
    source = parse_w3f(Path(args.source), args.encoding)
    localized = parse_w3f(Path(args.localized), args.localized_encoding)
    errors = []
    if comparable_w3f(source) != comparable_w3f(localized):
        errors.append({"error": "non-visible W3F data differs"})
    report = {
        "mode": "w3f",
        "source": str(Path(args.source).resolve()),
        "localized": str(Path(args.localized).resolve()),
        "source_visible_text": visible_w3f(source),
        "localized_visible_text": visible_w3f(localized),
        "errors": errors,
        "passed": not errors,
    }
    write_json(Path(args.report), report)
    print(json.dumps({"errors": len(errors)}))
    if errors:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prove that localization edits are limited to text payloads"
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    object_parser = sub.add_parser("object")
    object_parser.add_argument("source")
    object_parser.add_argument("localized")
    object_parser.add_argument("report")
    object_parser.add_argument("--allow-field", action="append", default=[])
    object_parser.set_defaults(func=object_command)

    script_parser = sub.add_parser("script")
    script_parser.add_argument("source")
    script_parser.add_argument("localized")
    script_parser.add_argument("report")
    script_parser.add_argument("--encoding")
    script_parser.add_argument("--localized-encoding")
    script_parser.add_argument("--allow-string", action="append", default=[])
    script_parser.set_defaults(func=script_command)

    w3f_parser = sub.add_parser("w3f")
    w3f_parser.add_argument("source")
    w3f_parser.add_argument("localized")
    w3f_parser.add_argument("report")
    w3f_parser.add_argument("--encoding")
    w3f_parser.add_argument("--localized-encoding")
    w3f_parser.set_defaults(func=w3f_command)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

