#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST="${LULU_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${LULU_BACKEND_PORT:-8000}"
FRONTEND_PORT="${LULU_FRONTEND_PORT:-5173}"
CONDA_ENV="${LULU_CONDA_ENV:-lulu-agent}"

cd "$ROOT_DIR"

if [ -n "${LULU_PYTHON:-}" ]; then
  BACKEND_CMD=("$LULU_PYTHON")
elif command -v python >/dev/null 2>&1; then
  BACKEND_CMD=(python)
elif command -v conda >/dev/null 2>&1; then
  BACKEND_CMD=(conda run --no-capture-output -n "$CONDA_ENV" python)
elif [ -x "$HOME/miniconda3/condabin/conda" ]; then
  BACKEND_CMD=("$HOME/miniconda3/condabin/conda" run --no-capture-output -n "$CONDA_ENV" python)
elif command -v python3 >/dev/null 2>&1; then
  BACKEND_CMD=(python3)
else
  echo "python is required to start lulu-agent." >&2
  exit 1
fi

if command -v npm >/dev/null 2>&1; then
  NPM_CMD=(npm)
elif [ -x "$HOME/.nvm/versions/node/v20.19.0/bin/npm" ]; then
  NPM_CMD=("$HOME/.nvm/versions/node/v20.19.0/bin/npm")
else
  echo "npm is required to start the lulu-agent GUI." >&2
  exit 1
fi

if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
  echo "frontend/node_modules is missing. Run: cd frontend && npm install" >&2
  exit 1
fi

cleanup() {
  if [ -n "${BACKEND_PID:-}" ]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${FRONTEND_PID:-}" ]; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
}

open_frontend_when_ready() {
  local url="http://127.0.0.1:${FRONTEND_PORT}"
  if ! command -v open >/dev/null 2>&1; then
    return
  fi
  for _ in {1..40}; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      open "$url" >/dev/null 2>&1 || true
      return
    fi
    sleep 0.25
  done
}

trap cleanup EXIT INT TERM

echo "Starting lulu-agent backend: http://${BACKEND_HOST}:${BACKEND_PORT}"
"${BACKEND_CMD[@]}" -m uvicorn lulu_agent.server.app:app \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" &
BACKEND_PID=$!

echo "Starting lulu-agent frontend: http://127.0.0.1:${FRONTEND_PORT}"
"${NPM_CMD[@]}" run dev --prefix frontend -- --port "$FRONTEND_PORT" --strictPort &
FRONTEND_PID=$!

echo "lulu-agent GUI is starting."
echo "Open: http://127.0.0.1:${FRONTEND_PORT}"
echo "Press Ctrl+C to stop both processes."

open_frontend_when_ready &
OPEN_PID=$!

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
