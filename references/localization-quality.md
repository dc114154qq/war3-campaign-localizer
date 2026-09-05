# Chinese Localization Quality

## Authorship requirement

Every Chinese translation must be written directly from the original source by the executing reasoning agent or a human writer. Do not use machine translation, translation APIs, browser translators, LLM batch-translation endpoints, MT caches, automatic dictionary substitution, or generated translation worksheets, even as drafts. Automated tools may extract and validate records, but they may not propose the Chinese wording.

Each translated record must declare `provenance: "agent_authored"` or `provenance: "human_authored"`. A preserved identity string may instead use `provenance: "source_reviewed_preservation"` after the writer has inspected the original and deliberately chosen not to translate it.

## Source-language handling

This workflow is not English-only. It applies to English, Russian, Polish, German, French, Spanish, Portuguese, Italian, Czech, Ukrainian, and other identifiable source languages, including campaigns that mix languages between chapters or assets.

- Detect the language and encoding per file or coherent segment. Encoding (`UTF-8`, `cp1251`, `cp1252`, and so on) and language are separate facts.
- Translate directly from the original language when its meaning can be established reliably. Do not generate an English or Chinese machine-translation draft first; the writer must establish meaning from the original plus context.
- If a passage uses an unfamiliar language, obtain a literal semantic gloss first, then write the final Chinese from the original plus context. Mark unresolved ambiguity instead of inventing meaning.
- Preserve speaker register, grammatical negation, certainty, gender/number cues, titles, faction relationships, and culturally meaningful names. Chinese should read naturally rather than imitate the source language's word order.
- Establish transliteration from official Warcraft usage, author-provided spelling, lore identity, and source pronunciation. Do not translate a proper name merely because it resembles a common noun or verb.
- Detect mixed-language credits, fictional incantations, Latin phrases, and borrowed English UI terms separately. Preserve them only under the same identity/credit exceptions used elsewhere.

## Target voice

Use natural, restrained Chinese that fits Warcraft III: direct military objectives, readable fantasy dialogue, and exact gameplay descriptions. Avoid literal English syntax, contemporary internet slang, inflated archaic diction, and invented lore.

## Terminology

Build a campaign glossary before translation and keep it versioned. Prefer, in order:

1. official Chinese Warcraft terminology available in local game strings;
2. established high-quality Chinese campaign usage;
3. consistent transliteration for original proper nouns;
4. a concise descriptive translation when a custom mechanic needs clarity.

Never let the same skill, item, unit, character, place, or faction use different names between dialogue, objectives, buttons, and object tooltips.

After drafting, group identical source strings across every layer and choose one canonical target. Treat unexplained variants as translation defects, even when each individual sentence is grammatical. Re-scan all visible payloads after every glossary change; checking only records that contain no English is insufficient because competing Chinese terms can both pass a residual scan.

## Dialogue

- Identify the speaker, listener, relationship, current objective, and previous line.
- Preserve intent, tone, certainty, negation, and faction relationships.
- Repair broken source-language prose only when context makes the intended meaning clear.
- Do not invent an action, destination, relationship, or motivation to complete a truncated sentence. Use a natural ellipsis when meaning is unavailable.
- Treat nicknames and historical aliases as the same character when lore confirms it.

## Quests and hints

- State the exact player action, object, count, location, failure condition, and required hero.
- Cross-check item rawcodes, spawned objects, regions, and trigger conditions when the source is ambiguous.
- Correct obvious source typos when the script proves the real objective, such as `crate` misspelled as `create`, or `can` misspelled as `cant`.
- Never preserve a source typo that would direct the player to the wrong item or reverse a success condition.

Preferred UI terms:

- Main Quest: 主线任务
- Optional Quest: 可选任务
- Quest Updated: 任务更新
- Quest Complete: 任务完成
- Quest Failed: 任务失败
- Hint: 提示
- Requires: 需要
- Train: 训练
- Build: 建造
- Research: 研究
- Revive: 复活

## Skills and items

Describe mechanics in this order when practical:

1. action and targets;
2. damage/healing/control effect;
3. duration, interval, range, area, chance, or scaling;
4. exceptions and failure conditions;
5. level table, cooldown, and mana cost.

Use clear Chinese mechanics:

- deals X damage: 造成 X 点伤害
- lasts X seconds: 持续 X 秒
- every X seconds: 每 X 秒
- area of effect: 影响范围
- cooldown: 冷却时间
- cast range: 施法距离
- movement/attack speed: 移动速度/攻击速度
- hit points/mana: 生命值/魔法值

Cross-check suspicious values against object fields and JASS/Lua. Common dangerous errors:

- `quarter` becoming four times;
- `miss` becoming hit;
- `can`/`can't` reversal;
- percent current/max health becoming flat damage;
- per-attribute scaling losing “每点力量/敏捷/智力”;
- seconds becoming milliseconds;
- level numbers becoming chapter numbers;
- source and target of extra damage being reversed;
- radius, range, duration, and cooldown changing places.

## Warcraft formatting

Preserve the ordered semantics of:

- `|cAARRGGBB` and `|r`;
- `|n`;
- `%d`, `%s`, and similar format placeholders;
- `<A000,DataA1>` style object-field placeholders;
- numeric values, slash-separated level lists, and percentages;
- physical line breaks where the UI requires them.

Color codes are case-insensitive. Repair a demonstrably broken source code only with an explicit approved exception.

Hotkey color codes embedded in English words must be re-anchored to the matching Chinese button character. Never leave broken fragments such as `nchorite`, `arrior`, or a colored English letter floating outside a translated name.

## Machine-translation rejection patterns

Reject and retranslate records containing symptoms such as:

- Train translated as “列车”;
- deal damage translated as “交易” or “发牌”;
- stun translated as “令人惊艳”;
- lasts translated as “最后的作品”;
- ground/air unit translated as “土地单位/空气单元”;
- `Max` transliterated as “马克斯” in a numeric mechanic;
- names translated as ordinary verbs or nouns;
- English word fragments caused by colored hotkeys;
- syntactically Chinese text whose subject, target, or mechanism cannot be explained.

A source-language residual scan catches omissions; it does not establish semantic correctness.
