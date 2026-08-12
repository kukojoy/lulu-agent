#!/usr/bin/env bash
set -euo pipefail

# 获取工作目录
WORKSPACE_DIR="$(pwd)"

# 获取项目目录 (启动脚本的根目录)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 端口配置
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
FRONTEND_PORT="5173"

# 检查 python 命令
if command -v python >/dev/null 2>&1; then
  BACKEND_CMD=(python)
else
  echo "python is required to start lulu-agent." >&2
  exit 1
fi

# 检查 npm 命令
if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to start the lulu-agent GUI." >&2
  exit 1
fi

# 检查前端依赖
if [ ! -d "$ROOT_DIR/gui/node_modules" ]; then
  echo "gui/node_modules is missing. Run: cd gui && npm install" >&2
  exit 1
fi

# 查找可用端口
find_available_port() {
  local first_port="$1"
  local port="$first_port"
  local last_port=$((first_port + 100))

  while [ "$port" -le "$last_port" ]; do
    if "${BACKEND_CMD[@]}" -c '
import socket
import sys

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", int(sys.argv[1])))
    except OSError:
        raise SystemExit(1)
' "$port" >/dev/null 2>&1; then
      printf '%s\n' "$port"
      return 0
    fi
    port=$((port + 1))
  done

  return 1
}

# 杀死进程树
kill_tree() {
  local pid="${1:-}"
  local child

  if [ -z "$pid" ] || ! kill -0 "$pid" >/dev/null 2>&1; then
    return
  fi

  if command -v pgrep >/dev/null 2>&1; then
    while IFS= read -r child; do
      kill_tree "$child"
    done < <(pgrep -P "$pid" 2>/dev/null || true)
  fi

  kill "$pid" >/dev/null 2>&1 || true
}

# 清理进程
cleanup() {
  kill_tree "${FRONTEND_PID:-}"
  if [ -n "${FRONTEND_PID:-}" ]; then
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi

  kill_tree "${BACKEND_PID:-}"
  if [ -n "${BACKEND_PID:-}" ]; then
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}

# 等待 URL 可用
wait_for_url() {
  local url="$1"
  for _ in {1..40}; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

# 打开 GUI
open_gui() {
  local url="$1"
  if ! command -v open >/dev/null 2>&1; then
    return
  fi
  open "$url" >/dev/null 2>&1 || true
}

if ! BACKEND_PORT="$(find_available_port "$BACKEND_PORT")"; then
  echo "No available backend port found." >&2
  exit 1
fi

if ! FRONTEND_PORT="$(find_available_port "$FRONTEND_PORT")"; then
  echo "No available frontend port found." >&2
  exit 1
fi

# 配置退出时清理
trap cleanup EXIT
trap 'trap - EXIT; cleanup; exit 130' INT TERM

# 开启后端
echo "Starting lulu-agent backend: http://${BACKEND_HOST}:${BACKEND_PORT}"
cd "$WORKSPACE_DIR"  # 切换到工作目录
PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
"${BACKEND_CMD[@]}" -m uvicorn lulu_agent.server.app:app \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" &
BACKEND_PID=$!

# 等待后端可用
if ! wait_for_url "http://${BACKEND_HOST}:${BACKEND_PORT}/health"; then
  echo "Backend did not become ready in time." >&2
  exit 1
fi

# 开启前端
echo "Starting lulu-agent GUI: http://127.0.0.1:${FRONTEND_PORT}"
VITE_API_BASE="http://${BACKEND_HOST}:${BACKEND_PORT}" \
VITE_WS_BASE="ws://${BACKEND_HOST}:${BACKEND_PORT}" \
npm run dev --prefix "$ROOT_DIR/gui" -- --port "$FRONTEND_PORT" --strictPort &
FRONTEND_PID=$!

# 等待前端可用
if ! wait_for_url "http://127.0.0.1:${FRONTEND_PORT}"; then
  echo "GUI did not become ready in time." >&2
  exit 1
fi

# 启动 GUI
echo "lulu-agent GUI is starting."
echo "Open: http://127.0.0.1:${FRONTEND_PORT}"
echo "Press Ctrl+C to stop both processes."

open_gui "http://127.0.0.1:${FRONTEND_PORT}"

# 轮询检查前后端进程状态
while true; do
  if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    wait "$BACKEND_PID" || true
    exit 1
  fi
  if ! kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    wait "$FRONTEND_PID" || true
    exit 1
  fi
  sleep 1
done
