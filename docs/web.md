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

选择手牌币后弹出合法行动菜单。调遣包含普通移动、攻击与控制；选择调遣后，点击空格移动、敌军攻击、单位脚下的高亮据点控制。控制不再单列菜单。部署、战术按引擎给出的完整行动拆成可点击的路径与目标。增强等只有一个结果时立即提交；调遣始终需要点击棋盘确认，其他多个结果则高亮棋盘。剑士攻击后可选择不移动。步兵普通调遣先选目的格，必要时再选出发单位；战术继续提示另一单位的调遣。

战斗牧师额外抽币后自动弹出该币菜单；狂战士可继续或结束；皇家卫队被攻击时切换到防御方弹窗，供应代损与单位受损可选。关闭弹窗不会跳过结算，仍有“继续技能结算”入口。

每位玩家的己方都显示在下方、红色，对手在上方、蓝色；这是视角配色，不会改变服务器的 A/B 身份或格子坐标。地图始终为 37 格、10 据点。

基础版房间从 16 兵种抽取互不重复的八种，随机首手；入门房间采用原有固定阵容、A 先手。再战保持座位，重新生成同模式的局面。新增 `custom` 模式：房主勾选扩展并自由配置双方阵容和首轮先手；自选再战保留配置。法令等扩展操作见 [扩展说明](expansions.md)。

## AI 陪练与特效

首页填写昵称、选择阵容后点击“与 AI 对战”，选择基础 AI 或随机 AI 即可开局，无需邀请。基础 AI 使用占点、推进、攻击和防守评分；随机 AI 均匀选择合法行动。它们都只接收玩家观察和合法动作，不读取对手手牌或抽袋顺序。基础 AI 是启发式陪练，尚未经过竞技训练。人类固定执 A；基础版随机阵容仍随机决定先手。

AI 每次经已认证的页面轮询推进一步，支持牧师额外币、卫队防御等技能选择；关闭网页后暂停，重新打开继续，服务器重启保留局面。AI 房间点击再战即可开始新局。

35 种兵种配有斩击、突刺、箭矢、弩箭、冲锋、重击或牧师光效，受击显示闪烁、减层与击溃，卫队供应代损显示抵挡。特效来自服务器确认的公开战斗结果，双方同步播放，不影响规则或操作；刷新不补播旧动画。系统开启减少动态效果时采用简化提示。

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
| `GET /api/bootstrap` | 公开的 35 种兵种资料、扩展列表、法令、地图与演示局面 |
| `POST /api/rooms` `{name, mode, opponent?, ai_level?, expansions?, armies?, initiative?}` | opponent 为 `human`（默认）或 `ai`，ai_level 为 `basic`（默认）或 `random`；创建房间，mode 为 `random`、`intro` 或 `custom`；custom 需提供两组各四个 ID 的 armies，expansions 为扩展 ID 列表，initiative 为 0 或 1，返回 `{code, token, player}` |
| `POST /api/rooms/:code/join` `{name}` | 加入空座位 |
| `GET /api/rooms/:code` | 获取已认证玩家视角及合法动作 |
| `POST /api/rooms/:code/actions` `{revision, action_id}` | 执行动作或技能追加选择 |
| `POST /api/rooms/:code/resign` `{revision}` | 认输 |
| `POST /api/rooms/:code/rematch` `{revision, game}` | 同意再战 |

已入席 API 使用 `Authorization: Bearer <token>`。快照含 `room`、`revision`、`game`、`mode`、`status`、`seats`、`winner`、`view` 和 `actions`。状态为 `waiting / playing / finished`。每个动作保留规则引擎字段，附加仅对当前 revision 有效的编号。

## 测试

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip install -e '.[browser]'
.venv/bin/python -m playwright install chromium
WC_BROWSER=1 .venv/bin/python -m pytest tests/test_browser.py -q
```

浏览器测试使用独立临时数据库和服务端口。覆盖两独立会话真实对战、刷新、手机布局、兵种图鉴、战斗牧师单结果增强、移动目标及卫队防御连锁、调遣中的脚下控制、攻击受击动画与 AI 开局自动行动。普通 pytest 默认跳过浏览器测试。
