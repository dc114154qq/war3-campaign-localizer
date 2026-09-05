from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

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
    canonical = [
        {"key": stable_key(row, i), "source": str(row.get("source", ""))}
        for i, row in enumerate(rows)
    ]
    raw = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail closed on incomplete semantic review evidence.")
    parser.add_argument("--records", action="append", required=True)
    parser.add_argument("--reviews", action="append", required=True)
    parser.add_argument("--glossary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    issues: list[dict] = []
    all_rows: list[tuple[Path, dict, str]] = []
    for path in expand(args.records):
        try:
            rows = records_from(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append({"location": str(path), "issue": str(exc)})
            continue
        keys = [stable_key(row, i) for i, row in enumerate(rows)]
        if len(keys) != len(set(keys)):
            issues.append({"location": str(path), "issue": "duplicate stable key"})
        for i, row in enumerate(rows):
            all_rows.append((path, row, keys[i]))

    expected_by_path: dict[str, set[str]] = defaultdict(set)
    for path, _, key in all_rows:
        expected_by_path[str(path.resolve())].add(key)

    seen_review_keys: dict[str, set[str]] = defaultdict(set)
    for review_path in expand(args.reviews):
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
        if review.get("reviewed_count") != len(keys):
            issues.append({"location": str(review_path), "issue": "reviewed_count does not match reviewed_keys"})
        if review.get("issues") != []:
            issues.append({"location": str(review_path), "issue": "unresolved semantic review issues"})
        source_fingerprint = review.get("source_fingerprint")
        if not isinstance(source_fingerprint, str) or not source_fingerprint:
            issues.append({"location": str(review_path), "issue": "missing source_fingerprint"})
        owner = review.get("record_file")
        if owner:
            owner_path = Path(owner)
            if not owner_path.is_absolute():
                owner_path = Path.cwd() / owner_path
            owner_path = owner_path.resolve()
            owner_name = str(owner_path)
            seen_review_keys[owner_name].update(map(str, keys))
            if owner_path.is_file() and isinstance(source_fingerprint, str):
                try:
                    actual = record_fingerprint(records_from(owner_path))
                    if actual != source_fingerprint.upper():
                        issues.append({"location": str(review_path), "issue": "stale source_fingerprint"})
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    issues.append({"location": str(review_path), "issue": f"invalid record_file: {exc}"})
            elif not owner_path.is_file():
                issues.append({"location": str(review_path), "issue": f"record_file not found: {owner_path}"})
        else:
            seen_review_keys["__unscoped__"].update(map(str, keys))

    if "__unscoped__" in seen_review_keys:
        expected = {key for _, _, key in all_rows}
        missing = expected - seen_review_keys["__unscoped__"]
        if missing:
            issues.append({"location": "reviews", "issue": f"unreviewed keys: {len(missing)}"})
    else:
        for owner, expected in expected_by_path.items():
            missing = expected - seen_review_keys.get(owner, set())
            if missing:
                issues.append({"location": owner, "issue": f"unreviewed keys: {len(missing)}"})

    by_source: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for path, row, key in all_rows:
        if row.get("decision") not in {"translate", "preserve_identity"}:
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
        if str(row.get("status", "")).lower() in {"draft", "machine_draft", "unreviewed"}:
            issues.append({"location": f"{path}:{key}", "issue": "unreviewed draft record is not releaseable"})
        by_source[source][target].append(f"{path}:{key}")
        if row.get("decision") in {"translate", "preserve_identity"} and BAD_RE.search(target):
            issues.append({"location": f"{path}:{key}", "issue": "known machine-translation artifact"})
    for source, targets in by_source.items():
        if len(targets) > 1:
            issues.append(
                {
                    "location": "same-source-consistency",
                    "source": source,
                    "issue": f"{len(targets)} competing translations",
                }
            )

    try:
        glossary = read_json(args.glossary)
        entries = glossary["entries"] if isinstance(glossary, dict) else glossary
        for entry in entries:
            source_term = str(entry.get("source", ""))
            target_term = str(entry.get("target", ""))
            if not source_term or not target_term:
                continue
            old_targets: set[str] = set()
            for _, row, key in all_rows:
                if source_term in str(row.get("source", "")) and row.get("decision") in {"translate", "preserve_identity"}:
                    target = str(row.get("translation", ""))
                    if target_term not in target and source_term not in {"Exodus II: The Worlds Forsaken"}:
                        issues.append({"location": f"glossary:{source_term}/{key}", "issue": "canonical target missing"})
                    old_targets.add(target)
            if len(old_targets) > 1:
                # This is informational unless a source occurrence omitted the canonical target above.
                pass
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        issues.append({"location": str(args.glossary), "issue": f"invalid glossary: {exc}"})

    report = {"issues": issues, "record_count": len(all_rows), "review_count": len(expand(args.reviews))}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(all_rows), "reviews": report["review_count"], "issues": len(issues)}))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
