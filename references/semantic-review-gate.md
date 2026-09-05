# Semantic Review Gate

Structural checks prove that IDs, control codes, placeholders, and archive entries survived. They do not prove that Chinese is natural or that every record was reviewed. Use this gate for every release.

## Translation provenance

The gate must reject a translated record unless its `provenance` is exactly `agent_authored` or `human_authored`. For a deliberately preserved identity string, `source_reviewed_preservation` is also allowed. Missing provenance is a failure. Review does not convert automatic translation into acceptable authorship: machine translation, translation APIs, browser translators, LLM batch-translation endpoints, MT caches, automatic dictionary substitution, and generated translation worksheets are prohibited even as drafts.

## Review manifest

Each disjoint review segment must be a JSON object:

```json
{
  "segment": "campaign-00000-05500",
  "source_fingerprint": "SHA256 of the exact source-record JSON",
  "reviewed_keys": ["1", "2", "3"],
  "reviewed_count": 3,
  "issues": []
}
```

`reviewed_keys` must contain every stable key in the assigned record file, including records ultimately marked `preserve_internal` or `preserve_identity`. The list must be unique and sorted. `reviewed_count` must equal its length. A plain `[]` review file is not evidence of review coverage and must fail the gate.

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

Group all visible records by exact source text after normalizing only line endings. One source string must have one canonical Chinese translation across campaign WTS, map WTS, object fields, scripts, quests, and UI. If context genuinely requires a variation, list the stable keys and the reason in an explicit exception file. Do not silently accept differences caused by separate machine-translation batches.

## Terminology consistency

The glossary is a contract, not a suggestion:

- Every source occurrence of a glossary term must use its canonical target, unless the glossary marks the occurrence as an identity/name exception.
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
  --out quality/semantic-review-gate.json
```

The checker must fail on missing or disallowed authorship provenance, missing review keys, stale source fingerprints, duplicate keys, non-empty issue arrays, same-source translation splits, glossary conflicts, replacement characters, and known machine-translation artifacts. Its output is part of the release report.
