#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

if [[ ! -x .tools/cloudflared || ! -x .venv/bin/python ]]; then
    echo '缺少 .tools/cloudflared 或 .venv/bin/python，请先安装。' >&2
    exit 1
fi

# Prevent a second launcher from reusing this port or publishing another service.
exec 9>.tools/online.lock
flock -n 9 || { echo '联机服务已经运行。' >&2; exit 1; }
.venv/bin/python - <<'PY'
import socket
with socket.socket() as sock:
    try:
        sock.bind(('127.0.0.1', 8080))
    except OSError:
        raise SystemExit('8080 端口已占用，请先停止占用该端口的服务。')
PY

web_pid=''
tunnel_pid=''
cleanup() {
    trap - EXIT INT TERM
    [[ -z "$tunnel_pid" ]] || kill "$tunnel_pid" 2>/dev/null || true
    [[ -z "$web_pid" ]] || kill "$web_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

.venv/bin/python -m warchest.web --host 127.0.0.1 --port 8080 &
web_pid=$!
.venv/bin/python - <<'PY'
import time
import urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for _ in range(40):
    try:
        with opener.open('http://127.0.0.1:8080/api/bootstrap', timeout=1) as response:
            if response.status == 200:
                break
    except OSError:
        pass
    time.sleep(0.25)
else:
    raise SystemExit('游戏服务启动失败。')
PY

echo '正在创建临时公网地址；双方请使用下方的 https://*.trycloudflare.com 链接。'
echo '保持本终端运行，按 Ctrl+C 同时停止游戏和隧道。'
.tools/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8080 &
tunnel_pid=$!
wait -n "$web_pid" "$tunnel_pid"
