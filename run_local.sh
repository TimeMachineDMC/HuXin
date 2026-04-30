#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "HuXin backend for macOS"
echo "This starts the local API at http://127.0.0.1:8000"
echo "After it finishes loading, open: https://timemachinedmc.github.io/HuXin/"
echo

mkdir -p .runtime
PORT="${HUXIN_PORT:-8000}"
LOG_FILE=".runtime/backend-live.log"

if [ "${1:-}" = "stop" ]; then
  launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.huxin.backend.plist" >/dev/null 2>&1 || true
  pids="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill >/dev/null 2>&1 || true
    echo "Stopped HuXin backend on port ${PORT}."
  else
    echo "No HuXin backend is listening on port ${PORT}."
  fi
  exit 0
fi

if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
  echo "HuXin backend is already running at http://127.0.0.1:${PORT}"
  echo "Open: https://timemachinedmc.github.io/HuXin/"
  if [ ! -t 1 ]; then
    exit 0
  fi
  echo
  echo "Showing live backend logs. Press Ctrl-C to stop watching logs; backend keeps running."
  for candidate in "$LOG_FILE" ".runtime/backend-launch.log" ".runtime/backend.log"; do
    if [ -f "$candidate" ]; then
      tail -n 80 -f "$candidate"
      exit 0
    fi
  done
  echo "No log file found yet. Trigger one request in the browser, then rerun ./run_local.sh."
  exit 0
fi

if [ ! -f "Code/.env" ] && [ ! -f ".env" ]; then
  echo "Missing DeepSeek config. Run this once first:" >&2
  echo "  cp .env.example Code/.env" >&2
  echo "Then edit Code/.env and fill DEEPSEEK_API_KEY." >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip

if [ ! -f ".venv/.huxin_requirements_installed" ] || [ "requirements.txt" -nt ".venv/.huxin_requirements_installed" ]; then
  python -m pip install -r requirements.txt
  touch .venv/.huxin_requirements_installed
fi

if [ -d "Model/chroma_db" ] && [ ! -d ".runtime/chroma_db" ]; then
  mkdir -p .runtime
  cp -R Model/chroma_db .runtime/chroma_db
fi

export CHROMA_DB_PATH="${CHROMA_DB_PATH:-.runtime/chroma_db}"
export HUXIN_HOST="${HUXIN_HOST:-127.0.0.1}"
export HUXIN_PORT="${PORT}"
export PYTHONUNBUFFERED=1

python -u Code/dual_api_server.py 2>&1 | tee -a "$LOG_FILE"
