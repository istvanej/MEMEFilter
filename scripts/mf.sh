# scripts/mf.sh
#!/usr/bin/env bash
set -euo pipefail

# === Config ===
SESSION_PREFIX="meme_follow"
LOGDIR="logs"
OUTDIR="data/exports"
DB="data/db.sqlite"

# Check tool availability
have() { command -v "$1" >/dev/null 2>&1; }

ts_or_cat() {
  if have ts; then echo "ts"; else echo "cat"; fi
}

ensure_dirs() {
  mkdir -p "$LOGDIR" "$OUTDIR" "scripts"
}

usage() {
  cat <<EOF
Usage:
  $0 start <MINT_ADDR> [BASE_TOPN=300] [OUT_TOPN=100]
  $0 stop
  $0 export

Notes:
  - 'start' 仅启动后台扫描与日志；你可随时 screen 附着看进度。
  - 'export' 会先跑过滤(soft+hard)，再导出 WHITE/WATCH/BLACK 三个 txt 以及总 CSV。
  - 查看 screen 会话: screen -ls
    进入会话:      screen -r <SESSION_NAME>   (Ctrl-A+n/p 切窗口，Ctrl-A+d 脱离)
EOF
}

start_cmd() {
  if [[ $# -lt 1 ]]; then usage; exit 1; fi
  local MINT="$1"; local BASE_TOPN="${2:-300}"; local OUT_TOPN="${3:-100}"
  ensure_dirs
  local TS=$(date +'%Y%m%d_%H%M%S')
  local SESSION="${SESSION_PREFIX}_${TS}"
  local HLOG="${LOGDIR}/holders_${MINT:0:6}_${TS}.log"
  local ELOG="${LOGDIR}/early_${MINT:0:6}_${TS}.log"
  local TSF="$(ts_or_cat)"

  # 先确保导入一遍（幂等）
  python -m app.cli import-token --mint "$MINT" || true

  # 启动 screen 会话
  screen -dmS "$SESSION"

  # 窗口0：holders
  screen -S "$SESSION" -X screen bash -lc "echo '[holders] mint=$MINT base_topn=$BASE_TOPN' | $TSF; stdbuf -oL -eL python -m app.logscan holders --mint '$MINT' --topn $BASE_TOPN 2>&1 | $TSF | tee '$HLOG'"

  # 窗口1：early
  screen -S "$SESSION" -X screen bash -lc "echo '[early] mint=$MINT base_topn=$BASE_TOPN out_topn=$OUT_TOPN' | $TSF; stdbuf -oL -eL python -m app.logscan early --mint '$MINT' --base_topn $BASE_TOPN --out_topn $OUT_TOPN --tx_limit 300 --sleep_ms 50 2>&1 | $TSF | tee '$ELOG'"

  echo "Started screen session: $SESSION"
  echo "Attach:  screen -r $SESSION   (Ctrl-A + n/p 切窗口, Ctrl-A + d 脱离)"
  echo "Logs:"
  echo "  holders: $HLOG"
  echo "  early:   $ELOG"
}

stop_cmd() {
  # 关闭所有本工具的 screen 会话
  local sessions
  sessions=$(screen -ls | awk "/${SESSION_PREFIX}_/ {print \$1}" || true)
  if [[ -z "$sessions" ]]; then
    echo "No screen sessions with prefix '${SESSION_PREFIX}_' found."
  else
    echo "Killing screen sessions:"
    echo "$sessions" | while read -r s; do
      echo "  - $s"
      screen -S "$s" -X quit || true
    done
  fi

  # 保险：杀掉残留的 logscan 进程
  pgrep -f "python.*app.logscan" >/dev/null 2>&1 && \
    pkill -f "python.*app.logscan" || true

  echo "Stopped."
}

export_cmd() {
  ensure_dirs
  # 跑一轮过滤（幂等）
  echo "[filter] soft-filter ..."
  python -m app.cli soft-filter --limit 2000 || true
  echo "[filter] hard-verify ..."
  python -m app.cli hard-verify --limit 2000 || true

  # 导出
  local TS=$(date +'%Y%m%d_%H%M%S')
  for KIND in WHITE WATCH BLACK; do
    sqlite3 -noheader "$DB" \
      "SELECT addr FROM lists WHERE status='$KIND' ORDER BY updated_at DESC;" \
      > "$OUTDIR/${KIND}_${TS}.txt"
    echo "[ok] $OUTDIR/${KIND}_${TS}.txt"
  done

  sqlite3 -header -csv "$DB" \
    "SELECT addr,chain,status,reason,updated_at FROM lists ORDER BY status DESC, updated_at DESC;" \
    > "$OUTDIR/lists_${TS}.csv"
  echo "[ok] $OUTDIR/lists_${TS}.csv"
}

case "${1:-}" in
  start) shift; start_cmd "$@";;
  stop)  shift; stop_cmd;;
  export) shift; export_cmd;;
  *) usage; exit 1;;
esac
