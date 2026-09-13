# 魔兽系列共享世界观术语层

`assets/shared-lore-terms.json` 是共享世界观参考层；`assets/warcraft-iii-community-terms.json` 是更大的 WC3 社区 roster 参考层；`assets/world-of-warcraft-community-terms.json` 是 WoW 的社区参考层，覆盖种族、职业、专业、阵营、资料片、地区、角色和宇宙概念；`assets/world-of-warcraft-client-terms.json` 是从成对的英文/简体中文 WoW `GlobalStrings.lua` 客户端文件生成的 10,000+ 条 UI 译文层。四者都不提供 WC3 rawcode；WC3 文件专门覆盖社区整理的单位、英雄、建筑、技能和物品名称，WoW 文件只在 `world_of_warcraft` 产品作用域生效。

## 证据边界

- `official_reference` 只接受可定位的 Blizzard 官方页面或合法客户端证据。
- `verified_community_reference` 可来自 Warcraft Wiki、Wowhead 等社区资料，但必须保留来源并回溯官方出处；它不能冒充 Blizzard 官方译名。
- `world-of-warcraft-client-terms.json` 的 `verified_community_reference` 条目来自社区镜像的客户端语言文件；它是客户端拼写证据，但来源仓库不是 Blizzard 官方发布接口，不能写成 `official_reference`。
- WoW 专属职业、任务、物品、版本改名和玩家黑话不得写入 WC3 专属术语层。
- 同一英文名在 WC3、WoW、不同客户端版本或不同中文地区有差异时，必须分条记录；不能静默采用“最新”名称。

## 查询和校验

```powershell
python scripts/shared_lore_registry.py validate `
  --input assets/shared-lore-terms.json `
  --input assets/warcraft-iii-community-terms.json `
  --input assets/world-of-warcraft-community-terms.json `
  --input assets/world-of-warcraft-client-terms.json
python scripts/shared_lore_registry.py summary `
  --input assets/shared-lore-terms.json `
  --input assets/warcraft-iii-community-terms.json `
  --input assets/world-of-warcraft-community-terms.json `
  --input assets/world-of-warcraft-client-terms.json
python scripts/shared_lore_registry.py query `
  --input assets/shared-lore-terms.json `
  --input assets/warcraft-iii-community-terms.json `
  --input assets/world-of-warcraft-community-terms.json `
  --input assets/world-of-warcraft-client-terms.json `
  --term "Arthas" --target-locale zh-TW `
  --product warcraft_iii
```

只有 `selected` 才是唯一最高证据级别的候选；`ambiguous` 和 `no_match` 都要交给人工裁决。查询结果只供 agent 读取和写入 glossary，不执行自动替换。

## 扩展规则

新增条目时，必须填写实体类型、适用产品、源名、目标 locale、目标名、证据等级、来源 key 和来源定位。两个参考层都不填写 WC3 rawcode；rawcode、技能栏名称和对象字段必须来自独立的 WC3 客户端/地图证据。战役作者有意改名时，使用战役作用域的 override，不修改参考层。
