# 战争之匣规则引擎

支持 **双人在线对战、基础版与四个官方扩展共 35 种兵种卡、中文响应式网页、网页基础/随机 AI 陪练、命令行随机 AI 与可校验回放**。Python 3.12+；规则核心仅依赖标准库，网页使用 Flask + Waitress。包含法令、堡垒、中毒、诱饵、震慑与替代兵种。

## 网页双人对战

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[web,test]'
.venv/bin/python -m warchest.web --port 8080
```

浏览器打开 **http://localhost:8080**，输入昵称并创建房间。好友访问同一服务，使用邀请链接或六位房间号加入。默认从全部 16 兵种中随机分配双方各 4 种，并随机决定先手；也可选择固定的经典入门阵容，或点击“选择扩展 / 配置双方兵种”，由房主为双方自由选择各四个兵种。详见 [扩展与选兵说明](docs/expansions.md)。

- 点击手牌币 → 选择行动。增强、控制、抢先等唯一结果立即完成。
- 首页点击“与 AI 对战”可选择基础 AI 或随机 AI，无需第二位玩家。
- 控制已并入调遣：选择币 → 调遣 → 点击单位脚下的高亮据点。各兵种攻击与受击有简单动画。
- 调遣、部署、战术需要目标时，在棋盘上点击高亮格；多步战术继续选择路径或目标。
- 剑士可选择攻击后留在原地；战斗牧师、步兵、狂战士等追加行动由界面继续引导。
- 皇家卫队的防御由被攻击方选择，随后自动回到攻击者完成技能结算。
- 技能弹窗关闭后，点击“继续技能结算”即可重新打开。
- 支持兵种图鉴、供给/弃置/移除数量、行动日志、坐标开关、可选音效、认输和双方同意再战。
- 房间存入 `data/rooms.sqlite3`；刷新或短暂断网后自动恢复。座位凭证保存在本浏览器中，关闭标签页后可从大厅返回原房间。

局域网好友用 **本机局域网 IP:8080** 访问，不要分享 `localhost` 链接。跨公网需要把服务部署到可访问的服务器并配置 HTTPS 域名；项目已提供服务，未替你发布到公网。部署与接口见 [联机说明](docs/web.md)。

[桌面截图](docs/screenshots/desktop.png) · [手机截图](docs/screenshots/mobile.png)


## 开始对局

在项目根目录运行：

```bash
python3 -m warchest play
python3 -m warchest play --side B --seed 7
```

A 方：剑士、长枪兵、弩手、轻骑兵；B 方：弓箭手、骑兵、枪骑兵、斥候。A 方开局先手。

输入行动编号；`help` 查看技能，`save` 保存，`quit` 保存并中止。默认保存到 `save.json`，可用 `--output 路径` 修改。人机双方都只通过合法行动执行规则。CLI 的 AI 均匀随机选择合法行动，适合规则验证，尚不具备可靠的占点或防守策略。

棋盘使用 `(q,r)` 六边形轴坐标。每格显示控制方和单位方、兵种缩写、层数，例如 `(-1,-2)A/ASw2`：A 控制的据点上有 A 的两层剑士。`*` 是中立据点，`.` 是普通格，`--` 是空格。终端建议宽度至少 126 列。

## 保存、恢复与回放

```bash
python3 -m warchest play --load save.json
python3 -m warchest replay examples/intro-win.json --view A --step
python3 -m warchest replay examples/intro-win.json --view B
python3 -m warchest replay examples/intro-win.json --view full
```

默认回放为 A 视角，`--step` 逐步暂停。每步重新执行规则并核对状态摘要和事件。`full` 显示完整调试状态。回放文件本身包含种子和全部行动，因此属于完整信息调试记录；玩家视角只过滤显示，文件不能直接发给正在对局的对手或交给 AI。

恢复对局重放已记录的行动，恢复游戏随机状态；CLI 随机 AI 的选择随机源按 `--ai-seed` 重新初始化。记录中的实际行动才是复现对局的依据。

`examples/intro-win.json` 是固定种子 7、73 次行动的规则演示：B 持续跳过，A 使用剑士获取四个新据点，触发胜利。用于展示完整胜利流程，不是棋力证明。

## 批量验证与测试

```bash
python3 -m warchest simulate --games 100 --max-actions 2000 --output report.json
python3 -m warchest simulate --games 2 --record-dir records --verbose
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

默认从种子 0 开始、AI 种子为 `10000 + 对局种子`。每步检查币数守恒、地图合法性和控制点状态。到达行动上限记为 `truncated`，不判和局；人工退出为 `aborted`，正式胜利为 `finished`。不引入重复局面和局或其他平台的额外规则。

扩展验收见 [扩展规则覆盖表](docs/expansion-rules.md) 与 [100 局混合扩展报告](docs/expansion-simulation-results.json)。基础版历史验收见 [联机版本验收](docs/web-validation.md)、[规则覆盖表](docs/rules.md) 和 [全兵种 100 局报告](docs/full-base-report.json)。最初的 8 兵种历史报告保留在 `docs/validation.md`。

## Python 接口

```python
import random
from warchest import new_game, observe, legal_actions, apply_action, serialize, deserialize
from warchest.ai import choose_action

state = new_game(seed=7)
agent_rng = random.Random(123)  # 与抽袋随机源独立
view = observe(state, state.current)
action = choose_action(view, legal_actions(state), agent_rng)
next_state, events = apply_action(state, action)
restored = deserialize(serialize(next_state))
assert restored == next_state
```

- `apply_action` 返回新状态及事件，不修改输入；非法行动抛出 `IllegalAction`，包括终局后的行动。
- `Action` 包含类型、支付币、完整路径、目标、招募兵种和剑士可选后续移动。动作对象稳定且可序列化；列表中的编号仅在当前局面有效。
- `observe` 返回独立的玩家视角及可见历史，不提供种子、随机状态、抽袋顺序和对手隐藏币种。无记忆随机基线可用 `include_history=False` 减少复制开销；后续策略默认应读取完整历史。
- `legal_actions` 只为当前行动方生成动作；AI 边界是 `choose_action(observation, actions, rng)`。完整 `State` 留在环境中。
- `Event.visible_to=None` 表示公开事件，`0/1` 表示仅对应玩家可见。显示或转发前使用 `visible_events` 过滤。
- 存档格式版本为 1，基础局规则版本为 `base-2`，扩展局为 `expansions-1`；不兼容版本显式拒绝。没有使用 pickle。
- `new_game(seed, armies=(己方四兵种, 对方四兵种), initiative=0)` 支持全部兵种；可传 `expansions=["base", "nobility", "siege", "nightfall", "shock"]` 启用扩展。八个兵种不能重复，原卡与替代卡不能共用。省略 `armies` 时仍采用官方入门阵容。
- `State.pending` 记录技能待结算步骤；`turn_owner` 保留原行动方，防御插入不会改变下一正常行动的归属。
- `Action.source` 指定步兵或受指挥单位的位置，`effect` 表示指挥战术的实际调遣类型。客户端必须使用引擎返回的合法行动。
- 旧版 `intro-1` 存档显式拒绝；示例回放已重新生成并校验为 `base-2`。

网页已提供基础启发式 AI，下一阶段可在相同接口上接入更强搜索和训练适配器。网页支持房主自选双方阵容、按启用扩展随机分兵及入门预设。仍没有轮流选秀阶段。

## 协作开发

克隆、分支开发、push / pull 和邀请合作者的步骤见 [协作说明](CONTRIBUTING.md)。本地房间数据库与认证信息不会提交到 Git。
