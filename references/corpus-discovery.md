# Complete Corpus Discovery

## Why this step is mandatory

Warcraft III localization text is distributed across nested archives and binary references. Translating only `war3campaign.wts`, or only strings that lack Chinese, misses chapter dialogue, object names, loading screens, and direct script text.

## Archive layers

```text
campaign.w3n
├── war3campaign.w3f
├── war3campaign.wts
├── war3campaign.w3u/.w3a/.w3t/.w3b/.w3d/.w3h/.w3q
├── war3campaignImported\...
└── Chapter.w3x
    ├── war3map.wts
    ├── war3map.j or war3map.lua
    ├── war3map.w3i
    ├── war3map.w3u/.w3a/.w3t/...
    └── imported assets
```

Always extract from the current source artifact. Do not reuse an older extraction after the user supplies a better source or after the campaign changes.

Decode BOM/UTF-8 automatically. If a source is stored in a legacy code page, determine it from authoritative context and pass it explicitly with `--encoding cp1251`, `--encoding cp1252`, or the correct value. Never silently fall back to a guessed Western code page: mojibake is worse than a hard stop.

## Corpus layers

### Campaign selection

`war3campaign.w3f` contains the campaign name, difficulty, author, description, chapter titles, map titles, background screen, minimap, and ambient music. Its text may be direct or `TRIGSTR_*` references into `war3campaign.wts`.

Scan the binary W3F for every `TRIGSTR_*`, including values with leading zeros. Normalize IDs numerically (`TRIGSTR_020` and WTS `STRING 20` are the same record).

### Campaign object data

Scan campaign object files for `TRIGSTR_*` references:

- units: `.w3u`
- abilities: `.w3a`
- items: `.w3t`
- buffs/effects: `.w3h`
- destructibles: `.w3b`
- doodads: `.w3d`
- upgrades: `.w3q`

Record the object rawcode and field tag for context. Common visible fields include names, editor suffixes that become UI suffixes, basic/extended tooltips, research tips, hotkeys, hero proper names, awakening text, and item descriptions.

Inventory both `TRIGSTR_*` references and direct null-terminated strings in object/metadata binaries. The latter list deliberately includes paths, raw labels, and other noise; classify every candidate, translate only fields proven player-visible, and leave every other string byte-for-byte unchanged.

For terminology linkage, record object identity as campaign/map scope + object type + rawcode/stable key. WTS IDs remain text references only. `campaign_inventory.py` supplies broad candidates and TRIGSTR locations; it does **not** parse `uabi`/`uhab` or manufacture entity/mention coverage. Build the manifest described in [entity-link-audit.md](entity-link-audit.md) from a separately verified object parser or the documented `manual_verified` contract. Do not infer inherited values without matching-version base object data; record dynamic or unresolved references explicitly so the release gate fails closed.

### Map WTS

Treat every real `STRING` block as in scope on the first pass. WTS often contains comments between the `STRING` line and opening brace:

```text
STRING 17
// Units: n002 (Frost Lord Core), Name (Name)
{
Frost Lord Core
}
```

A parser that expects `{` immediately after `STRING` silently loses these records. Count anchored `^STRING` declarations and require the localized patch to cover the same IDs.

### Scripts

Search `war3map.j`, `war3map.lua`, and imported script files for visible literals used by:

- `DisplayText*`, `QuestSet*`, `CreateQuest`, `SetMapDescription`;
- cinematic subtitles and transmissions;
- cinematic speaker labels and runtime unit names, including direct strings passed to custom actor constructors such as `ScreenplayFactory.createActor`, `BlzSetUnitName`, and `BlzSetHeroProperName`;
- leaderboard, multiboard, timer, dialog, button, and game-message APIs;
- dynamically assembled tooltips or objectives.

The inventory reports every script string literal. It classifies literals on visible API calls and literals assigned to variables later used by visible APIs, but the unclassified remainder still requires manual review. This deliberate over-collection prevents dynamically assembled text from being missed.

Do not translate rawcodes, function names, paths, order strings, cache keys, or debug-only markers without evidence they display.

Speaker names are a separate visible layer from dialogue bodies. A translated `ScreenplayMessages` table does not localize an actor name supplied by a constructor or copied from a runtime unit name. Inventory and review every explicit actor-name argument and every runtime name setter, then scan the localized scripts for remaining Latin speaker labels before release.

### Map metadata and images

Inspect `war3map.w3i`, loading-screen configuration, imported BLP/TGA/DDS/PNG/JPG files, videos, and custom UI panels. Render or convert likely text-bearing images and inspect them visually. For every visual-manifest row, fill `contains_text`, `reviewed`, and `localized_path`; no `reviewed: false` row may remain at release. If English text is baked into an image that players see, localize the image while preserving dimensions, alpha, compression, and path.

### Credits and identity text

Translate surrounding prose but preserve:

- author and contributor usernames;
- email addresses and URLs;
- tool/site/product names;
- song titles and band names unless an established Chinese title exists;
- fictional-language phrases where the phrase itself is characterization;
- internal `dummy`, effect, attachment, and raw labels proven not to display.

## Inventory report

Run:

```powershell
python scripts/campaign_inventory.py --root <extracted-root> --out corpus-inventory.json
# Legacy Cyrillic example:
python scripts/campaign_inventory.py --root <extracted-root> --out corpus-inventory.json --encoding cp1251
```

The report must include:

- WTS files and exact string counts;
- W3F metadata and referenced IDs;
- object-file reference IDs and file origins;
- direct binary-string candidates and their offsets;
- every script literal with stable string indexes and visibility classification;
- imported FDF/TOC/TXT/INI/SLK text candidates;
- likely text-bearing visual assets;
- audio/video assets;
- duplicates, missing references, and decoding failures.
- broad candidates needed to create separately reviewed scoped entity/ability/mention evidence; the inventory report alone is not that evidence.

Use this report to define translation segments and final expected counts.
