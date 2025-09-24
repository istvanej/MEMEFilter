#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <MINT_ADDR> [BASE_TOPN=300] [OUT_TOPN=100]"
  exit 1
fi

MINT="$1"
BASE_TOPN="${2:-300}"
OUT_TOPN="${3:-100}"
SESSION="meme_follow_$(date +%H%M%S)"
LOGDIR="logs"
mkdir -p "$LOGDIR"

HLOG="${LOGDIR}/holders_${MINT:0:6}_$(date +%Y%m%d_%H%M%S).log"
ELOG="${LOGDIR}/early_${MINT:0:6}_$(date +%Y%m%d_%H%M%S).log"

# 创建 screen 会话（后台启动）
screen -dmS "$SESSION"

# 窗口 0：holders 扫描（当前持有人）
screen -S "$SESSION" -X screen bash -lc "echo '[holders] mint=$MINT' | ts; stdbuf -oL -eL python -m app.logscan holders --mint '$MINT' --topn $BASE_TOPN 2>&1 | ts | tee '$HLOG'"

# 窗口 1：early 扫描（早期净买入者，带回放）
screen -S "$SESSION" -X screen bash -lc "echo '[early] mint=$MINT' | ts; stdbuf -oL -eL python -m app.logscan early --mint '$MINT' --base_topn $BASE_TOPN --out_topn $OUT_TOPN --tx_limit 300 --sleep_ms 50 2>&1 | ts | tee '$ELOG'"

echo "Started screen session: $SESSION"
echo "Attach:   screen -r $SESSION    (Ctrl-A + n/p 切换窗口)"
echo "Logs:"
echo "  holders: $HLOG"
echo "  early:   $ELOG"
