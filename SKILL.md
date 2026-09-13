---
name: war3-campaign-localizer
description: Fully localize English, Russian, European-language, or other foreign Warcraft III custom campaigns and maps (.w3n/.w3x/.w3m) into polished Chinese, covering player-visible campaign, map, object, script, and image text with lore-aware terminology, independent semantic review, and safe archive verification. Use for complete Chinese localization, retranslation, or quality repair; not for save-game-only edits.
---

# Warcraft III Campaign Localizer

Produce a finished Chinese localization authored directly from the source text by the executing reasoning agent. This skill is standalone: do not invoke or require another skill. Use the bundled scripts, these references, and locally available MPQ/media tools.

## Required references

Read these before acting:

- [references/corpus-discovery.md](references/corpus-discovery.md) before deciding what must be translated.
- [references/localization-quality.md](references/localization-quality.md) before drafting or reviewing Chinese.
- [references/terminology-registry.md](references/terminology-registry.md) before accepting Warcraft terminology or importing evidence.
- [references/entity-link-audit.md](references/entity-link-audit.md) before resolving object abilities or auditing tooltip mentions.
- [references/review-and-release.md](references/review-and-release.md) before accepting a segment or writing an archive.
- [references/shared-lore-registry.md](references/shared-lore-registry.md) when a name is shared with World of Warcraft or wider Warcraft lore.

## Non-negotiable outcome

- Translate every player-visible string, including campaign selection text, every map WTS record, campaign/map object data, direct JASS/Lua strings, and text embedded in visible images.
- Support English and any other identifiable source language. Detect the language and encoding per corpus or segment; mixed-language campaigns must not be forced through one language assumption.
- Preserve author names, usernames, email addresses, brands, resource credits, raw identifiers, and fictional-language phrases when translation would destroy identity or attribution.
- Do not use machine translation, translation APIs, browser translators, LLM batch-translation endpoints, MT caches, automatic dictionary substitution, or machine-generated translation worksheets at any stage, including drafting.
- The executing reasoning agent must personally read the original source and author every Chinese translation in context. Automation may inventory, extract, validate, compare, and package text, but it may never generate translated prose.
- Before packaging, every visible translated record must carry explicit `agent_authored` or `human_authored` provenance tied to its original source key. Missing, rewritten, or inherited provenance is a release failure.
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
   - Treat speaker labels as a separate corpus layer: inventory explicit names passed to `ScreenplayFactory.createActor`, `BlzSetUnitName`, and `BlzSetHeroProperName`; run `scripts/speaker_name_audit.py` after translation and require zero unapproved Latin names.
   - Default to translating uncertain records. Exclude a record only with evidence that it is an internal raw/effect/dummy label.

3. **Establish terminology and voice**
   - Identify the source language(s), regional spelling, register, and name-pronunciation rules before translating. Translate directly from the original language whenever it can be understood reliably; do not route all languages through an English machine draft.
   - Record the exact Warcraft III client version, distribution, and target locale. Import only auditable evidence into `scripts/term_registry.py`; never mix WoW, `zh-CN`/`zh-TW`, or different releases.
   - Query by scoped entity identity. Use exact-version Warcraft III official evidence first; if it is absent or ambiguous, retain the candidates and mark the term for human adjudication instead of inventing an “official” name.
   - Create a glossary before bulk translation: sourced official terms, clearly labeled custom decisions, factions, places, UI phrases, recurring names, skill names, item names, and hotkeys. Import final custom decisions as scoped `campaign_override` records.
   - For shared Warcraft lore names, query `assets/shared-lore-terms.json`, `assets/warcraft-iii-community-terms.json`, `assets/world-of-warcraft-community-terms.json`, and the paired WoW client layer `assets/world-of-warcraft-client-terms.json` using `scripts/shared_lore_registry.py`. Keep `warcraft_iii` and `world_of_warcraft` scopes separate; WoW evidence may support a shared proper name but cannot silently replace a WC3 client/object name. Treat the client layer as high-value spelling evidence, not as a substitute for the target campaign's own object data.
   - A missing or conflicting shared-lore result is an explicit human-review item, not permission to invent an “official” Chinese name.
   - If a high-quality Chinese campaign is available, use it only as a style and terminology reference; never copy unrelated prose.
   - Lock glossary choices across all chapters and object data.

4. **Author every translation in context**
   - Split by disjoint chapters and object-ID ranges when parallel work helps.
   - Give each reasoning-agent or human writer the original-language source, field/reference context, glossary, and exclusive output ownership. Never provide or generate an automatic translation draft.
   - Require the assigned writer to read the source record and write the Chinese itself; do not call a translation service, translation model endpoint, browser translator, or bulk substitution tool.
   - Translate meaning, not word order. Dialogue must sound spoken; quests must state the exact action; tooltips must state targets, values, timing, and exceptions unambiguously.
   - Preserve all control codes, placeholders, raw field references, line breaks, and hotkey behavior.
   - Build the entity-link manifest from unit/hero ability lists and object references. Resolve each unit-description skill mention to the actual ability entity and its button/learning name; WTS IDs are text locations, not entity identities. Missing base data or dynamic/unresolved references block release.

5. **Run an independent full review**
   - A reviewer other than the writer must compare every source/localized pair, not merely sample.
   - Review dialogue, objectives, negation, factions, names, numeric mechanics, hotkeys, and source omissions.
   - Return a review manifest, not only an issue list. Each segment manifest must contain the source fingerprint, the complete `reviewed_keys` list (stable WTS ID or script/object key), `reviewed_count`, and an `issues` array with exact replacement text. An empty issues array without complete coverage evidence is invalid.
   - Apply fixes and re-review until every segment manifest has complete key coverage, a matching source fingerprint, and an empty `issues` array. Run `scripts/semantic_review_gate.py` before packaging.
   - The reviewer must actively search for machine-translation artifacts and “translated-looking” nonsense (repeated characters, wrong part of speech, literal UI terms, mixed scripts, mojibake, and source fragments). A clean residual-English scan is not sufficient evidence of quality.
   - Group identical source text within the same semantic entity/field. Do not conflate same-named different entities; list genuine contextual variations by stable key with a reason.
   - Re-run the terminology and entity-link audits after every review pass. Each resolved entity/surface must use its adjudicated target across campaign WTS, map WTS, object fields, scripts, quests, and UI; competing targets or subtle description/button differences block release unless an evidence-backed alias is explicitly scoped.
   - “No source-language text remains” and “all IDs exist” are structural checks, not translation approval.

6. **Merge and release**
   - Apply reviewed patches to a fresh clean extraction.
   - Run WTS tree verification, residual scans, glossary consistency scans, and the release gates in the review reference.
   - Run `scripts/semantic_review_gate.py --require-entity-audit` against all writer records, review manifests, the final glossary, every entity-link manifest, the terminology database, and the final extracted object/WTS tree. Supply the independently established campaign, source/target locale, client version, and distribution through every `--expected-*` option; manifest self-declaration is not release evidence. A pass requires full review coverage, zero unresolved issues, zero unexplained within-entity splits, zero glossary conflicts, and zero entity-term issues.
   - Run `scripts/speaker_name_audit.py` against the final extracted maps. A translated dialogue body does not prove its speaker label or runtime unit name was translated.
   - Run text-only structural verification for every changed W3F, object file, and script. Any non-text delta is a release blocker.
   - Rebuild nested maps first, then the campaign, preserving entry storage flags at both layers.
   - Run `scripts/archive_verify.py` on every rebuilt nested map and again on the outer campaign. All undeclared changes and flag differences are release blockers.
   - Perform a no-op packaging test before bulk replacement when the MPQ tool or target client is unproven.
   - Verify both classic 1.31 and Reforged when the user needs both. Do not claim compatibility without an actual client smoke test or an explicit validation gap.

## Stop conditions

Do not package a final release while any of these remain:

- missing or extra WTS IDs;
- non-empty independent review reports;
- review reports that are plain arrays, lack a source fingerprint, omit any stable key, or claim a count different from the covered keys;
- any visible record not listed in exactly one independent review manifest;
- unexplained multiple translations for one identical source string within the same semantic entity/field;
- a glossary term with competing visible targets or a missing canonical target in a source occurrence;
- a terminology decision without exact product/locale/version/distribution evidence or an explicit scoped campaign override;
- a unit ability scan, ability binding, description mention, base-data inheritance, or entity-term decision that is missing, duplicate, wrong, dynamic, or unresolved;
- a description mention that differs from the resolved skill bar/learning name after display-only color/hotkey normalization, unless a sourced alias is explicitly scoped to that mention;
- unapproved control-code or placeholder differences;
- known machine-translation artifacts, replacement characters, or literal escape text;
- any record produced or drafted by a machine-translation engine, translation API, browser translator, LLM batch-translation endpoint, MT cache, or bulk dictionary pass;
- any translated record whose provenance is missing or is not explicitly `agent_authored` or `human_authored`;
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
- terminology source summary, exact client/locale decisions, unresolved ambiguities, and entity-link audit report;
- independent review status;
- archive and client compatibility evidence;
- backup path and any remaining validation gap.
