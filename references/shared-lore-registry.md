# 魔兽系列共享世界观术语层

`assets/shared-lore-terms.json` 是一个小型、可审计的共享世界观参考层，不是 WC3 客户端词库，也不提供 rawcode。它只用于人物、地点、种族、阵营、宇宙设定和历史名词等跨作品实体。

## 证据边界

- `official_reference` 只接受可定位的 Blizzard 官方页面或合法客户端证据。
- `verified_community_reference` 可来自 Warcraft Wiki、Wowhead 等社区资料，但必须保留来源并回溯官方出处；它不能冒充 Blizzard 官方译名。
- WoW 专属职业、任务、物品、版本改名和玩家黑话不得写入 WC3 专属术语层。
- 同一英文名在 WC3、WoW、不同客户端版本或不同中文地区有差异时，必须分条记录；不能静默采用“最新”名称。

## 查询和校验

```powershell
python scripts/shared_lore_registry.py validate `
  --input assets/shared-lore-terms.json
python scripts/shared_lore_registry.py summary `
  --input assets/shared-lore-terms.json
python scripts/shared_lore_registry.py query `
  --input assets/shared-lore-terms.json `
  --term "Arthas" --target-locale zh-TW `
  --product warcraft_iii
```

只有 `selected` 才是唯一最高证据级别的候选；`ambiguous` 和 `no_match` 都要交给人工裁决。查询结果只供 agent 读取和写入 glossary，不执行自动替换。

## 扩展规则

新增条目时，必须填写实体类型、适用产品、源名、目标 locale、目标名、证据等级、来源 key 和来源定位。共享层的条目不填写 WC3 rawcode；rawcode、技能栏名称和对象字段必须来自独立的 WC3 客户端/地图证据。战役作者有意改名时，使用战役作用域的 override，不修改共享层。
