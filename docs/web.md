# 网页与双人联机

## 启动

```bash
.venv/bin/python -m pip install -e '.[web,test]'
.venv/bin/python -m warchest.web --host 0.0.0.0 --port 8080
```

网页、静态资源和 API 由同一服务提供，无需 Node.js 或前端构建。核心规则与网页依赖分离，CLI 继续可用。

- 本机：`http://localhost:8080`。
- 局域网：另一台设备访问服务器的局域网 IP 和 8080 端口；确保系统防火墙允许此端口。
- 公网：部署到有域名的主机，使用 Nginx/Caddy 等反向代理提供 HTTPS，转发到 `127.0.0.1:8080`，保留原始 Host。不需要 WebSocket 配置。
- 持久化：`--database /持久化目录/rooms.sqlite3`，保留 SQLite 及其 WAL 文件；备份宜用 SQLite 的 backup 接口。
- 重启后房间与座位仍保留。浏览器保存对应房间的座位凭证；清除浏览器站点数据会失去该座位访问权，没有账号找回功能。

示例 Nginx 代理段（放入已经配置 HTTPS 的 server 内）：

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 30s;
}
```

正式服务使用 Waitress，见 [Flask 的 Waitress 部署文档](https://flask.palletsprojects.com/en/stable/deploying/waitress/)。此项目没有自动创建云服务器或发布公网域名。

## 交互

对局布局按窗口高度分配棋盘空间，常见桌面、平板和竖屏手机可同时看到棋盘与手牌。宽屏桌面将双方供应与手牌放在棋盘左右，让棋盘占用完整高度；棋子图标、名称和层数加大。桌面侧栏单独滚动；窄屏通过棋盘上方的“房间”和“档案 / 记录”打开辅助面板，点击收起或按 Escape 返回。点击供应区兵种也会打开档案。非常矮的窗口保留必要滚动，避免棋盘被压到不可操作。

选择手牌币后弹出合法行动菜单。调遣包含普通移动、攻击与控制；选择调遣后，点击空格移动、敌军攻击、单位脚下的高亮据点控制。控制不再单列菜单。部署、战术使用引擎给出的完整合法行动：多格移动直接高亮最终可达位置，点击终点后自动选取合法路径；同终点有多条路径时优先使用较短路径。移动后攻击等战术再选择攻击目标。增强等只有一个结果时立即提交；调遣始终需要点击棋盘确认，其他多个结果则高亮棋盘。剑士攻击后可选择不移动。行军法令、步兵等有多个可执行单位时，先点击高亮棋子选定单位，再选择目的格；战术继续提示另一单位的调遣。

战斗牧师额外抽币后自动弹出该币菜单；狂战士可继续或结束；皇家卫队被攻击时切换到防御方弹窗，供应代损与单位受损可选。关闭弹窗不会跳过结算，仍有“继续技能结算”入口。

每位玩家的己方都显示在下方、红色，对手在上方、蓝色；这是视角配色，不会改变服务器的 A/B 身份或格子坐标。地图始终为 37 格、10 据点。

默认 `bp` 模式的每张选兵卡显示该兵种的总币数。从启用扩展的兵种池抽取 10 种不同兵种，原版与替代版本不同时出现。随机决定先手，双方入席后按以下顺序操作：

1. 先手禁用 1 种。
2. 后手禁用 1 种。
3. 先手选取 1 种。
4. 后手选取 2 种。
5. 先手选取 2 种。
6. 后手选取 2 种。
7. 先手选取 1 种。

每轮选足数量后点击确认，服务器一次提交整轮选择。双方各选四种后才生成对局和发手牌，BP 先手也是对局首轮先手。BP 进度自动保存，刷新、短暂断网及服务重启后可恢复；BP 阶段也可认输。再战重新抽候选池、随机先手并重新 BP。

`random` 模式直接随机分配双方各四种；`intro` 采用固定入门阵容、A 先手；`custom` 由房主配置双方阵容和首轮先手，自选再战保留配置。原有房间保持原模式。法令等扩展操作见 [扩展说明](expansions.md)。

## AI 陪练与特效

首页填写昵称、选择阵容后点击“与 AI 对战”，默认使用随机 AI，也可选择基础版的[作弊 MCTS AI](cheat-mcts.md)，它读取双方当前手牌、每步新增 5000 次模拟、rollout 深度 120，最多 16 个进程异步回传至同一棵搜索树，并复用后继子树，未来抽币仍随机，计算期间网页继续轮询。随机 AI 均匀选择合法行动，支持基础版及全部扩展。人类固定执 A；BP 与随机阵容均随机决定先手。AI 在 BP 阶段随机禁选。

旧 `basic`、`mcts` 请求和已有 AI 房间统一迁移为 `random`，对手名称显示“随机 AI”。决策在数据库写事务之外执行，提交前检查局号、版本和行动方，过期结果丢弃。

AI 由已认证的页面轮询触发，支持牧师额外币、卫队防御等技能选择。作弊 MCTS 在后台完成本次搜索，关闭网页后已启动的任务仍可提交一步，下一次搜索需等待轮询；服务器重启保留已提交局面，未完成搜索重新计算。AI 房间点击再战即可开始新局。

47 种兵种配有斩击、突刺、箭矢、弩箭、冲锋、重击或牧师光效，受击显示闪烁、减层与击溃，卫队供应代损显示抵挡。特效来自服务器确认的公开战斗结果，双方同步播放，不影响规则或操作；刷新不补播旧动画。系统开启减少动态效果时采用简化提示。

对手每次行动会在棋盘中央显示大字提示及公开兵种信息，停留约 2.2 秒后淡出；连续操作按顺序显示，不拦截棋盘点击。刷新、重新进入房间及再战不会重播旧操作。招募只显示招募兵种，抢先与跳过不显示暗弃支付的币种。

## 权威与同步

- 房间号仅用于邀请，不授予读取手牌或落子权限。每个座位持有随机 Bearer 凭证，数据库仅保存其哈希。
- 服务器每次动作都重新枚举合法动作。客户端提交 `action_id` 和所见 `revision`，不能上传棋盘或指定任意隐藏状态。
- SQLite 写事务串行处理加入、落子、认输与再战。重复或过期落子返回 409，不会多支付币。
- 对局快照过滤对手手牌、暗弃币种、抽袋顺序、种子、随机数状态。非当前行动方收到空动作列表。
- 浏览器每 1.2 秒读取自己的快照，失败显示重连状态，恢复后重建局面；落子响应立即更新本人界面。
- 最近事件用于展示日志，数据库保留完整引擎历史。前端从不接收完整调试存档。
- 再战投票按局数标识，双方同时同意也能成功；旧局投票不会作用于新局。

## API

| 请求 | 用途 |
|---|---|
| `GET /api/bootstrap` | 公开的 47 种兵种资料、扩展列表、法令、地图与演示局面 |
| `POST /api/rooms` `{name, mode, opponent?, ai_level?, expansions?, armies?, initiative?}` | opponent 为 `human`（默认）或 `ai`，ai_level 为 `random`（默认）或 `cheat_mcts`（作弊 MCTS，仅基础版），旧 `basic`、`mcts` 兼容映射到 `random`；创建房间，mode 为 `bp`（默认）、`random`、`intro` 或 `custom`；custom 需提供两组各四个 ID 的 armies，expansions 为扩展 ID 列表，initiative 为 0 或 1，返回 `{code, token, player}` |
| `POST /api/rooms/:code/join` `{name}` | 加入空座位 |
| `GET /api/rooms/:code` | 获取已认证玩家视角及合法动作 |
| `POST /api/rooms/:code/draft` `{revision, units}` | 当前 BP 方一次提交本轮完整兵种 ID 列表；服务器校验轮次、数量、候选及版本，完成最后一轮后自动开局 |
| `POST /api/rooms/:code/actions` `{revision, action_id}` | 执行动作或技能追加选择 |
| `POST /api/rooms/:code/resign` `{revision}` | 认输 |
| `POST /api/rooms/:code/rematch` `{revision, game}` | 同意再战 |

已入席 API 使用 `Authorization: Bearer <token>`。快照含 `room`、`revision`、`game`、`mode`、`status`、`seats`、`winner`、`view` 和 `actions`，以及最近 40 次公开行动的 `activity`（含提交版本号和公开行动字段）。状态为 `waiting / drafting / playing / finished`。BP 房间还包含 `draft`：候选池 `pool`、剩余候选 `available`、先手 `first`、步骤 `step`（0–7）、当前操作方 `current`、操作 `kind`、数量 `count`、双方 `bans` 与 `picks`。BP 完成前 `view=null` 且 `actions=[]`；完成后 `draft` 保留禁选结果。每个动作保留规则引擎字段，附加仅对当前 revision 有效的编号。

## 测试

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip install -e '.[browser]'
.venv/bin/python -m playwright install chromium
WC_BROWSER=1 .venv/bin/python -m pytest tests/test_browser.py -q
```

浏览器测试使用独立临时数据库和服务端口。覆盖两独立会话完整 BP（双方先手、双选确认、手机界面、刷新及开局落子）、真实对战、刷新、手机布局、兵种图鉴、战斗牧师单结果增强、移动目标及卫队防御连锁、调遣中的脚下控制、攻击受击动画与 AI 开局自动行动。普通 pytest 默认跳过浏览器测试。

新增网站扩展：Champions、Mastery、High Seas。选扩展、BP、自选阵容、AI 与再战沿用原入口；工具栏 `?` 内可展开各扩展特殊机制。公海棋盘包含 49 格，同格船／乘员用明确兵种名称区分行动和目标；英雄局据点进度显示动态获胜目标。详见 [规则与本地边界](community-expansions.md)。


## AI 自我对弈演示

大厅的「观看 AI 自我对弈」链接打开 `/static/demo.html`。演示读取静态逐步记录，不建立房间、不调用行动接口、不触发新的 AI 搜索；返回大厅后原有浏览器房间会话不受影响。展示双方手牌、供应、袋中数量、控制点和逐步行动，支持播放/暂停、前后步进、倍速、进度拖动及从头播放。移动、部署和战斗使用动画；减少动态效果设置下禁用移动过渡并简化战斗效果。

记录生成命令：`.venv/bin/python scripts/generate_mcts_demo.py`。双方均使用 5000 次新增模拟、rollout 深度 120、c_uct=1.4、最多 16 个工作进程的共享树异步 MCTS，各自保留后继树；唯一合法动作直接执行。真实对局按规则引擎的随机流抽币，搜索不读取真实未来袋序。每一步原子保存，重复执行命令可从存档继续（重建搜索树）。

完整权威记录：`docs/mcts-selfplay-record.json`；前端帧：`warchest/static/demos/mcts-selfplay.json`。生成时和回归测试使用 `replay_states` 逐步核对合法动作、局面摘要及事件。演示动画的播放速度与实际搜索耗时分开显示。
