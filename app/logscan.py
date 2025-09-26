from typing import List, Tuple
import time, argparse, os
from datetime import datetime
from app.rpc import SolRpc
from app.solana_spl import recent_token_owners
from app.db import add_candidates
from app.t0 import estimate_t0
from app.txscan import replay_recent_for_owner, replay_owner_windowed

def _ts(): return datetime.now().strftime("%H:%M:%S")
def log(*args): print(f"[{_ts()}]", *args, flush=True)
def elog(*args): print(f"[{_ts()}][ERR]", *args, flush=True)

class Meter:
    def __init__(self, total:int, tick:int=80):
        self.total=total; self.tick=max(1, tick); self.start=time.time()
        self.done=0; self.ok=0; self.fail=0
    def hit_rpc(self, ok:bool):
        if ok: self.ok+=1
        else: self.fail+=1
    def step(self):
        self.done+=1
        if (self.done % self.tick)==0 or self.done==self.total:
            el=max(1e-6, time.time()-self.start)
            rps=self.done/el
            eta=(self.total-self.done)/rps if rps>0 else 0
            print(f"[{_ts()}] progress {self.done}/{self.total} (rps={rps:.2f}, eta={eta/60:.1f}m, rpc_ok={self.ok}, rpc_fail={self.fail})", flush=True)

def scan_holders(mint: str, topn: int = 800):
    rpc = SolRpc()
    log(f"[holders] start mint={mint} topn={topn}")
    owners = recent_token_owners(rpc, mint, topn=topn)
    log(f"[holders] owners found={len(owners)}")
    m = Meter(len(owners), tick=max(1, len(owners)//10 or 1))
    add_candidates("sol", mint, owners, source="mint_scan")
    for _ in owners:
        m.hit_rpc(True); m.step()
    log(f"[holders] done, written candidates={len(owners)}")

def scan_early(mint: str, base_topn: int, tx_limit: int = 300, out_topn: int = 100,
               sleep_ms: int = 50, retry:int=1, window_h: float = 2.0):
    rpc = SolRpc()
    log(f"[early] start mint={mint} base_topn={base_topn} window_h={window_h} out_topn={out_topn}")
    try:
        t0 = estimate_t0(rpc, mint, sample_holders=12)
    except Exception as e:
        t0=None; elog(f"[early] estimate_t0 failed: {e}")
    base = recent_token_owners(rpc, mint, topn=base_topn)
    log(f"[early] base owners={len(base)}")
    m = Meter(len(base), tick=max(1, len(base)//10 or 1))
    hits: List[Tuple[str,int,int]] = []

    # 实时落盘：logs/early_hits_<mint6>_<ts>.txt
    os.makedirs("logs", exist_ok=True)
    fname = f"logs/early_hits_{mint[:6]}_{datetime.now().strftime('%H%M%S')}.txt"
    with open(fname, "w") as fh:
        fh.write("# addr\tfb\tnet\n")

    for owner in base:
        if sleep_ms>0: time.sleep(sleep_ms/1000.0)
        try:
            if t0 is not None:
                net, fb = replay_owner_windowed(rpc, owner, mint, t0, window_h=window_h, max_sigs_per_ata=600)
            else:
                net, fb = replay_recent_for_owner(rpc, owner, mint, max_txs=tx_limit)
            m.hit_rpc(True)
        except Exception as e:
            m.hit_rpc(False); elog(f"[early] owner={owner[:8]}… err={e}")
            m.step(); continue

        if net > 0 and fb >= 0:
            hits.append((owner, fb, net))
            log(f"[early][HIT] {owner} fb={fb} net={net}")
            try:
                with open(fname, "a") as fh:
                    fh.write(f"{owner}\t{fb}\t{net}\n")
            except Exception:
                pass
        m.step()

    hits.sort(key=lambda x: x[1])
    out=[o for (o,_,_) in hits[:out_topn]]
    add_candidates("sol", mint, out, source="early_buyers")
    log(f"[early] done hits={len(hits)} early_top={len(out)} (written)")
    log(f"[early] hits file -> {fname}")

def main():
    import argparse
    ap = argparse.ArgumentParser(prog="logscan", description="holders/early with verbose progress")
    sub = ap.add_subparsers()

    p = sub.add_parser("holders")
    p.add_argument("--mint", required=True)
    p.add_argument("--topn", type=int, default=800)
    p.set_defaults(func=lambda a: scan_holders(a.mint, a.topn))

    p = sub.add_parser("early")
    p.add_argument("--mint", required=True)
    p.add_argument("--base_topn", type=int, default=800)
    p.add_argument("--out_topn", type=int, default=100)
    p.add_argument("--tx_limit", type=int, default=300)
    p.add_argument("--window_h", type=float, default=2.0)
    p.add_argument("--sleep_ms", type=int, default=60)
    p.add_argument("--sleep-ms", dest="sleep_ms", type=int)
    p.add_argument("--retry", type=int, default=1)
    p.set_defaults(func=lambda a: scan_early(a.mint, a.base_topn, a.tx_limit, a.out_topn, a.sleep_ms, a.retry, a.window_h))

    a = ap.parse_args()
    if hasattr(a, "func"): a.func(a)
    else: ap.print_help()

if __name__ == "__main__":
    main()
