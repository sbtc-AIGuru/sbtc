#!/usr/bin/env bash
# Runner 1-Click cho SparkProxy 24-Hour Free Trial
set -e

REPO_DIR="/home/tran-nhat-truong/TranNhatTruong/other/AIGuru"
PYTHON="$REPO_DIR/sbtc/.venv/bin/python"
SCRIPT="$REPO_DIR/sbtc/Scripts/Clawler/crawl_ask39_sparkproxy.py"

# Cấu hình mặc định của SparkProxy
HOST="${1:-gateway.sparkproxy.io}"
PORT="${2:-11000}"
USER="$3"
PASS="$4"

if [ -z "$USER" ] || [ -z "$PASS" ]; then
    echo "Cách dùng:"
    echo "  $0 <HOST> <PORT> <USERNAME> <PASSWORD>"
    echo "Ví dụ:"
    echo "  $0 gateway.sparkproxy.io 11000 myuser mypass"
    exit 1
fi

echo "======================================================="
echo "⚡ KHỞI CHẠY SPARKPROXY 24-HOUR CRAWLER (220 WORKERS)"
echo "Host: $HOST:$PORT | User: $USER"
echo "======================================================="

exec $PYTHON -u "$SCRIPT" \
  --host "$HOST" \
  --port "$PORT" \
  --user "$USER" \
  --password "$PASS" \
  --concurrency 220 \
  --timeout 10 \
  --duration 1400
