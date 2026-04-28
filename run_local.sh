#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

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

python Code/dual_api_server.py
