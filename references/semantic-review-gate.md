# Semantic Review Gate

Structural checks prove that IDs, control codes, placeholders, and archive entries survived. They do not prove that Chinese is natural or that every record was reviewed. Use this gate for every release.

## Translation provenance

The gate must reject a translated record unless its `provenance` is exactly `agent_authored` or `human_authored`. For a deliberately preserved identity string, `source_reviewed_preservation` is also allowed. Missing provenance is a failure. Review does not convert automatic translation into acceptable authorship: machine translation, translation APIs, browser translators, LLM batch-translation endpoints, MT caches, automatic dictionary substitution, and generated translation worksheets are prohibited even as drafts.

## Review manifest

Each disjoint review segment must be a JSON object:

```json
{
  "segment": "campaign-00000-05500",
  "record_file": "quality/writer-campaign-00000-05500.json",
  "source_fingerprint": "SHA256 of the exact source-record JSON",
  "reviewed_keys": ["1", "2", "3"],
  "reviewed_count": 3,
  "issues": []
}
```

`reviewed_keys` must contain every stable key in the assigned record file, including records ultimately marked `preserve_internal` or `preserve_identity`. The list must be unique and sorted. `reviewed_count` must equal its length. A plain `[]` review file is not evidence of review coverage and must fail the gate.

Every writer record must have `status: "final"` and an enumerated `surface` (`campaign_text`, `dialogue`, `quest`, `ui`, `credits`, `script_visible`, unit/ability/item surfaces, `other_visible`, or `internal`). Entity-linked surfaces also require a unique `audit_key`. `preserve_internal` requires `surface`/`visibility` both `internal`, a non-empty `visibility_evidence`, and `source_reviewed_preservation` provenance. The gate hashes the complete record objects, requires each review to name its `record_file`, rejects extra review keys, and requires every record key exactly once.

When a record needs correction, keep the issue until the replacement is applied and the reviewer rechecks that key:

```json
{
  "key": "campaign/7543",
  "severity": "high",
  "source": "original text",
  "localized": "current Chinese",
  "issue": "tooltip is a word-order draft and omits the target condition",
  "suggested": "complete corrected Chinese"
}
```

The final manifest may have an empty `issues` array only after the complete `reviewed_keys` coverage has been independently rechecked. Include the source fingerprint generated immediately before the review; a changed source invalidates the manifest.

## Same-source consistency

Group visible records by exact source text after normalizing only line endings, but keep `entity_key`/`entity_id` and `surface` boundaries when writer records provide them. One semantic entity/field should have one canonical Chinese translation. Identical spelling does not make different objects or contextual senses the same entity. For a genuine within-entity variation, every affected writer record must contain a non-empty `consistency_exception` reason; accepted records and reasons appear in the gate report. Do not silently accept drift caused by separate drafting passes.

## Terminology consistency

The glossary is a contract, not a suggestion:

- Every source occurrence of a glossary term must use its canonical target, unless the glossary marks the occurrence as an identity/name exception.
- Give entity-bound glossary entries `entity_key`/`entity_id` and, when relevant, `surface`; otherwise the entry intentionally applies to every matching source occurrence.
- Search translated payloads for old targets, competing translations, English fragments, and near-synonyms before packaging.
- Review terms in context: faction nouns, adjectives, unit names, skill names, item names, place names, and mechanic terms may require distinct glossary entries.
- When a term changes, regenerate all reviewed worksheets from the clean source and repeat the full audit. Never patch only the screenshot or the first matching WTS ID.

## Required command

Run the bundled checker after writer/reviewer merge and again on the final extracted tree:

```powershell
python scripts/semantic_review_gate.py `
  --records quality/writer-campaign-*.json `
  --records quality/writer-maps/**/*.json `
  --reviews quality/review-manifest-*.json `
  --glossary quality/glossary.json `
  --entity-manifest quality/entity-links.json `
  --term-db quality/war3-terms.sqlite `
  --term-source-root quality/extracted-evidence `
  --object-root final-extracted `
  --expected-campaign campaign-sha256-or-stable-id `
  --expected-source-locale en-US --expected-target-locale zh-CN `
  --expected-client-version 1.31.1 --expected-distribution classic `
  --require-entity-audit `
  --out quality/semantic-review-gate.json
```

The independently supplied `--expected-*` values are mandatory in release mode and must match every manifest; they prevent a manifest from selecting a different client/locale by self-declaration. The checker must fail on missing or disallowed authorship provenance, missing review keys, stale source fingerprints, duplicate keys, non-empty issue arrays, within-entity source splits, glossary conflicts, replacement characters, known machine-translation artifacts, and every unresolved entity/ability/name link. Older calls remain runnable but only a report with `entity_audit.required: true`, at least one manifest, and zero issues is release evidence.
