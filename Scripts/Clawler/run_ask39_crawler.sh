#!/usr/bin/env bash
cd /home/tran-nhat-truong/TranNhatTruong/other/AIGuru
exec /home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/.venv/bin/python -u \
  /home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Clawler/crawl_ask39_local.py \
  --concurrency 3 \
  --batch-size 25 \
  --timeout 12000 \
  >> /home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/ask39_crawler.log 2>&1
