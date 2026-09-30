# 本机临时公网联机

本机已将 Cloudflare 官方 Linux amd64 程序安装到 `.tools/cloudflared`。
无需账号或域名，不需要修改路由器端口转发。

在项目根目录运行：

```bash
bash scripts/start-online.sh
```

脚本同时启动本机游戏（127.0.0.1:8080）及 Cloudflare Quick Tunnel。
终端显示 `https://随机名称.trycloudflare.com` 后，双方都打开这个公网地址，
再创建房间并分享邀请链接。不要从 localhost 页面复制邀请链接给异地好友。
按 Ctrl+C 会同时停止脚本启动的游戏和隧道；电脑和 WSL 必须保持运行。
如果提示服务已运行或 8080 被占用，请先停止原来的服务。

本次配置时已在后台启动，日志为 `.tools/online.log`，启动进程号记录在
`.tools/online.pid`。停止本次后台运行：

```bash
kill "$(cat .tools/online.pid)"
```

该 PID 文件仅用于本次后台会话；系统重启后不要用旧 PID 文件停止进程。
停止后可以用上面的启动脚本重新运行。不配置开机自启。

房间保存在 `data/rooms.sqlite3`。隧道重启通常生成新域名，浏览器保存在旧域名下的
座位凭证不会自动迁移到新域名，建议先结束对局再重启隧道。

Quick Tunnel 用于临时测试，没有可用性保证。
官方说明：https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/
