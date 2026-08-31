from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path

from wts_tool import parse, read_text


TRIGSTR_RE = re.compile(rb"TRIGSTR_(\d+)")
TEXT_TRIGSTR_RE = re.compile(r"TRIGSTR_(\d+)")
SCRIPT_STRING_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:set\s+|(?:local\s+)?string\s+)([A-Za-z_]\w*)\s*=\s*"
    r'"((?:\\.|[^"\\])*)"'
)
VISIBLE_CALL_RE = re.compile(
    r"(?i)(DisplayText|Quest|Transmission|Cinematic|Multiboard|Leaderboard|"
    r"Dialog|Button|GameMessage|SetMapDescription|BlzFrameSetText|"
    r"BlzSetAbility(?:Extended)?Tooltip|BlzSetItem(?:Name|Description|Tooltip|ExtendedTooltip)|"
    r"(?:Set|Create)TextTag|SetTextTagText)"
)
OBJECT_SUFFIXES = {".w3u", ".w3a", ".w3t", ".w3h", ".w3b", ".w3d", ".w3q", ".w3i"}
VISUAL_SUFFIXES = {".blp", ".tga", ".dds", ".png", ".jpg", ".jpeg"}
AUDIO_VIDEO_SUFFIXES = {".mp3", ".wav", ".flac", ".ogg", ".avi", ".webm", ".mp4"}
TEXT_ASSET_SUFFIXES = {".fdf", ".toc", ".txt", ".ini", ".slk"}


def decode_binary_text(raw: bytes, encoding: str | None, location: str) -> str:
    if encoding:
        return raw.decode(encoding)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnicodeError(
            f"{location} contains non-UTF-8 text. Re-run with --encoding and the "
            "known source code page, for example cp1251 or cp1252."
        ) from exc


def cstring(data: bytes, offset: int, encoding: str | None, location: str) -> tuple[str, int]:
    try:
        end = data.index(0, offset)
    except ValueError as exc:
        raise ValueError(f"unterminated string at {location}, offset {offset}") from exc
    return decode_binary_text(data[offset:end], encoding, location), end + 1


def parse_w3f(path: Path, encoding: str | None = None) -> dict:
    data, offset = path.read_bytes(), 0
    def need(size: int, label: str) -> None:
        if offset + size > len(data):
            raise ValueError(f"{path}: truncated while reading {label} at {offset}")
    def integer(label: str) -> int:
        nonlocal offset; need(4, label); value = struct.unpack_from("<i", data, offset)[0]; offset += 4; return value
    def floating(label: str) -> float:
        nonlocal offset; need(4, label); value = struct.unpack_from("<f", data, offset)[0]; offset += 4; return value
    def byte(label: str) -> int:
        nonlocal offset; need(1, label); value = data[offset]; offset += 1; return value
    def string(label: str) -> str:
        nonlocal offset; value, offset = cstring(data, offset, encoding, f"{path}:{label}"); return value
    result = {
        "format_version": integer("format version"), "campaign_version": integer("campaign version"),
        "editor_version": integer("editor version"), "name": string("name"),
        "difficulty": string("difficulty"), "author": string("author"), "description": string("description"),
        "flags": integer("flags"), "background_index": integer("background index"),
        "background_path": string("background path"), "minimap_path": string("minimap path"),
        "ambient_sound_index": integer("ambient sound index"), "ambient_sound_path": string("ambient sound path"),
        "fog_style": integer("fog style"), "fog_start": floating("fog start"),
        "fog_end": floating("fog end"), "fog_density": floating("fog density"),
        "fog_color": [byte("fog red"), byte("fog green"), byte("fog blue"), byte("fog alpha")],
        "ui_race": integer("UI race"),
    }
    count = integer("campaign button count")
    if not 0 <= count <= 10000: raise ValueError(f"{path}: implausible campaign button count {count}")
    result["campaign_buttons"] = [
        {"visible": integer(f"button {i} visibility"), "chapter_title": string(f"button {i} chapter title"),
         "map_title": string(f"button {i} map title"), "map_path": string(f"button {i} map path")}
        for i in range(count)
    ]
    count = integer("campaign map count")
    if not 0 <= count <= 10000: raise ValueError(f"{path}: implausible campaign map count {count}")
    result["campaign_maps"] = [{"unknown": string(f"map {i} unknown string"), "map_path": string(f"map {i} map path")} for i in range(count)]
    result["bytes_consumed"], result["trailing_bytes"] = offset, len(data) - offset
    result["trigstr_ids"] = sorted({str(int(x)) for x in TRIGSTR_RE.findall(data)}, key=int)
    result["direct_visible_text"] = [
        {"field": field, "text": text} for field, text in
        {**{k: result[k] for k in ("name", "difficulty", "author", "description")},
         **{f"campaign_buttons[{i}].{f}": item[f] for i, item in enumerate(result["campaign_buttons"]) for f in ("chapter_title", "map_title")}}.items()
        if text and not TEXT_TRIGSTR_RE.fullmatch(text)
    ]
    return result


def script_candidates(path: Path, encoding: str | None = None) -> list[dict]:
    text = read_text(path, encoding)
    assignments = {
        name: value for name, value in ASSIGNMENT_RE.findall(text)
    }
    candidates, index = [], 0
    for line_number, line in enumerate(text.splitlines(), 1):
        strings = SCRIPT_STRING_RE.findall(line)
        if not strings: continue
        if VISIBLE_CALL_RE.search(line):
            classification = "visible-call-line"
        elif any(
            re.search(rf"\b{re.escape(name)}\b", line)
            for name in assignments
        ):
            classification = "visible-via-variable"
        else:
            classification = "unclassified"
        candidates.append({"line": line_number, "classification": classification,
                           "first_string_index": index, "string_indexes": list(range(index, index + len(strings))), "strings": strings})
        index += len(strings)
    return candidates


def binary_string_candidates(
    path: Path, encoding: str | None = None
) -> list[dict]:
    data = path.read_bytes()
    candidates = []
    start = 0
    for end, value in enumerate(data):
        if value != 0:
            continue
        raw = data[start:end]
        start = end + 1
        if not 3 <= len(raw) <= 4096:
            continue
        try:
            text = decode_binary_text(
                raw, encoding, f"{path}@{start - len(raw) - 1}"
            )
        except UnicodeError:
            continue
        printable = sum(character.isprintable() for character in text)
        if not text or printable / len(text) < 0.85:
            continue
        if not any(character.isalpha() for character in text):
            continue
        candidates.append(
            {
                "offset": start - len(raw) - 1,
                "text": text,
            }
        )
    return candidates


def text_asset_candidates(
    path: Path, encoding: str | None = None
) -> list[dict]:
    try:
        text = read_text(path, encoding)
    except Exception as exc:
        return [{"classification": "error", "error": str(exc)}]
    return [
        {"line": number, "text": line.strip()}
        for number, line in enumerate(text.splitlines(), 1)
        if any(character.isalpha() for character in line)
    ]


def image_metadata(path: Path) -> dict:
    data = path.read_bytes()[:262144]
    suffix = path.suffix.lower()
    metadata = {"width": None, "height": None, "has_alpha": None}
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 26:
            metadata["width"], metadata["height"] = struct.unpack_from(
                ">II", data, 16
            )
            metadata["has_alpha"] = data[25] in {4, 6}
        elif suffix == ".tga" and len(data) >= 18:
            metadata["width"], metadata["height"] = struct.unpack_from(
                "<HH", data, 12
            )
            metadata["has_alpha"] = bool(data[17] & 0x0F)
        elif data.startswith(b"DDS ") and len(data) >= 108:
            metadata["height"], metadata["width"] = struct.unpack_from(
                "<II", data, 12
            )
            pixel_flags = struct.unpack_from("<I", data, 80)[0]
            alpha_mask = struct.unpack_from("<I", data, 104)[0]
            metadata["has_alpha"] = bool(pixel_flags & 1 or alpha_mask)
        elif data.startswith((b"BLP1", b"BLP2")) and len(data) >= 20:
            metadata["width"], metadata["height"] = struct.unpack_from(
                "<II", data, 12
            )
            if data.startswith(b"BLP2"):
                metadata["has_alpha"] = data[9] > 0
        elif data.startswith(b"\xff\xd8"):
            position = 2
            while position + 9 < len(data):
                if data[position] != 0xFF:
                    position += 1
                    continue
                marker = data[position + 1]
                if marker in {0xD8, 0xD9}:
                    position += 2
                    continue
                length = struct.unpack_from(">H", data, position + 2)[0]
                if marker in {
                    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
                }:
                    metadata["height"], metadata["width"] = struct.unpack_from(
                        ">HH", data, position + 5
                    )
                    metadata["has_alpha"] = False
                    break
                position += 2 + length
    except (IndexError, struct.error, ValueError):
        pass
    return metadata


def candidate_wts_tables(
    relative: str, all_wts_ids: dict[str, set[str]]
) -> set[str]:
    return set().union(
        *(
            ids
            for wts_path, ids in all_wts_ids.items()
            if Path(wts_path).parent == Path(relative).parent
            or ("campaign" in relative.lower() and "campaign" in wts_path.lower())
        )
    ) if all_wts_ids else set()


def add_missing_refs(
    missing: list[dict], relative: str, refs: list[str], available: set[str]
) -> None:
    if not available:
        missing.extend(
            {
                "file": relative,
                "id": ref,
                "reason": "no candidate WTS table found",
            }
            for ref in refs
        )
        return
    missing.extend(
        {
            "file": relative,
            "id": ref,
            "reason": "TRIGSTR ID absent from candidate WTS",
        }
        for ref in refs
        if ref not in available
    )


def inventory(root: Path, encoding: str | None) -> dict:
    wts_files = []
    all_wts_ids: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.wts")):
        relative = str(path.relative_to(root)).replace("\\", "/")
        entries = parse(path, encoding)
        ids = {item[0] for item in entries}
        all_wts_ids[relative] = ids
        wts_files.append(
            {
                "file": relative,
                "strings": len(entries),
                "first_id": entries[0][0] if entries else None,
                "last_id": entries[-1][0] if entries else None,
            }
        )

    object_refs: dict[str, list[str]] = {}
    binary_strings: dict[str, list[dict]] = {}
    missing_refs: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in OBJECT_SUFFIXES:
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        data = path.read_bytes()
        refs = sorted({str(int(item)) for item in TRIGSTR_RE.findall(data)}, key=int)
        if refs:
            object_refs[relative] = refs
        candidates = binary_string_candidates(path, encoding)
        if candidates:
            binary_strings[relative] = candidates
        add_missing_refs(
            missing_refs, relative, refs, candidate_wts_tables(relative, all_wts_ids)
        )

    w3f_files = {}
    for path in sorted(root.rglob("war3campaign.w3f")):
        relative = str(path.relative_to(root)).replace("\\", "/")
        info = parse_w3f(path, encoding)
        w3f_files[relative] = info
        campaign_tables = [
            ids for wts_path, ids in all_wts_ids.items()
            if "campaign" in wts_path.lower()
        ]
        add_missing_refs(
            missing_refs,
            relative,
            info["trigstr_ids"],
            set().union(*campaign_tables) if campaign_tables else set(),
        )

    scripts = {}
    for pattern in ("war3map.j", "war3map.lua", "*.j", "*.lua"):
        for path in sorted(root.rglob(pattern)):
            relative = str(path.relative_to(root)).replace("\\", "/")
            if relative in scripts:
                continue
            candidates = script_candidates(path, encoding)
            if candidates:
                scripts[relative] = candidates

    text_assets = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_ASSET_SUFFIXES:
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        candidates = text_asset_candidates(path, encoding)
        if candidates:
            text_assets[relative] = candidates

    visual_assets = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VISUAL_SUFFIXES:
            continue
        visual_assets.append(
            {
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "size": path.stat().st_size,
                **image_metadata(path),
                "contains_text": None,
                "reviewed": False,
                "localized_path": None,
            }
        )
    audio_video_assets = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_VIDEO_SUFFIXES
    )

    report = {
        "root": str(root.resolve()),
        "wts_files": wts_files,
        "wts_string_total": sum(item["strings"] for item in wts_files),
        "campaign_info": w3f_files,
        "object_trigstr_refs": object_refs,
        "binary_string_candidates": binary_strings,
        "object_unique_ref_count": len(
            {item for refs in object_refs.values() for item in refs}
        ),
        "missing_trigstr_refs": missing_refs,
        "source_encoding": encoding or "BOM/UTF-8 required",
        "script_string_candidates": scripts,
        "script_string_candidate_total": sum(
            len(
                [
                    item
                    for item in candidates
                    if item.get("classification") != "error"
                ]
            )
            for candidates in scripts.values()
        ),
        "text_asset_candidates": text_assets,
        "text_asset_candidate_total": sum(
            len(items) for items in text_assets.values()
        ),
        "visual_assets_to_inspect": visual_assets,
        "audio_video_assets": audio_video_assets,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory Warcraft III campaign localization corpus")
    parser.add_argument("--root", required=True); parser.add_argument("--out", required=True); parser.add_argument("--encoding")
    args = parser.parse_args()
    report = inventory(Path(args.root), args.encoding)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    decoding_errors = [
        {"file": file, **item}
        for file, items in {
            **report["script_string_candidates"],
            **report["text_asset_candidates"],
        }.items()
        for item in items
        if item.get("classification") == "error"
    ]
    if report["missing_trigstr_refs"] or decoding_errors:
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "wts_files": len(report["wts_files"]),
                "wts_strings": report["wts_string_total"],
                "object_refs": report["object_unique_ref_count"],
                "script_files": len(report["script_string_candidates"]),
                "script_strings": report["script_string_candidate_total"],
                "binary_strings": sum(
                    len(items)
                    for items in report["binary_string_candidates"].values()
                ),
                "text_asset_strings": report["text_asset_candidate_total"],
                "visual_assets": len(report["visual_assets_to_inspect"]),
            }
        )
    )


if __name__ == "__main__":
    main()
