#!/usr/bin/env bash
set -euo pipefail

# 用法：
# ./scripts/run_entry.sh <MINT_ADDR> [TOPN] [MODE]
# MODE: holders | early （默认 early）

MINT="${1:-}"
TOPN="${2:-300}"
MODE="${3:-early}"

if [[ -z "$MINT" ]]; then
  echo "Usage: $0 <MINT_ADDR> [TOPN] [MODE]"
  exit 1
fi

# 1) 导入 token
python -m app.cli import-token --mint "$MINT"

# 2) 扫描候选地址
python -m app.cli scan-mint --mint "$MINT" --topn "$TOPN" --mode "$MODE"

# 3) 软过滤（初筛）
python -m app.cli soft-filter --limit 800
