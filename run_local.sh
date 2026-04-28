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

python Code/dual_api_server.py
