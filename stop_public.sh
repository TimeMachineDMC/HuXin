#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.huxin.cloudflared.plist" >/dev/null 2>&1 || true

for name in cloudflared backend; do
  pid_file=".runtime/${name}.pid"
  if [ -f "$pid_file" ]; then
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      echo "Stopped ${name} (${pid})."
    fi
    rm -f "$pid_file"
  fi
done
