# Review and Release

## Authorship gate

Translation prose must be authored directly from the original source by the executing reasoning agent or a human writer. Extraction, inventory, consistency checks, and packaging may be automated; translation drafting may not. Do not use machine translation, translation APIs, browser translators, LLM batch-translation endpoints, MT caches, automatic dictionary substitution, or generated translation worksheets at any stage.

Every translated writer record must use `provenance: "agent_authored"` or `provenance: "human_authored"`. A deliberately preserved identity string may use `provenance: "source_reviewed_preservation"`. Missing or different provenance is a release blocker, regardless of later review quality.

## Writer/reviewer separation

The writer produces a patch mapping stable string keys to final Chinese. The reviewer compares the entire assigned source range with that patch. When subagents are available, use disjoint ownership and a separate verifier. Without subagents, perform two temporally separated passes and do not reuse the writer's conclusions as review evidence.

The reviewer must inspect every record, not a sample. The evidence must be a manifest containing the source fingerprint, every reviewed stable key, the reviewed count, and an issues array. A bare empty array is never sufficient evidence of full review.

Before release, group exact source text within the same semantic entity/field and fail on competing translations unless every affected writer record supplies a non-empty `consistency_exception` reason. Do not merge same-named different entities. Re-run the glossary and entity-link scans after applying reviewer fixes; a terminology decision is not complete until every occurrence resolved to that entity/surface uses the adjudicated target or a narrowly sourced alias.

## Review issue schema

Use a JSON object manifest:

```json
{
  "segment": "11_Dalaran",
  "record_file": "writer-maps/11_Dalaran.json",
  "source_fingerprint": "SHA256",
  "reviewed_keys": ["135", "136"],
  "reviewed_count": 2,
  "issues": [
    {
      "key": "11_Dalaran/135",
      "severity": "high",
      "source": "Original-language source",
      "localized": "Current Chinese",
      "context": ["war3map.wts", "quest objective"],
      "issue": "The time condition was changed into a different objective.",
      "suggested": "Complete corrected Chinese"
    }
  ]
}
```

Severity:

- `critical`: directly reverses or destroys gameplay mechanics, target, success/failure, or numeric behavior;
- `high`: materially changes plot, faction, identity, objective, or required item;
- `medium`: omission, terminology mismatch, unnatural dialogue, or misleading UI;
- `low`: polish or consistency issue that remains visible.

A segment passes only when its report is a valid JSON object with complete, unique `reviewed_keys`, matching `reviewed_count` and source fingerprint, and an empty `issues` array. A bare `[]` always fails.

## Automated gates

Use `scripts/wts_tool.py`:

```powershell
python scripts/wts_tool.py dump source.wts source.json
python scripts/wts_tool.py pairs source.wts localized.wts pairs.json
python scripts/wts_tool.py apply source.wts patch.json localized.wts
python scripts/wts_tool.py verify source.wts localized.wts report.json --strict-numbers
python scripts/wts_tool.py tree-verify source-root localized-root report.json --strict-numbers

# A legacy source code page must be explicit. Localized output is normally UTF-8:
python scripts/wts_tool.py dump source.wts source.json --encoding cp1251
python scripts/wts_tool.py verify source.wts localized.wts report.json --encoding cp1251 --strict-numbers
```

Automated gates must detect:

- ID/order/count differences;
- control code and placeholder differences;
- replacement characters, `<unk>`, and literal escape text;
- known machine-translation artifacts;
- residual Latin words for human classification;
- numeric differences for manual gameplay review.

For terminology and ability mentions, first import evidence and campaign decisions as described in [terminology-registry.md](terminology-registry.md), then build [entity-link-audit.md](entity-link-audit.md). The release invocation is:

```powershell
python scripts/semantic_review_gate.py `
  --records quality/writer-*.json --reviews quality/review-manifest-*.json `
  --glossary quality/glossary.json `
  --entity-manifest quality/entity-links.json `
  --term-db quality/war3-terms.sqlite --term-source-root quality/extracted-evidence `
  --object-root final-extracted `
  --expected-campaign campaign-sha256-or-stable-id `
  --expected-source-locale en-US --expected-target-locale zh-CN `
  --expected-client-version 1.31.1 --expected-distribution classic `
  --require-entity-audit `
  --out quality/semantic-review-gate.json
```

Legacy invocations without entity inputs still run the older review checks for compatibility, but are not release evidence. `--require-entity-audit` also requires independently supplied campaign/source locale/target locale/client version/distribution values; missing or mismatched context, manifests/database, unresolved bindings, source gaps, and display/description name differences become a nonzero release failure.

Approved exceptions must be explicit and narrow. For intentional numeric changes, repeat `--allow-number-diff <location>` with the exact report location. For intentional control changes, repeat `--allow-control-diff <location>`. Do not globally disable a gate because a few source strings are malformed.

## Text-only structural gate

Localization is not authorization to alter gameplay. Run `scripts/text_only_verify.py` for every changed non-WTS file:

```powershell
# W3F: only campaign name/difficulty/author/description and chapter/map titles may differ.
python scripts/text_only_verify.py w3f clean.w3f localized.w3f w3f-report.json

# Object data: object IDs, modification order/types, numeric values, and non-visible
# string fields must be identical. Add a custom field only after proving it is visible.
python scripts/text_only_verify.py object clean.w3a localized.w3a object-report.json
python scripts/text_only_verify.py object clean.w3u localized.w3u object-report.json `
  --allow-field customVisibleFieldTag

# Scripts: the entire program outside double-quoted string payloads must be identical.
# Each intentionally translated literal uses its zero-based index from the inventory.
python scripts/text_only_verify.py script clean-war3map.j localized-war3map.j script-report.json `
  --allow-string 127 --allow-string 128
```

All text-only reports must pass. Never permit a numeric object-field change, script-code change, model/resource path change, rawcode change, trigger change, or added/removed modification in order to make packaging easier. A changed visual asset is allowed only when its manifest proves that the same asset path, dimensions, and alpha behavior were preserved and the edit is confined to replacing visible text.

## MPQ packaging invariants

Start every build from the clean source.

For `.w3n`:

1. extract a chapter map;
2. patch the innermost WTS or text-bearing asset;
3. preserve the original inner entry flags;
4. normalize/compact the inner MPQ only with a tool proven compatible;
5. put the map back using the original outer map flags;
6. patch campaign WTS and campaign-level text;
7. preserve all unrelated entries byte-identically where the tool permits.

Record storage flags for every changed entry: compression, implode, encryption, key mode, single-unit, and sector CRC. Do not add compression merely because the API defaults to it.

### Required no-op compatibility test

Before bulk packaging with an unproven tool:

- copy a clean campaign;
- replace one WTS entry with byte-identical content;
- rebuild using preserved flags;
- verify full extraction;
- smoke-test the affected chapter in each required client.

If classic accepts the map but Reforged reports `ERROR #131`, `Bad sector offset`, or `ReadFileUnbuffered() Failed`, treat the packaging layout as incompatible even if StormLib can extract the changed WTS. Rebuild from the clean source with a different update/compaction method. Do not stack fixes on the incompatible archive.

## Full archive verification

Checking only the changed WTS is insufficient. For every rebuilt nested map:

- enumerate the original listfile;
- extract every known entry from original and rebuilt archives;
- compare every unchanged entry by size and SHA256;
- verify changed entries against reviewed sources;
- compare inner and outer flags;
- verify `(listfile)` and `(attributes)` behavior;
- explicitly extract large imported models, textures, and audio;
- run the archive library's verification function when available.

Then re-extract all maps from the final live campaign and repeat the changed-entry checks.

Run the bundled verifier separately for each nested map and for the outer campaign:

```powershell
python scripts/archive_verify.py `
  --original clean-map.w3x `
  --rebuilt localized-map.w3x `
  --changed-entry war3map.wts `
  --required-entry war3map.wts `
  --required-entry war3map.j `
  --report map-archive-report.json

python scripts/archive_verify.py `
  --original clean-campaign.w3n `
  --rebuilt localized-campaign.w3n `
  --changed-entry war3campaign.wts `
  --changed-entry "Chapter01.w3x" `
  --required-entry war3campaign.w3f `
  --report campaign-archive-report.json
```

Declare every expected changed entry. The verifier treats any other size/SHA256 change, missing entry, or MPQ flag difference as an error. It reads the union of both listfiles; if an archive has no usable `(listfile)`, rebuild or supply a packaging method that preserves one. Passing this verifier proves archive integrity only, not client compatibility.

Only declare entries that contain reviewed localized text or a nested map already proven text-only. If the archive tool rewrites `(listfile)` or `(attributes)`, inspect and explicitly justify that metadata-only delta; it may never add, remove, or redirect a gameplay resource.

## Client smoke tests

When compatibility is required:

- launch the campaign selection page;
- enter every chapter or at least every distinct rebuilt map;
- test in classic 1.31 and current Reforged;
- start from the chapter entry point rather than an old save;
- check titles, Chinese glyph rendering, loading screens, quests, dialogue, buttons, tooltips, credits, and campaign transitions.

Do not claim dual-version support if only archive extraction or one client was tested. Report the missing client test explicitly.

## Release report

Include:

- source/output paths and SHA256;
- backup path;
- corpus counts by campaign and map;
- review reports and remaining issue count;
- approved untranslated names/credits/raw labels;
- approved source corrections and control-code repairs;
- archive flags and full extraction result;
- actual client versions smoke-tested;
- any remaining gap.
