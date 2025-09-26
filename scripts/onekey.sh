#!/usr/bin/env bash
set -euo pipefail

# 用法:
#   ./scripts/onekey.sh <TOKEN_ADDR> [CHAIN]
# CHAIN: auto|sol|bsc|base （默认 auto）

TOKEN="${1:-}"
CHAIN="${2:-auto}"
if [[ -z "$TOKEN" ]]; then read -rp "请输入合约地址(Mint/Token): " TOKEN; fi
[[ -z "${TOKEN:-}" ]] && { echo "ERROR: 未输入地址"; exit 1; }

export TOKEN_SH="$TOKEN"   # 给子进程用
T6="${TOKEN:0:6}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p logs data/exports
RUN_LOG="logs/run_${T6}_${TS}.log"; : > "$RUN_LOG"
_now(){ date "+%H:%M:%S"; }
log(){ echo "[$(_now)] $*" | tee -a "$RUN_LOG" ; }

# 环境
if [[ -f .env ]]; then set -a; source .env; set +a; fi

# ========== 自动识别链 ==========
if [[ "$CHAIN" == "auto" ]]; then
  log "[detect] 自动识别链…"
  CHAIN="$(python -m app.detect_chain "$TOKEN" 2>&1 | tee -a "$RUN_LOG" | tail -n1 | tr -d '\r\n' )"
  log "[detect] 识别为: $CHAIN"
fi

log "=== start CHAIN=$CHAIN TOKEN=$TOKEN ==="
export CHAIN   # 给子进程用

# ========== 主流程 ==========
if [[ "$CHAIN" == "sol" ]]; then
  [[ -z "${SOLANA_RPC_URL:-}" ]] && { log "ERROR: 缺少 SOLANA_RPC_URL"; exit 1; }

  python -u -m app.cli reset-mint --mint "$TOKEN" 2>/dev/null || true

  log "[sol] holders"
  python -u -m app.logscan holders --mint "$TOKEN" --topn 800 | tee -a "$RUN_LOG"

  log "[sol] early"
  python -u -m app.logscan early --mint "$TOKEN" \
    --base_topn 800 --out_topn 80 --window_h 1.0 --sleep-ms 120 | tee -a "$RUN_LOG"

  log "[sol] score-watch / score-white"
  python -u -m app.cli score-watch --mint "$TOKEN" \
    --limit 1500 --min-rounds 1 --require-activity --sort-by sol --topk 0 --sleep-ms 5 | tee -a "$RUN_LOG"
  python -u -m app.cli score-white --mint "$TOKEN" \
    --limit 600  --min-rounds 1 --pos-expect --topk 0 --sleep-ms 5 | tee -a "$RUN_LOG"

else
  # -------- EVM：BSC/Base --------
  [[ "$CHAIN" == "bsc"  && -z "${BSC_RPC_URL:-}"  ]] && { log "ERROR: 缺少 BSC_RPC_URL";  exit 1; }
  [[ "$CHAIN" == "base" && -z "${BASE_RPC_URL:-}" ]] && { log "ERROR: 缺少 BASE_RPC_URL"; exit 1; }

  log "[evm] holders_recent"
  python - <<'PY' | tee -a "$RUN_LOG"
from app.evm_rpc import EvmRpc
from app.evm_scan import holders_recent
import os, pathlib
chain=os.environ["CHAIN"].lower()
rpc=EvmRpc(chain)
owners=holders_recent(chain, rpc, os.environ["TOKEN_SH"], lookback_blocks=120000, step=4000, topn=800)
print("[evm] owners", len(owners))
from datetime import datetime
T6=os.environ["TOKEN_SH"][:6]; TS=datetime.now().strftime("%Y%m%d_%H%M%S")
pathlib.Path(f"logs/evm_holders_{T6}_{TS}.txt").write_text("\n".join(owners))
PY

  log "[evm] early_buyers"
  python - <<'PY' | tee -a "$RUN_LOG"
from app.evm_rpc import EvmRpc
from app.evm_scan import early_buyers
import os, glob, pathlib
from datetime import datetime
chain=os.environ["CHAIN"].lower()
token=os.environ["TOKEN_SH"]
rpc=EvmRpc(chain)
T6=token[:6]
holders_files=sorted(glob.glob(f"logs/evm_holders_{T6}_*.txt"))
owners=[]
if holders_files:
    owners=[x.strip() for x in pathlib.Path(holders_files[-1]).read_text().splitlines() if x.strip()]
hits=early_buyers(chain, rpc, token, owners, window_h=1.0)
TS=datetime.now().strftime("%Y%m%d_%H%M%S")
pathlib.Path(f"logs/evm_early_{T6}_{TS}.txt").write_text("\n".join(hits))
print("[evm] hits", len(hits))
PY
fi

# ========== 统一收尾导出（CSV + TXT；余额过滤 0.5~15） ==========
log "[final] 导出（刷新原生余额，过滤 0.5~15）"
python - <<'PY' | tee -a "$RUN_LOG"
import os,sys,re,csv,glob,time
from pathlib import Path
from datetime import datetime

CHAIN=os.environ.get("CHAIN","sol").lower()
TOKEN=os.environ.get("TOKEN_SH","")
t6=TOKEN[:6]
ROOT=Path(".").resolve(); exports=ROOT/"data/exports"; logs=ROOT/"logs"
exports.mkdir(parents=True, exist_ok=True)
MIN_SOL=float(os.environ.get("FINAL_MIN_SOL","0.5"))
MAX_SOL=float(os.environ.get("FINAL_MAX_SOL","15"))
BAL_SLEEP_MS=int(os.environ.get("FINAL_BAL_SLEEP_MS","10"))

# 1) 汇集候选地址
cands=[]
if CHAIN=="sol":
    csvs=sorted(glob.glob(f"data/exports/*scored_{t6}_*.csv"))
    for fp in csvs[-4:]:
        try:
            with open(fp,newline="") as f:
                r=csv.DictReader(f)
                for row in r:
                    a=(row.get("addr") or row.get("address") or row.get("owner") or "").strip()
                    if a: cands.append(a)
        except: pass
    hit_logs=sorted(glob.glob(f"logs/early_hits_{t6}_*.txt"))
    if hit_logs:
        with open(hit_logs[-1]) as f:
            for ln in f:
                m=re.search(r"[1-9A-HJ-NP-Za-km-z]{32,44}", ln)
                if m: cands.append(m.group(0))
else:
    for fp in sorted(glob.glob(f"logs/evm_holders_{t6}_*.txt")+glob.glob(f"logs/evm_early_{t6}_*.txt"))[-4:]:
        try:
            with open(fp) as f:
                cands += [x.strip() for x in f if x.strip()]
        except: pass

# 去重
seen=set(); addrs=[]
for a in cands:
    if a not in seen:
        seen.add(a); addrs.append(a)
print(f"[final] candidates={len(addrs)}")

# 2) 余额接口
def try_sol():
    try:
        from app.rpc import SolRpc
        r=SolRpc()
        def gb(a):
            v=r.get_balance(a); val=v.get("value")
            if isinstance(val,dict): val=val.get("value",0)
            return (val or 0)/1_000_000_000
        return gb
    except Exception: return None

def try_evm():
    try:
        from app.evm_rpc import EvmRpc
        r=EvmRpc(CHAIN)
        def gb(a): return r.get_balance(a)
        return gb
    except Exception: return None

get_bal = try_sol() if CHAIN=="sol" else try_evm()
if get_bal is None:
    print("[final][ERR] 无法创建余额查询器"); sys.exit(0)

kept=[]; n=len(addrs); ok=err=0
for i,a in enumerate(addrs,1):
    try:
        bal=get_bal(a)
        if MIN_SOL<=bal<=MAX_SOL:
            kept.append((a,bal))
        ok+=1
    except Exception:
        err+=1
    if (i%max(1,n//10 or 1)==0) or (i==n):
        print(f"[BAL] {i}/{n} ok={ok} err={err} kept={len(kept)}", flush=True)
    if BAL_SLEEP_MS>0: import time as _t; _t.sleep(BAL_SLEEP_MS/1000.0)

ts=datetime.now().strftime("%Y%m%d_%H%M%S")
txt=str(exports/f"final_{CHAIN}_{t6}_{ts}.txt")
csvp=str(exports/f"final_{CHAIN}_{t6}_{ts}.csv")
with open(txt,"w") as f:
    for a,_ in kept: f.write(a+"\n")
with open(csvp,"w",newline="") as f:
    w=csv.writer(f); w.writerow(["addr","native_balance"])
    for a,b in kept: w.writerow([a,b])
print(f"[OK] 导出 {len(kept)} rows")
print("TXT:", txt)
print("CSV:", csvp)
PY

log "=== done ==="
