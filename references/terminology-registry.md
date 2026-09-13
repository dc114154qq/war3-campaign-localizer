# Warcraft III 术语证据库

此库用于查证和裁决，不生成或自动替换译文。JSON 导入契约为 v1，SQLite schema 为 v2。随 skill 交付的 `assets/war3-terminology.sqlite` 是可运行的空证据库；远端没有用户客户端资料，故未凭模型记忆填入“官方译名”。`assets/terminology-seed.json` 是可审核的空构建输入。

只导入用户合法拥有并已提取的游戏资料，或小规模、可定位的公开 Blizzard 权威页面证据。不要下载盗版客户端/数据包，也不要抓取大型站点全文。

## 证据边界与优先级

库只接受 `product: "warcraft_iii"`，拒绝把 World of Warcraft 条目混入。locale 必须明确，如 `zh-CN`、`zh-TW`；客户端版本和发行口径（例如 `classic`、`reforged`）也是裁决键。

证据状态只有：

- `official_reference`：目标版本 Warcraft III 客户端的合法提取字符串，或可定位、可哈希的 Blizzard 官方资料。官方网页只能证明网页展示的名称；没有 rawcode 时不得伪填 rawcode。
- `verified_community_reference`：有可审核来源且经人工核对的可靠社区参考，不能冒充官方客户端资料。
- `campaign_override`：地图/战役自身对实体的改名或最终裁决；必须绑定 campaign/map 作用域，并引用包含目标 locale 裁决及原对象证据定位的 `campaign_term_decision` 文件。
- `unverified`：待人工核实；永不被查询器选为最终裁决。

运行时先选择最具体的 map/campaign 实体。在同一实体、source/target locale、版本、发行口径与显示面内，`official_reference` 优先于 `campaign_override`，后者再优先于 `verified_community_reference`；`unverified` 永不入选。若最具体的自定义实体只有显式 `campaign_override`，它会先于该实体继承的全局名入选。查询缺版本/发行口径，或只有别的版本/地区时，返回 `ambiguous` 并列出证据，不静默采用最新记录。相同证据级别、相同裁决身份但目标名冲突的 canonical 行会整批回滚拒绝。跨地图/战役继承与不同 object_type 继承在导入和发布复核时拒绝。

## 可解析证据格式与直接导入

强证据来源文件不能是任意字节或只靠一个自报 locator。`official_reference`、`verified_community_reference`、`campaign_override` 的每个条目都必须存在于下述 UTF-8 JSON `entries` 中；导入和 `validate` 会把 `entry_locator` 解析到唯一行，并逐项核对 entity key/type/rawcode/stable key、source/target 名称、locale、版本、发行口径、role/level/form。测试夹具必须明确写明非权威，不能因格式通过就冒充官方资料。

这是从用户合法提取资料整理后的规范交换格式。转换时保留原提取文件的路径/hash/提取命令在 `source_capture` 或项目来源清单中；脚本不下载客户端资源。单文件可用 `import-evidence` 直接建实体并导入：

```json
{
  "schema_version": 1,
  "source": {
    "source_key": "client-1.31.1-zhcn-extract",
    "product": "warcraft_iii",
    "source_kind": "extracted_client_string",
    "client_version": "1.31.1",
    "distribution": "classic",
    "locale": "zh-CN",
    "notes": "由用户合法安装的已提取字符串/对象记录规范化"
  },
  "source_capture": [{"path": "原提取清单中的相对路径", "sha256": "原文件hash"}],
  "entries": [{
    "record_kind": "name",
    "entry_locator": "Objects/AHxx/Name",
    "product": "warcraft_iii",
    "entity_key": "wc3:ability:AHxx",
    "scope": {"kind": "global"},
    "object_type": "ability",
    "rawcode": "AHxx",
    "stable_key": "AHxx",
    "inherits_entity_key": null,
    "source_locale": "en-US",
    "source_name": "Example Name",
    "target_locale": "zh-CN",
    "target_name": "从证据逐字录入的示例译名",
    "client_version": "1.31.1",
    "distribution": "classic",
    "name_role": "canonical",
    "level": null,
    "form": null,
    "evidence_status": "official_reference"
  }]
}
```

以上 `AHxx` 和名称只是格式占位，不是权威条目。alias entry 把 `record_kind` 改为 `alias`，并提供 `locale`、`alias`、`alias_kind`；其余实体/版本/证据字段相同。

```powershell
python scripts/term_registry.py import-evidence --db quality/war3-terms.sqlite `
  --input quality/extracted-evidence/client-1.31.1-zhcn.json `
  --source-root quality/extracted-evidence
```

## 多来源 Bundle 导入格式（schema_version 1）

需要一次事务合并多个来源或先定义继承时，导入文件只含 `schema_version`、`sources`、`entities`、`names`、`aliases`。每个 strong name/alias 仍必须在相应 source locator 指向的上述规范证据 JSON 中有完全匹配的 entry；bundle 不能绕过内容核验。不直接猜测未知 SLK、TXT 或二进制字段。

```json
{
  "schema_version": 1,
  "sources": [{
    "source_key": "client-1.31.1-zhcn-unitstrings",
    "product": "warcraft_iii",
    "source_kind": "extracted_client_string",
    "locator": "1.31.1/zh-CN/client-evidence.json",
    "sha256": "源文件的64位十六进制SHA256",
    "client_version": "1.31.1",
    "distribution": "classic",
    "locale": "zh-CN",
    "notes": "用户从合法安装中提取"
  }],
  "entities": [{
    "entity_key": "wc3:ability:AHxx",
    "scope": {"kind": "global"},
    "object_type": "ability",
    "rawcode": "AHxx",
    "stable_key": "AHxx",
    "inherits_entity_key": null,
    "notes": "示例占位符，不是权威条目"
  }],
  "names": [{
    "entity_key": "wc3:ability:AHxx",
    "source_locale": "en-US",
    "source_name": "Example Name",
    "target_locale": "zh-CN",
    "target_name": "人工从上述证据录入的名称",
    "client_version": "1.31.1",
    "distribution": "classic",
    "evidence_status": "official_reference",
    "source_key": "client-1.31.1-zhcn-unitstrings",
    "entry_locator": "Objects/AHxx/Name",
    "name_role": "button",
    "level": null,
    "form": null,
    "canonical": true,
    "notes": "定位到具体键名/行号"
  }],
  "aliases": [{
    "entity_key": "wc3:ability:AHxx",
    "locale": "zh-CN",
    "alias": "经证据确认的别名",
    "alias_kind": "official_alias",
    "evidence_status": "official_reference",
    "client_version": "1.31.1",
    "distribution": "classic",
    "source_key": "client-1.31.1-zhcn-unitstrings",
    "entry_locator": "Objects/AHxx/OfficialAlias",
    "notes": "别名证据定位"
  }]
}
```

`scope.kind` 为 `global`、`campaign` 或 `map`。campaign 作用域要求 `campaign`，map 还要求 `map`。`stable_key` 必填；rawcode 只在证据确实提供四字符对象 ID 时填写。自定义对象即使 rawcode 与另一地图相同，也以作用域区分。继承用 `inherits_entity_key`，不能因为 rawcode 相似而推断。

非 `unverified` 名称/别名必须引用已导入 source，其版本、发行口径和目标 locale 必须与 source 完全一致。导入任何 source 时 `--source-root` 必填；locator 必须是该目录下的安全相对路径，脚本会实算并比对规范证据 JSON 的 hash，再解析 entry 内容。网页证据应只保存必要的小段页面/JSON 响应及其原定位到规范证据文件，不抓取大型站点全文。campaign override 的 source 应包含最终中文裁决和原对象证据定位，而非只有外文原名。

证据状态与 source_kind 固定对应：official 只接受 `extracted_client_string`/`blizzard_official_excerpt`，community 只接受 `verified_community_excerpt`，override 只接受 `campaign_term_decision`。每个 name/alias 还必须用 `entry_locator` 定位到证据文件内的键、行或决策路径。网页 excerpt 不能给实体建立 rawcode；网页种子只能用 rawcode-free stable key，之后若要关联客户端 rawcode，必须另导入客户端对象证据。

## 命令

```powershell
# 查看随附空库
python scripts/term_registry.py summary --db assets/war3-terminology.sqlite

# 在新路径可靠重建并导入证据
python scripts/term_registry.py init --db quality/war3-terms.sqlite
python scripts/term_registry.py import-json --db quality/war3-terms.sqlite `
  --input quality/client-terms.json --source-root quality/extracted-evidence
python scripts/term_registry.py validate --db quality/war3-terms.sqlite `
  --source-root quality/extracted-evidence

# 精确查名；只有 selected 时退出 0，歧义/无匹配退出 2，输入或数据库错误退出 1
python scripts/term_registry.py query --db quality/war3-terms.sqlite `
  --object-type ability --rawcode A001 --campaign my-campaign --map chapter-01 `
  --source-locale en-US --target-locale zh-CN `
  --client-version 1.31.1 --distribution classic `
  --name-role button
```

把查询 JSON 和 source 清单保留在质量证据目录。agent 读取候选和证据后直接创作/裁决；不得把数据库用作批量替换器。最终 campaign override 也先导入库，再由实体关联审计消费。
