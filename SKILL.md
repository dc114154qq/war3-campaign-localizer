---
name: war3-campaign-localizer
description: Fully localize English, Russian, European-language, or other foreign Warcraft III custom campaigns and maps (.w3n/.w3x/.w3m) into polished Chinese, covering player-visible campaign, map, object, script, and image text with lore-aware terminology, independent semantic review, and safe archive verification. Use for complete Chinese localization, retranslation, or quality repair; not for save-game-only edits.
---

# Warcraft III Campaign Localizer

Produce a finished Chinese localization that reads like a well-edited Warcraft campaign, not a machine-translated draft. This skill is standalone: do not invoke or require another skill. Use the bundled scripts, these references, and locally available MPQ/media tools.

## Required references

Read these before acting:

- [references/corpus-discovery.md](references/corpus-discovery.md) before deciding what must be translated.
- [references/localization-quality.md](references/localization-quality.md) before drafting or reviewing Chinese.
- [references/review-and-release.md](references/review-and-release.md) before accepting a segment or writing an archive.

## Non-negotiable outcome

- Translate every player-visible string, including campaign selection text, every map WTS record, campaign/map object data, direct JASS/Lua strings, and text embedded in visible images.
- Support English and any other identifiable source language. Detect the language and encoding per corpus or segment; mixed-language campaigns must not be forced through one language assumption.
- Preserve author names, usernames, email addresses, brands, resource credits, raw identifiers, and fictional-language phrases when translation would destroy identity or attribution.
- Treat automated translation only as a disposable draft. Every visible record must receive source-based semantic review.
- Resolve ambiguous gameplay text against object fields and scripts. If the source wording contradicts actual behavior, prefer the behavior for objectives and mechanics, and record the correction.
- Change only player-visible text payloads. Do not change models, model paths, textures outside text-bearing image regions, balance, object IDs, non-text object fields, trigger logic, script code, map geometry, sounds, archive membership, or campaign progress.
- When visible text is stored in W3F, object data, or JASS/Lua, alter only that text field or string literal. Prove the surrounding structure is unchanged with `scripts/text_only_verify.py`.
- Never overwrite the source. Back up the exact live file before every archive write.

## Workflow

1. **Fingerprint and isolate**
   - Record source path, size, SHA256, Warcraft target versions, encoding, and output name.
   - Accept BOM/UTF-8 automatically. For legacy sources, identify and pass the exact source code page; never let a decoder guess and silently produce mojibake.
   - Create a timestamped backup and a dedicated work directory outside the live Campaigns folder.
   - Keep a clean source copy for every rebuild.

2. **Build the complete corpus**
   - Extract the campaign and every nested map.
   - Run `scripts/campaign_inventory.py` on the extracted tree.
   - Review its W3F direct-text list, every script literal classification, and every visual manifest row; no unresolved decoding or missing-reference record may remain.
   - Parse WTS with `scripts/wts_tool.py`; count every `^STRING` declaration, including records with `// Units`, `// Abilities`, `// Doodads`, or similar comments.
   - Include `war3campaign.w3f` references, all `TRIGSTR_*` references in campaign/map object files, direct script strings, loading screens, credits, and visual assets likely to contain text.
   - Default to translating uncertain records. Exclude a record only with evidence that it is an internal raw/effect/dummy label.

3. **Establish terminology and voice**
   - Identify the source language(s), regional spelling, register, and name-pronunciation rules before translating. Translate directly from the original language whenever it can be understood reliably; do not route all languages through an English machine draft.
   - Create a glossary before bulk translation: official Warcraft names, factions, places, UI phrases, recurring custom names, skill names, item names, and hotkeys.
   - If a high-quality Chinese campaign is available, use it only as a style and terminology reference; never copy unrelated prose.
   - Lock glossary choices across all chapters and object data.

4. **Translate in context**
   - Split by disjoint chapters and object-ID ranges when parallel work helps.
   - Give each translator the original-language source, current draft, field/reference context, glossary, and exclusive output ownership.
   - Translate meaning, not word order. Dialogue must sound spoken; quests must state the exact action; tooltips must state targets, values, timing, and exceptions unambiguously.
   - Preserve all control codes, placeholders, raw field references, line breaks, and hotkey behavior.

5. **Run an independent full review**
   - A reviewer other than the writer must compare every source/localized pair, not merely sample.
   - Review dialogue, objectives, negation, factions, names, numeric mechanics, hotkeys, and source omissions.
   - Return an issue list with exact replacement text. Apply fixes and re-review until every segment report is an empty JSON array.
   - “No source-language text remains” and “all IDs exist” are structural checks, not translation approval.

6. **Merge and release**
   - Apply reviewed patches to a fresh clean extraction.
   - Run WTS tree verification, residual scans, glossary consistency scans, and the release gates in the review reference.
   - Run text-only structural verification for every changed W3F, object file, and script. Any non-text delta is a release blocker.
   - Rebuild nested maps first, then the campaign, preserving entry storage flags at both layers.
   - Run `scripts/archive_verify.py` on every rebuilt nested map and again on the outer campaign. All undeclared changes and flag differences are release blockers.
   - Perform a no-op packaging test before bulk replacement when the MPQ tool or target client is unproven.
   - Verify both classic 1.31 and Reforged when the user needs both. Do not claim compatibility without an actual client smoke test or an explicit validation gap.

## Stop conditions

Do not package a final release while any of these remain:

- missing or extra WTS IDs;
- non-empty independent review reports;
- unapproved control-code or placeholder differences;
- known machine-translation artifacts, replacement characters, or literal escape text;
- unexplained gameplay-number differences;
- any non-text W3F, object-data, script-code, model/path, map, audio, or archive-membership change;
- untranslated player-visible source-language text outside approved names, credits, raw labels, or fictional language;
- any nested-map resource extraction failure;
- a classic/Reforged compatibility failure requested by the user.

## Delivery

Provide:

- the new `.w3n`/`.w3x` path without overwriting the source;
- source and output SHA256;
- translated/reviewed record counts by layer and chapter;
- glossary and intentional untranslated-name exceptions;
- independent review status;
- archive and client compatibility evidence;
- backup path and any remaining validation gap.

