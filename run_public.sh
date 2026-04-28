#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PORT="${HUXIN_PORT:-8000}"
RUNTIME_DIR=".runtime"
BACKEND_HEALTH_URL="http://127.0.0.1:${PORT}/api/health"
mkdir -p "$RUNTIME_DIR"

wait_for_health() {
  local url="$1"
  local label="$2"
  local attempts="${3:-90}"

  for _ in $(seq 1 "$attempts"); do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "Timed out waiting for ${label}: ${url}" >&2
  return 1
}

if ! curl -fsS --max-time 5 "$BACKEND_HEALTH_URL" >/dev/null 2>&1; then
  echo "Starting HuXin backend on port ${PORT}..."
  nohup ./run_local.sh > "${RUNTIME_DIR}/backend.log" 2>&1 &
  echo $! > "${RUNTIME_DIR}/backend.pid"
  wait_for_health "$BACKEND_HEALTH_URL" "local backend" 180
else
  echo "HuXin backend is already running on port ${PORT}."
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installing cloudflared with Homebrew..."
    brew install cloudflared
  else
    echo "cloudflared is required. Install it first, then rerun this script." >&2
    exit 1
  fi
fi

if [ -f "${RUNTIME_DIR}/cloudflared.pid" ]; then
  old_pid="$(cat "${RUNTIME_DIR}/cloudflared.pid" 2>/dev/null || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" >/dev/null 2>&1; then
    old_url="$(grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' "${RUNTIME_DIR}/cloudflared.log" 2>/dev/null | tail -1 || true)"
    if [ -n "$old_url" ] && curl -fsS --max-time 10 "${old_url}/api/health" >/dev/null 2>&1; then
      echo "$old_url" > "${RUNTIME_DIR}/public_url.txt"
      echo "Cloudflare tunnel is already running."
      echo
      echo "Backend URL: ${old_url}"
      echo "GitHub Pages: https://timemachinedmc.github.io/HuXin/?api=${old_url}"
      exit 0
    fi
    kill "$old_pid" >/dev/null 2>&1 || true
  fi
fi

: > "${RUNTIME_DIR}/cloudflared.log"
echo "Starting Cloudflare quick tunnel..."
nohup cloudflared tunnel --url "http://localhost:${PORT}" > "${RUNTIME_DIR}/cloudflared.log" 2>&1 &
echo $! > "${RUNTIME_DIR}/cloudflared.pid"

public_url=""
for _ in $(seq 1 60); do
  public_url="$(grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' "${RUNTIME_DIR}/cloudflared.log" | tail -1 || true)"
  if [ -n "$public_url" ]; then
    break
  fi
  sleep 1
done

if [ -z "$public_url" ]; then
  echo "Could not read the Cloudflare public URL. Recent tunnel log:" >&2
  tail -40 "${RUNTIME_DIR}/cloudflared.log" >&2
  exit 1
fi

wait_for_health "${public_url}/api/health" "public tunnel" 90
echo "$public_url" > "${RUNTIME_DIR}/public_url.txt"

echo
echo "Public HuXin backend is ready:"
echo "${public_url}"
echo
echo "Open GitHub Pages with this backend:"
echo "https://timemachinedmc.github.io/HuXin/?api=${public_url}"
echo
echo "For Vercel, append the same api parameter to your Vercel URL."
echo "Tunnel log: ${RUNTIME_DIR}/cloudflared.log"
