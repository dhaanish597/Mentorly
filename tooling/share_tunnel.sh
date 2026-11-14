#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-5180}"
CLOUDFLARED="/opt/homebrew/bin/cloudflared"

if [[ ! -x "$CLOUDFLARED" ]]; then
  if command -v cloudflared >/dev/null 2>&1; then
    CLOUDFLARED="$(command -v cloudflared)"
  else
    echo "cloudflared not found. Install it with: brew install cloudflared" >&2
    exit 1
  fi
fi

LOG_FILE="/tmp/cloudflared.log"

if pgrep -f "cloudflared tunnel --url" >/dev/null 2>&1; then
  echo "Cloudflare Tunnel is already running."
  if [[ -f "$LOG_FILE" ]]; then
    URL=$(grep -oE "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" "$LOG_FILE" | tail -n 1 || true)
    if [[ -n "$URL" ]]; then
      echo "Public URL: $URL"
      exit 0
    fi
  fi
fi

echo "Starting Cloudflare quick tunnel to http://127.0.0.1:${PORT}..."
"$CLOUDFLARED" tunnel --url "http://127.0.0.1:${PORT}" > "$LOG_FILE" 2>&1 &

for _ in {1..15}; do
  sleep 1
  if [[ -f "$LOG_FILE" ]]; then
    URL=$(grep -oE "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" "$LOG_FILE" | tail -n 1 || true)
    if [[ -n "$URL" ]]; then
      echo "=== Tunnel Created Successfully ==="
      echo "Shareable Public URL: $URL"
      exit 0
    fi
  fi
done

echo "Tunnel started. Check log for URL: $LOG_FILE"
