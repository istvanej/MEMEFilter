#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <MINT_ADDR> [BASE_TOPN=300] [OUT_TOPN=100]"
  exit 1
fi
MINT="$1"; BASE_TOPN="${2:-300}"; OUT_TOPN="${3:-100}"
./scripts/run_screen.sh "$MINT" "$BASE_TOPN" "$OUT_TOPN"
# 可选：等待一会儿让扫描进度推进，再跑过滤/导出
sleep 30
./scripts/run_filters.sh || true
./scripts/export_lists.sh || true
