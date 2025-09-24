import sys, time, traceback
from datetime import datetime
from typing import List, Tuple
from app.rpc import SolRpc
from app.entry import import_token
from app.solana_spl import recent_token_owners
from app.txscan import (
    replay_recent_for_owner,
    guess_atas_for_owner,
    replay_owner_windowed,
)
from app.db import add_candidates
from app.t0 import estimate_t0

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def log(*args, **kw):
    print(f"[{ts()}]", *args, flush=True, **kw)

def elog(*args, **kw):
    print(f"[{ts()}][ERR]", *args, file=sys.stderr, flush=True, **kw)

class Meter:
    def __init__(self, total:int, tick:int=10):
        self.total=total
        self.tick=max(1,tick)
        self.start=time.time()
        self.done=0
        self.rpc_ok=0
        self.rpc_fail=0
    def step(self, n:int=1):
        self.done+=n
        if self.done%self.tick==0 or self.done==self.total:
            self.print_progress()
    def hit_rpc(self, ok:bool=True):
        if ok: self.rpc_ok+=1
        else:  self.rpc_fail+=1
    def print_progress(self, extra:str=""):
        elapsed=max(1e-6, time.time()-self.start)
        rps=self.done/elapsed
        eta_s=(self.total-self.done)/rps if rps>0 else 0
        msg=f"progress {self.done}/{self.total} (rps={rps:.2f}, eta={eta_s/60:.1f}m, rpc_ok={self.rpc_ok}, rpc_fail={self.rpc_fail})"
        if extra: msg += " | " + extra
        log(msg)

def scan_holders(mint: str, topn: int):
    rpc = SolRpc()
    log(f"[holders] start mint={mint} topn={topn}")
    owners = recent_token_owners(rpc, mint, topn=topn)
    total = len(owners)
    log(f"[holders] owners found={total}")
    add_candidates("sol", mint, owners, source="mint_scan")
    m = Meter(total, tick=max(1,total//10 or 1))
    for _ in owners:
        m.step()
    log(f"[holders] done, written candidates={total}")

def scan_early(
    mint: str,
    base_topn: int,
    tx_limit: int = 300,
    out_topn: int = 100,
    sleep_ms: int = 50,
    retry: int = 2,
    window_h: float = 2.0
):
    """
    早期买家（窗口加速版）：
      1) 估 T0
      2) 收集 base_topn 个当前持有人
      3) 对每个 owner：
         - 若有 T0：只在 [T0, T0+window_h] 内用 getTransaction 回放（先用 blockTime 过滤签名）
         - 否则：fallback 到慢路径 replay_recent_for_owner
      4) 命中条件：net>0 且 first_buy_idx>=0
    """
    rpc = SolRpc()
    log(f"[early] start mint={mint} base_topn={base_topn} window_h={window_h} out_topn={out_topn} sleep_ms={sleep_ms}")

    # 估 T0（一次）
    try:
        t0 = estimate_t0(rpc, mint, sample_holders=12)
    except Exception as e:
        t0 = None
        elog(f"[early] estimate_t0 failed: {e}")
    if t0 is None:
        log("[early] T0 unknown, fallback to slow path (no window).")

    base = recent_token_owners(rpc, mint, topn=base_topn)
    total = len(base)
    log(f"[early] base owners={total}")

    hits: List[Tuple[str,int,int]] = []  # (owner, fb_idx, net_raw)
    m = Meter(total, tick=max(1,total//20 or 1))

    for owner in base:
        if sleep_ms>0: time.sleep(sleep_ms/1000.0)
        try:
            if t0 is not None:
                net, fb = replay_owner_windowed(rpc, owner, mint, t0, window_h=window_h, max_sigs_per_ata=600)
                m.hit_rpc(True)
            else:
                # 慢路径
                net, fb = replay_recent_for_owner(rpc, owner, mint, max_txs=tx_limit)
                m.hit_rpc(True)
        except Exception as e:
            m.hit_rpc(False)
            elog(f"[early] owner={owner[:8]}… err={e}")
            m.step(); continue

        if net > 0 and fb >= 0:
            hits.append((owner, fb, net))
            log(f"[early][HIT] {owner} fb={fb} net={net}")

        m.step()

    # 排序/截断并入库
    hits.sort(key=lambda x: x[1])
    out=[o for (o,_,_) in hits[:out_topn]]
    add_candidates("sol", mint, out, source="early_buyers")
    log(f"[early] done hits={len(hits)} early_top={len(out)} (written)")

def main():
    import argparse
    ap = argparse.ArgumentParser("logscan (holders/early with verbose progress)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("holders")
    p.add_argument("--mint", required=True)
    p.add_argument("--topn", type=int, default=300)

    p = sub.add_parser("early")
    p.add_argument("--mint", required=True)
    p.add_argument("--base_topn", type=int, default=300)
    p.add_argument("--tx_limit", type=int, default=300)
    p.add_argument("--out_topn", type=int, default=100)
    p.add_argument("--sleep_ms", type=int, default=50)
    p.add_argument("--retry", type=int, default=2)
    p.add_argument("--window_h", type=float, default=2.0)

    a = ap.parse_args()

    # 确保 pools 有记录（幂等）
    try:
        import_token("sol", getattr(a, "mint"), source="manual")
    except Exception:
        pass

    if a.cmd == "holders":
        scan_holders(a.mint, a.topn)
    else:
        scan_early(a.mint, a.base_topn, a.tx_limit, a.out_topn, a.sleep_ms, a.retry, a.window_h)

if __name__ == "__main__":
    main()
