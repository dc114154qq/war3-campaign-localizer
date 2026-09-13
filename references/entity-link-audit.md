# 实体关联与技能提及审计

`scripts/entity_term_audit.py` 验证“单位实际技能列表 → 技能实体 → 技能栏/学习名称 → 单位描述中的名称提及”。它只识别和核对，不生成译文。

## 身份与来源

实体身份是 `campaign + map + object_type + stable_key/rawcode`；WTS ID 只是文本记录位置。不同地图相同 rawcode、不同实体相同英文名、共享 WTS、直接文本都必须分别建模。形态、等级和显示面用 `form`、`level`、`role` 精确区分。

`scripts/object_link_inventory.py` 从实际提取目录解析 `.w3u/.w3a` 和同目录 `war3map.wts`，只采用已核实字段：`uabi`（普通技能列表）、`uhab`（英雄技能列表）、`utip`/`utub`（单位按钮/扩展描述），以及 `anam`/`atp1`/`aret`（规范名称、普通按钮提示、学习提示）。字段到 role 固定为 `anam→canonical`、`atp1→button`、`aret→learn`，level 和 data_pointer 也必须相等。它生成带原文件 hash 的实体、槽位和 WTS 清单；发布 gate 会现场重建并与 manifest 双向对账。其他字段不猜测；确需补充时才用 `manual_verified` 并给出准确 source_location 和哈希证据。自定义对象未覆写的基础技能列表只有在对应客户端版本的基础对象资料存在时才可标 `inherited`。动态脚本引用、未知字段、缺基础资料和未解析引用都会阻断发布。

## Manifest 契约（schema_version 1）

顶层字段：

- `source_fingerprint` 与 `evidence_files`：列出用于抽取的本地相对路径及 SHA256，再对规范化清单计算 SHA256。脚本实查文件与两层 hash；输入变化后必须重建。空实体、无单位/技能/绑定的 manifest 不是发布证据。
- `context`：非空 `campaign`、`source_locale`、`target_locale`、`client_version`、`distribution`。
- `texts`：`key`、与最终 writer record 相连的 `record_key`、对象字段中实际保存的 `storage_ref`（例如精确的 `TRIGSTR_10`）、最终 `text`、`source_location`。WTS key 建议写成 `map:wts:ID`，因此不同地图不会碰撞。
- `entities`：单位或技能实体，每个都用 `inventory_key` 绑定现场解析对象，且 `scope.map` 必须等于对象文件相对 `--object-root` 的父目录（根目录对象用 `.`）。`ability_scan.inventory_keys` 必须列全 `uabi/uhab` 槽，并由 direct bindings 对槽内 rawcode 做集合完全覆盖；`description_review.surfaces` 和 display name 分别把字段槽位连到实际 direct/WTS 文本引用。所有单位还必须列出已审查描述位置和精确 mention keys。
- `mentions`：描述中每一处已确认的技能名跨度；不得用空的“全通过”清单替代实际提及。
- `aliases`：有来源、理由且可限制到 `mention_keys` 的作者有意别名。
- `exceptions`：仅用于证据充分的单个 `mention_name_mismatch`；必须精确写 key、expected_name、actual_name、reason 和 source_location。未命中的例外也会失败。

最小结构示例（示例 rawcode/名称均为测试占位，不是官方词库）：

```json
{
  "schema_version": 1,
  "source_fingerprint": "抽取输入清单的64位十六进制SHA256",
  "evidence_files": [
    {"path": "inventory/corpus-inventory.json", "sha256": "该文件的64位十六进制SHA256"}
  ],
  "context": {
    "campaign": "campaign-sha256-or-stable-id",
    "source_locale": "en-US",
    "target_locale": "zh-CN",
    "client_version": "1.31.1",
    "distribution": "classic"
  },
  "texts": [
    {"key": "m:wts:10", "record_key": "m:wts:10", "storage_ref": "TRIGSTR_10", "text": "|cffffcc00测|r试技能", "source_location": "m/war3map.wts:STRING 10"},
    {"key": "m:wts:20", "record_key": "m:wts:20", "storage_ref": "TRIGSTR_20", "text": "可使用测试技能。", "source_location": "m/war3map.wts:STRING 20"}
  ],
  "entities": [
    {
      "id": "m:unit:n001", "scope": {"campaign": "campaign-sha256-or-stable-id", "map": "m"},
      "object_type": "unit", "rawcode": "n001", "stable_key": "n001",
      "inventory_key": "m/war3map.w3u:table:1:object:0",
      "source_location": "m/war3map.w3u:n001",
      "ability_scan": {"status": "complete", "inventory_keys": ["m/war3map.w3u:table:1:object:0:mod:3"], "bindings": [{
        "key": "m:n001:uabi:A001", "field": "uabi", "resolution": "direct",
        "ability_entity_id": "m:ability:A001", "source_location": "m/war3map.w3u:n001:uabi",
        "inventory_key": "m/war3map.w3u:table:1:object:0:mod:3"
      }]},
      "description_review": {
        "status": "complete",
        "source_locations": ["m/war3map.w3u:n001:utub"],
        "surfaces": [{"inventory_key": "m/war3map.w3u:table:1:object:0:mod:7", "text": {"kind": "wts", "key": "m:wts:20"}}],
        "mention_keys": ["m:n001:utub:mention:0"]
      }
    },
    {
      "id": "m:ability:A001", "scope": {"campaign": "campaign-sha256-or-stable-id", "map": "m"},
      "object_type": "ability", "rawcode": "A001", "stable_key": "A001",
      "inventory_key": "m/war3map.w3a:table:1:object:0",
      "source_location": "m/war3map.w3a:A001",
      "display_names": [{
        "role": "button", "level": null, "form": null, "data_pointer": 0, "source_name": "Example Ability",
        "inventory_key": "m/war3map.w3a:table:1:object:0:mod:2",
        "text": {"kind": "wts", "key": "m:wts:10"}
      }]
    }
  ],
  "mentions": [{
    "key": "m:n001:utub:mention:0", "status": "resolved",
    "owner_entity_id": "m:unit:n001", "ability_entity_id": "m:ability:A001",
    "expected_role": "button", "level": null, "form": null,
    "observed_name": "测试技能",
    "span": [3, 7],
    "description": {"kind": "wts", "key": "m:wts:20"},
    "source_location": "m/war3map.w3u:n001:utub"
  }],
  "aliases": [],
  "exceptions": []
}
```

直接文本使用 `{"kind":"direct","value":"...","record_key":"...","source_location":"..."}`，对象槽值必须逐字等于 `value`；WTS 引用会现场跟进同地图的 `war3map.wts`，并要求 text key 与 record_key 都严格派生为 `<对象父目录>:wts:<规范化十进制ID>`。`span` 是未经修改 description 中精确框住所见名称的 `[start,end]` Python 字符索引，不能从更长的错误名称中只挑目标名称子串。描述提及的 `expected_role` 只能是实际技能栏/学习界面的 `button` 或 `learn`；不能声明 `canonical`/`anam` 来绕过按钮或学习提示名称差异。审计还会仅围绕本单位实际绑定技能的 `button`/`learn` 显示名寻找精确匹配；两字名称检查一字符替换，三字及以上另查一字符增删改候选，防止用空 mentions 隐藏细微错名。它不是全文词典扫描，更复杂变体仍须人工完整审查。数据库和 manifest 的 role/level/form 必须一致；每个 display name 还要记录原文 `source_name` 和现场 `data_pointer`。

继承绑定还必须有非空 `base_data_source`、`base_entry_locator` 和 `inherited_rawcodes`，继承技能实体必须有 `inherits` 与 `base_data_status: "available"`；基础资料本身必须列在 `evidence_files`。当 manifest 从文件读取时，`base_data_source` 必须是 UTF-8 JSON，且 `entries` 中有唯一 `{"record_kind":"ability_list","entry_locator":"...","rawcodes":[...]}` 与绑定声明逐项一致；目标技能 rawcode 必须在该列表内。alias 必须含 `entity_id`、`alias`、`reason`、`source_location`、`registry_source_key` 和非空 `mention_keys`，且该名称/来源必须已在术语库作为强证据 alias 登记。exception 还必须用 `evidence_path` 指向已哈希的 evidence file。

正式发布的 entity surface writer records（单位描述、技能名/按钮/学习提示）必须有唯一 `audit_key`；gate 要求每个 key 恰好被 manifest 文本消费一次并逐字等于最终 translation，防止审计平行的“正确副本”。

优先把确有其名的变体登记为 alias。只有无法表达为实体别名、且该单次差异有独立证据时才用 exception；审计报告会列出所有实际应用的例外，便于发布复核。

## 运行与诊断

```powershell
python scripts/object_link_inventory.py --root final-extracted `
  --out quality/object-link-inventory.json
python scripts/entity_term_audit.py --manifest quality/entity-links.json `
  --term-db quality/war3-terms.sqlite --out quality/entity-term-audit.json
```

错误退出 1；manifest/数据库无效退出 2。报告中的每项问题都含稳定 key、source_location 和 code；名称问题另含 expected_name、actual_name、ability_entity_id。控制码、颜色和热键标记只在比较时归一化，原文本、等级、占位符均不修改。

发布时必须经 `semantic_review_gate.py --object-root final-extracted --require-entity-audit` 调用此逻辑，不能只单独跑一份未纳入发布报告的审计。现场解析的每个相关对象和字段槽位必须在 manifests 中恰好覆盖，对象槽、TRIGSTR ID、实际 WTS 文本和 writer record 必须闭环，技能列表 rawcode 集合也必须完全一致；这防止把实际单位描述误标成无关 surface、重定向到“正确副本”或只登记列表中的一个技能。常见阻断码包括 `mention_name_mismatch`、`mention_role_not_skill_bar`、`undeclared_potential_mention`、`inventory_wts_text_mismatch`、`inventory_wts_record_key_mismatch`、`inventory_ability_list_mismatch`、`inventory_display_role_mismatch`、`unresolved_ability_reference`、`base_data_missing`、`wrong_ability_binding` 和 `term_decision_unresolved`。
