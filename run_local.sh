#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "HuXin backend for macOS"
echo "This starts the local API at http://127.0.0.1:8000"
echo "After it finishes loading, open: https://timemachinedmc.github.io/HuXin/"
echo

PORT="${HUXIN_PORT:-8000}"
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
  echo "HuXin backend is already running at http://127.0.0.1:${PORT}"
  echo "Open: https://timemachinedmc.github.io/HuXin/"
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

python Code/dual_api_server.py
