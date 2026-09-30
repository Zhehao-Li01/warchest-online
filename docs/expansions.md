# 扩展与自选阵容

本版支持 **47 种兵种卡**：16 张基础卡、贵族／攻城／夜幕／震慑战术合计 19 张卡，以及 Champions／Mastery／High Seas 合计 12 张网站扩展卡。Mastery 和 High Seas 是社区非官方内容；Champions 的官方身份尚未确认。通常采用双人 37 格地图和控制六个据点获胜；公海启用时增加十二格海域，英雄阵亡可以降低对手获胜目标。新扩展规则、来源和边界约定见 [网站扩展说明](community-expansions.md)。

## 怎么开局

按原方式启动：

```bash
cd /home/lzh/warchest-online
.venv/bin/python -m warchest.web --host 0.0.0.0 --port 8080
```

1. 打开 `http://localhost:8080`，填写昵称，点击 **选择扩展 / 配置双方兵种**。
2. 勾选需要的版本（基础版也可取消勾选），组军方式选择 **房主自由配置双方阵容**。
3. 切换 A / B 标签，分别选 4 个兵种；可先点“清空当前方阵容”。兵种卡展示数量和技能。
4. 选择首轮先手，保存配置，然后创建好友房间或点击“与 AI 对战”。房主执 A，好友或 AI 执 B。
5. 好友访问同一服务，用房间号或邀请链接加入。再战沿用这份阵容与扩展开关，重新洗袋、抽取法令和堡垒布局。

基础版默认勾选但不是必选项，可以只使用扩展兵种。BP 至少需要 10 种不同兵种，随机分配或自选双方阵容至少需要 8 种；兵种不足时界面和服务端都会提示。经典入门固定阵容仍使用基础版。

默认采用 **BP 禁选**：从启用扩展中抽取 10 种兵种，随机先手，先后各 Ban 1，再按先 1、后 2、先 2、后 2、先 1 的顺序 Pick。法令和堡垒布局在 BP 前公开，选兵后沿用同一份设置。每轮选足数量后确认；BP 先手也是对局先手。原版与替代版不会同时进入候选池，再战会重新 BP。也可选择直接随机分配或经典入门阵容；经典入门模式仅启用基础版。

相同兵种不能重复；重骑兵 / 枪骑兵、先锋 / 步兵、军阀 / 元帅不能同时入选，因为各组共用实体币。前端禁选，服务器再次检查；关闭扩展会移走配置中属于该扩展的兵种。

## 对局操作

延续“选手牌币 → 行动菜单 → 点击高亮格”的交互。控制仍在调遣中，点击当前所在据点执行。只有一个结果的行动会立即完成。

- **贵族**：开局抽取三道公共法令；支付皇家币选择法令后，按提示选择其具体效果。棋盘工具栏“令”可查看三道法令和双方使用状态。伯爵免费颁布不消耗印章。
- **攻城**：虚线六边形边框表示堡垒；工兵档案显示剩余供应。无主据点上的堡垒可以攻击拆除，也可以移入，但不能在一次多格移动中穿过；敌方控制的堡垒据点不能直接移入。空的无主堡垒格同时可移动和攻击时，点击该格后明确选择“移动到此格”或“拆除堡垒”。攻击先拆堡垒，不伤害格内单位，也不改变据点控制权；即使据点由己方控制，里面的敌军仍受堡垒保护，须先拆堡垒。攻城塔第二次攻击继续弹出选择。
- **夜幕**：中毒单位带绿色“毒”标记；对应币可选解毒。散兵防御弹窗可选诱饵抵挡；抽到诱饵时可暗弃使用或归还。档案显示诱饵是否可用、毒药所在格。
- **震慑战术**：震慑把整支单位的币放回其所有者明弃；不会触发长枪兵反伤。战鼓手弹窗明确区分放到己方还是对手袋顶；军阀指挥后跟踪并震慑选定友军。
- 防御选择由防御方操作。其他追加行动、技能顺序和可选效果使用相同菜单；关闭后可从“继续技能结算”恢复。
- 侦察法令的手牌内容只给施放者；普通观察、对手快照和公共日志不增加隐藏币种。

[选兵界面](screenshots/expansion-setup.png) · [桌面棋盘](screenshots/expansion-desktop.png) · [手机棋盘](screenshots/expansion-mobile.png)

## 后端阅读入口

| 文件 | 内容 |
|---|---|
| `warchest/model.py` | `Action / Stack / Player / Event / State`；新增 `State.extras` |
| `warchest/units.py` | 47 张卡的数据、扩展归属、替代版本的币种族 |
| `warchest/expansions.py` | 扩展初始化、合法行动、技能队列、结算和守恒校验 |
| `warchest/engine.py` | 公共 API、抽袋、轮次、观察；基础版与扩展版分派 |
| `warchest/serialization.py`、`recording.py` | JSON 存档、完整初始状态和逐步回放校验 |
| `warchest/ai.py` | `choose_action` 随机 AI 支持基础版及扩展 |
| `warchest/web.py` | 配置验证、持久化房间、双方权限、AI 推进 |
| `warchest/static/setup.js`、`actions.js` | 双方阵容编辑、合法行动菜单与棋盘点击步骤 |

纯基础局沿用 `base-2`，旧房间与旧示例仍可读取；仅原四个扩展启用时使用 `expansions-1`，启用任一网站扩展时使用 `expansions-2`。不要在进行中的房间更换规则版本。

`extras` 包含 `enabled`、`forts`、`poison`、`decoys`、`decrees`、`seals`。袋顶用原有袋列表末尾表示，仍不通过观察接口暴露；公共 `bag_top` 事件保留玩家可推断的信息。部署中的单位继续用 `Stack(owner, unit, count)` 表示。

`pending` 中 `x_` 开头的项是扩展续接步骤：`x_defend`、`x_order`、`x_decree_effect` 等。每次续接依然经 `legal_actions` 校验。`turn_owner` 记住原行动方，插入防御不会改变正常交替顺序。复杂战术的路径和目标保留在 `Action`；依赖攻击结果的选择（防御、后卫移动、第二次攻击等）分步列举。

```python
from warchest import new_game
from warchest.recording import new_record

armies = (
    ('bannerman', 'siege_tower', 'saboteur', 'warlord'),
    ('raider', 'skirmisher', 'herald', 'war_drummer'),
)
expansions = ['base', 'nobility', 'siege', 'nightfall', 'shock']
state = new_game(11, armies, expansions=expansions)
record = new_record(11, armies=armies, expansions=expansions)
```

省略 `expansions` 会根据阵容自动启用所需扩展。显式启用扩展即启用其机制，即使本局没有抽到该扩展兵种。`setup={'forts': [...], 'decrees': [...]}` 供确定性场景测试使用，网页不接受任意棋盘输入。

## 规则来源与裁定

- [AEG 贵族规则与 FAQ](https://www.alderac.com/wp-content/uploads/2019/08/WarChest_Nobility_Rules_Rulesheet_FINAL.pdf)
- [AEG 攻城规则与 FAQ](https://www.alderac.com/wp-content/uploads/2021/03/WarChest_Siege_1P_Rules_Rulesheet_FINAL.pdf)
- [AEG 夜幕规则与 FAQ](https://www.alderac.com/wp-content/uploads/2025/04/WarChest_Nightfall_Expansion_Rulebook_Optimized.pdf)
- [AEG 夜幕设计日志与四张印刷卡图](https://www.alderac.com/2023/05/31/war-chest-nightfall-developer-diary/)
- [AEG 震慑战术已公布规则与 FAQ](https://www.alderac.com/wp-content/uploads/2026/07/WarChest_ShockTactics_Rulebook.pdf)
- [Crowd Games 出版商的六张堡垒地图组件图](https://www.crowdgames.ru/collection/sunduk-voyny-osada)：按引擎棋盘的旋转方向转写到 `FORT_LAYOUTS`，每张四个、中心对称。
- [War Chest Online 卡牌说明](https://warchestonline.com/how-to-play)：用于卡面文字交叉核对，不包含其自制扩展。

震慑战术采用 2026 年 7 月公布规则。先锋的“须已增强”依据该官方 FAQ；线上展示卡的简写没有列出此条件，本版以 FAQ 为准。军阀的“两格内友军”包含自身，与既有旗手、元帅的范围定义一致。侦察弃置按暗弃记录，已看过的手牌保留在施放者的私有历史中。规则解释集中于此，后续官方勘误应连同版本和回归测试一起更新。

## 验证与复现

```bash
.venv/bin/python -m pytest -q
WC_BROWSER=1 PLAYWRIGHT_BROWSERS_PATH=.venv/browsers .venv/bin/python -m pytest tests/test_browser.py -q
.venv/bin/python -m scripts.validate_expansions
.venv/bin/python -m warchest replay examples/expansion-win.json --view A --step
```

[扩展规则覆盖表](expansion-rules.md) · [固定种子模拟结果](expansion-simulation-results.json) · [扩展正常获胜回放](../examples/expansion-win.json) · [上限截断回放](../examples/expansion-random.json)

随机模拟每局至胜利或 2,000 次决定，包括追加技能和防御。`truncated` 仅表示达到测试上限。每步验证币数、毒药、诱饵、堡垒及控制点守恒；同时检查随机 AI 返回的也是合法行动，并定期保存恢复。它验证规则执行稳定性，不证明竞技棋力或覆盖所有可能组合。

本轮规则、实现、文案核对结果见 [规则审查记录](rules-audit.md)，其中单独列出了现有组军流程与官方规则的差异。

游戏指南（棋盘工具栏 `?`）提供基础版与七个扩展的分项规则，本局启用的扩展默认展开。
