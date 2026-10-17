#!/usr/bin/env bash
set -euo pipefail

# Usage: ./run_turbotrial.sh <HOST> <PORT> [USER] [PASS] [--rotate-session]
HOST="${1:-}"
PORT="${2:-}"
USER="${3:-}"
PASS="${4:-}"
EXTRA="${5:-}"

if [ -z "$HOST" ] || [ -z "$PORT" ]; then
    echo "Usage: $0 <HOST> <PORT> [USER] [PASS] [--rotate-session]"
    exit 1
fi

PYTHON="/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/.venv/bin/python"
SCRIPT="/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Clawler/crawl_ask39_turbotrial.py"

echo "=========================================================="
echo "🚀 KHỞI CHẠY 1-HOUR TURBO CRAWLER (50 WORKERS / 10 Mbps)"
echo "Host: $HOST:$PORT | User: $USER"
echo "=========================================================="

exec $PYTHON -u $SCRIPT \
    --host "$HOST" \
    --port "$PORT" \
    --user "$USER" \
    --password "$PASS" \
    --concurrency 50 \
    --timeout 10 \
    --duration 58 \
    $EXTRA
