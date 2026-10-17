#!/usr/bin/env bash
# 🚀 1-Click Runner for ask.39.net 4G Mobile Crawler
set -e

cd /home/tran-nhat-truong/TranNhatTruong/other/AIGuru
PYTHON_BIN="/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/.venv/bin/python"

echo "=========================================================="
echo "   🏥 ask.39.net 4G HIGH-THROUGHPUT RESILIENT CRAWLER     "
echo "=========================================================="
echo "🌐 Đang kiểm tra IP công khai..."
CURRENT_IP=$(curl -s --max-time 5 https://api.ipify.org || echo "Chưa lấy được IP")
echo "👉 Public IP: $CURRENT_IP"
echo "⚙️ Khởi động crawler (Concurrency: 4, Batch: 25)..."
echo "=========================================================="

exec $PYTHON_BIN -u sbtc/Scripts/Clawler/crawl_ask39_4g.py --concurrency 4 --batch-size 25 --timeout 12000
