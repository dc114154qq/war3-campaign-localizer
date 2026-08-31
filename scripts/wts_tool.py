from __future__ import annotations

import argparse
import codecs
import collections
import json
import re
from pathlib import Path


STRING_RE = re.compile(
    r"(?ms)^(STRING\s+(\d+)(?:[^\r\n]*)\r?\n"
    r"(?:[^\r\n]*\r?\n)*?\{\r?\n)(.*?)(\r?\n\})"
)
CONTROL_RE = re.compile(
    r"\|c[0-9A-Fa-f]{8}|\|[rRnN]|%[0-9]*[A-Za-z]|<[^>\r\n]+>"
)
NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?")
SOURCE_WORD_PATTERNS = {
    "Latin": re.compile(r"[A-Za-z][A-Za-z'’-]{2,}"),
    "Cyrillic": re.compile(r"[\u0400-\u04FF][\u0400-\u04FF'’-]{2,}"),
    "Greek": re.compile(r"[\u0370-\u03FF][\u0370-\u03FF'’-]{2,}"),
    "Hebrew": re.compile(r"[\u0590-\u05FF]{3,}"),
    "Arabic": re.compile(r"[\u0600-\u06FF]{3,}"),
    "Devanagari": re.compile(r"[\u0900-\u097F]{3,}"),
    "Hangul": re.compile(r"[\uAC00-\uD7AF]{2,}"),
    "Kana": re.compile(r"[\u3040-\u30FF]{2,}"),
}
BAD_PATTERNS = {
    "Train mistranslated as train vehicle": re.compile(r"列车"),
    "deal damage mistranslated": re.compile(r"发牌|交易.{0,4}伤害"),
    "stun mistranslated": re.compile(r"令人惊艳"),
    "lasts mistranslated": re.compile(r"最后的作品|最后几部|秒数"),
    "ground/air mistranslated": re.compile(r"土地单位|空气单元"),
    "broken hotkey fragment": re.compile(
        r"(?i)(?:训练|建造|研究|复活).{0,24}"
        r"(?:nchorite|arrior|yvern|reant|isp|uard|ider|alker|emon)\b"
    ),
}


def read_text(path: Path, encoding: str | None = None) -> str:
    raw = path.read_bytes()
    if encoding:
        try:
            return raw.decode(encoding)
        except LookupError as exc:
            raise ValueError(f"unknown encoding {encoding!r}") from exc
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig")
    if raw.startswith(codecs.BOM_UTF16_LE):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnicodeError(
            f"{path} is not BOM/UTF-8. Re-run with an explicit source code page, "
            "for example --encoding cp1251 or --encoding cp1252."
        ) from exc


def parse(path: Path, encoding: str | None = None) -> list[tuple[str, str]]:
    text = read_text(path, encoding)
    entries = [(m.group(2), m.group(3)) for m in STRING_RE.finditer(text)]
    anchored = re.findall(r"(?m)^STRING\s+(\d+)\b", text)
    if len(entries) != len(anchored):
        parsed = {item[0] for item in entries}
        missing = [item for item in anchored if item not in parsed]
        raise ValueError(
            f"parsed {len(entries)} of {len(anchored)} STRING blocks in {path}; "
            f"unparsed IDs: {missing[:20]}"
        )
    ids = [item[0] for item in entries]
    duplicates = [key for key, count in collections.Counter(ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate STRING IDs in {path}: {duplicates[:20]}")
    return entries


def normalize_controls(value: str) -> list[str]:
    result = []
    for token in CONTROL_RE.findall(value):
        if token.lower().startswith("|c") or token.lower() in {"|r", "|n"}:
            result.append(token.lower())
        else:
            result.append(token)
    return result


def numbers(value: str) -> list[str]:
    value = CONTROL_RE.sub("", value)
    return [item.replace(",", ".").replace(" ", "") for item in NUMBER_RE.findall(value)]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def dump_command(args: argparse.Namespace) -> None:
    write_json(Path(args.output), dict(parse(Path(args.input), args.encoding)))


def pairs_command(args: argparse.Namespace) -> None:
    source = parse(Path(args.source), args.encoding)
    localized = parse(Path(args.localized), args.localized_encoding)
    if [item[0] for item in source] != [item[0] for item in localized]:
        raise ValueError("source/localized ID order differs")
    write_json(
        Path(args.output),
        [
            {"id": key, "source": source_text, "localized": localized_text}
            for (key, source_text), (_, localized_text) in zip(source, localized)
        ],
    )


def apply_command(args: argparse.Namespace) -> None:
    source_path = Path(args.source)
    output_path = Path(args.output)
    patch = json.loads(Path(args.patch).read_text(encoding="utf-8-sig"))
    if not isinstance(patch, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in patch.items()
    ):
        raise TypeError("patch must be a JSON object of string IDs to strings")

    source_values = dict(parse(source_path, args.encoding))
    missing = sorted(set(patch) - set(source_values), key=int)
    if missing:
        raise KeyError(f"patch IDs absent from source: {missing[:20]}")

    text = read_text(source_path, args.encoding)
    newline = "\r\n" if "\r\n" in text else "\n"

    def replace(match: re.Match[str]) -> str:
        key = match.group(2)
        if key not in patch:
            return match.group(0)
        value = patch[key].replace("\r\n", "\n").replace("\r", "\n")
        return match.group(1) + value.replace("\n", newline) + match.group(4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(codecs.BOM_UTF8 + STRING_RE.sub(replace, text).encode("utf-8"))


def verify_pair(
    location: str,
    source: str,
    localized: str,
    allow_control_diff: set[str],
    errors: list[dict],
    warnings: list[dict],
    strict_numbers: bool,
    allow_number_diff: set[str],
) -> None:
    source_controls = normalize_controls(source)
    localized_controls = normalize_controls(localized)
    if source_controls != localized_controls and location not in allow_control_diff:
        errors.append(
            {
                "location": location,
                "error": "control tokens differ",
                "source": source_controls,
                "localized": localized_controls,
            }
        )
    if "\ufffd" in localized or "<unk>" in localized.lower():
        errors.append({"location": location, "error": "invalid replacement marker"})
    if "`r`n" in localized or "\\r\\n" in localized:
        errors.append({"location": location, "error": "literal newline escape"})

    for label, pattern in BAD_PATTERNS.items():
        if pattern.search(localized):
            errors.append(
                {
                    "location": location,
                    "error": label,
                    "source": source,
                    "localized": localized,
                }
            )

    source_numbers = collections.Counter(numbers(source))
    localized_numbers = collections.Counter(numbers(localized))
    if source_numbers != localized_numbers:
        item = {
            "location": location,
            "source": list(source_numbers.elements()),
            "localized": list(localized_numbers.elements()),
        }
        if strict_numbers and location not in allow_number_diff:
            item["error"] = "numeric values differ in release mode"
            errors.append(item)
        else:
            item["warning"] = "numeric values differ; manually review mechanics"
            warnings.append(item)

    stripped = CONTROL_RE.sub(" ", localized)
    residual = {
        script: pattern.findall(stripped)
        for script, pattern in SOURCE_WORD_PATTERNS.items()
        if pattern.search(stripped)
    }
    if residual:
        warnings.append(
            {
                "location": location,
                "warning": "non-Chinese-script words require human classification",
                "scripts": residual,
            }
        )


def verify_files(
    source_path: Path,
    localized_path: Path,
    prefix: str,
    allow_control_diff: set[str],
    source_encoding: str | None,
    localized_encoding: str | None,
    strict_numbers: bool,
    allow_number_diff: set[str],
) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    source = parse(source_path, source_encoding)
    localized = parse(localized_path, localized_encoding)
    source_ids = [item[0] for item in source]
    localized_ids = [item[0] for item in localized]
    if source_ids != localized_ids:
        errors.append(
            {
                "location": prefix,
                "error": "STRING IDs/order differ",
                "source_count": len(source_ids),
                "localized_count": len(localized_ids),
                "missing": sorted(set(source_ids) - set(localized_ids), key=int)[:100],
                "extra": sorted(set(localized_ids) - set(source_ids), key=int)[:100],
            }
        )
        return {"errors": errors, "warnings": warnings}

    for (key, source_text), (_, localized_text) in zip(source, localized):
        location = f"{prefix}/{key}" if prefix else key
        verify_pair(
            location,
            source_text,
            localized_text,
            allow_control_diff,
            errors,
            warnings,
            strict_numbers,
            allow_number_diff,
        )
    return {"errors": errors, "warnings": warnings}


def verify_command(args: argparse.Namespace) -> None:
    result = verify_files(
        Path(args.source),
        Path(args.localized),
        args.prefix,
        set(args.allow_control_diff),
        args.encoding,
        args.localized_encoding,
        args.strict_numbers,
        set(args.allow_number_diff),
    )
    write_json(Path(args.report), result)
    print(json.dumps({"errors": len(result["errors"]), "warnings": len(result["warnings"])}))
    if result["errors"]:
        raise SystemExit(1)


def tree_verify_command(args: argparse.Namespace) -> None:
    source_root = Path(args.source_root)
    localized_root = Path(args.localized_root)
    allow = set(args.allow_control_diff)
    allow_numbers = set(args.allow_number_diff)
    errors: list[dict] = []
    warnings: list[dict] = []
    source_files = sorted(source_root.rglob("*.wts"))
    localized_files = {
        path.relative_to(localized_root): path
        for path in localized_root.rglob("*.wts")
    }
    for source_path in source_files:
        relative = source_path.relative_to(source_root)
        localized_path = localized_files.pop(relative, None)
        if localized_path is None:
            errors.append({"location": str(relative), "error": "missing localized WTS"})
            continue
        result = verify_files(
            source_path,
            localized_path,
            str(relative).replace("\\", "/"),
            allow,
            args.encoding,
            args.localized_encoding,
            args.strict_numbers,
            allow_numbers,
        )
        errors.extend(result["errors"])
        warnings.extend(result["warnings"])
    for relative in sorted(localized_files, key=str):
        errors.append({"location": str(relative), "error": "extra localized WTS"})
    report = {
        "source_files": len(source_files),
        "errors": errors,
        "warnings": warnings,
    }
    write_json(Path(args.report), report)
    print(json.dumps({"errors": len(errors), "warnings": len(warnings)}))
    if errors:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Warcraft III WTS review helper")
    sub = parser.add_subparsers(dest="command", required=True)

    dump_p = sub.add_parser("dump")
    dump_p.add_argument("input")
    dump_p.add_argument("output")
    dump_p.add_argument("--encoding")
    dump_p.set_defaults(func=dump_command)

    pairs_p = sub.add_parser("pairs")
    pairs_p.add_argument("source")
    pairs_p.add_argument("localized")
    pairs_p.add_argument("output")
    pairs_p.add_argument("--encoding")
    pairs_p.add_argument("--localized-encoding")
    pairs_p.set_defaults(func=pairs_command)

    apply_p = sub.add_parser("apply")
    apply_p.add_argument("source")
    apply_p.add_argument("patch")
    apply_p.add_argument("output")
    apply_p.add_argument("--encoding")
    apply_p.set_defaults(func=apply_command)

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("source")
    verify_p.add_argument("localized")
    verify_p.add_argument("report")
    verify_p.add_argument("--prefix", default="")
    verify_p.add_argument("--encoding")
    verify_p.add_argument("--localized-encoding")
    verify_p.add_argument("--allow-control-diff", action="append", default=[])
    verify_p.add_argument("--strict-numbers", action="store_true")
    verify_p.add_argument("--allow-number-diff", action="append", default=[])
    verify_p.set_defaults(func=verify_command)

    tree_p = sub.add_parser("tree-verify")
    tree_p.add_argument("source_root")
    tree_p.add_argument("localized_root")
    tree_p.add_argument("report")
    tree_p.add_argument("--allow-control-diff", action="append", default=[])
    tree_p.add_argument("--encoding")
    tree_p.add_argument("--localized-encoding")
    tree_p.add_argument("--strict-numbers", action="store_true")
    tree_p.add_argument("--allow-number-diff", action="append", default=[])
    tree_p.set_defaults(func=tree_verify_command)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
