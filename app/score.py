import csv, time, statistics
from typing import Dict, Any, List, Tuple
from datetime import datetime
from app.db import conn
from app.rpc import SolRpc
from app.t0 import estimate_t0
from app.rounds import rounds_with_usd

def _ts(): return datetime.now().strftime("%H:%M:%S")
def _log(*args): print(f"[{_ts()}]", *args, flush=True)

class Meter:
    def __init__(self, total:int, tick:int=20):
        self.total=total; self.tick=max(1, tick); self.start=time.time(); self.done=0; self.err=0
    def step(self, ok=True):
        self.done+=1
        if not ok: self.err+=1
        if (self.done % self.tick)==0 or self.done==self.total:
            el=max(1e-6, time.time()-self.start); rps=self.done/el; eta=(self.total-self.done)/rps if rps>0 else 0
            _log(f"[PROGRESS] {self.done}/{self.total} rps={rps:.2f} eta={eta/60:.1f}m err={self.err}")

def fetch_white(limit:int=None) -> List[str]:
    with conn() as c:
        cur = c.execute(
            "SELECT addr FROM lists WHERE status='WHITE' ORDER BY updated_at DESC LIMIT ?;" if limit
            else "SELECT addr FROM lists WHERE status='WHITE' ORDER BY updated_at DESC;", 
            (limit,) if limit else ()
        )
        return [r[0] for r in cur.fetchall()]

def fetch_watch(limit:int=None) -> List[str]:
    with conn() as c:
        cur = c.execute(
            "SELECT addr FROM lists WHERE status='WATCH' ORDER BY updated_at DESC LIMIT ?;" if limit
            else "SELECT addr FROM lists WHERE status='WATCH' ORDER BY updated_at DESC;", 
            (limit,) if limit else ()
        )
        return [r[0] for r in cur.fetchall()]

def calc_metrics(trips: List[Dict[str,Any]]) -> Dict[str,Any]:
    n = len(trips)
    if n == 0:
        return {"rounds":0,"wins":0,"win_rate":0.0,"total_pnl":0.0,"avg_pnl":0.0,"median_hold_s":0,"max_drawdown":0.0}
    pnls = [float(t.get("pnl_usd") or 0.0) for t in trips]
    wins = sum(1 for x in pnls if x > 0)
    total = sum(pnls)
    avg = total / n
    holds = [int(t.get("hold_s") or 0) for t in trips if t.get("hold_s") is not None]
    median_hold = int(statistics.median(holds)) if holds else 0
    dd = 0.0; peak = 0.0; acc = 0.0
    for x in pnls:
        acc += x; peak = max(peak, acc); dd = min(dd, acc - peak)
    return {"rounds": n, "wins": wins, "win_rate": wins/n, "total_pnl": total, "avg_pnl": avg,
            "median_hold_s": median_hold, "max_drawdown": dd}

def score_white_for_mint(rpc: SolRpc, mint: str, white_addrs: List[str],
                         price_url: str=None, price_key: str=None, t0: int=None,
                         decimals: int=9, sleep_ms: int=0) -> List[Dict[str,Any]]:
    out=[]
    if t0 is None:
        try: t0 = estimate_t0(rpc, mint, sample_holders=8)
        except Exception: t0 = None
    m = Meter(total=len(white_addrs), tick=max(1, len(white_addrs)//20 or 1))
    for addr in white_addrs:
        ok=True
        try:
            trips = rounds_with_usd(rpc, addr, mint, t0, price_url, price_key, decimals=decimals)
            met = calc_metrics(trips)
            out.append({"addr": addr, **met})
        except KeyboardInterrupt:
            break
        except Exception:
            ok=False
            out.append({"addr": addr, "rounds":0,"wins":0,"win_rate":0.0,"total_pnl":0.0,"avg_pnl":0.0,"median_hold_s":0,"max_drawdown":0.0})
        finally:
            if sleep_ms>0: time.sleep(sleep_ms/1000.0)
            m.step(ok=ok)
    return out

def _batch(iterable, n=100):
    buf=[]
    for x in iterable:
        buf.append(x)
        if len(buf)>=n:
            yield buf; buf=[]
    if buf: yield buf

def _batch_sol_balances(rpc: SolRpc, addrs: List[str]) -> dict:
    sol_map={}
    for chunk in _batch(addrs, 100):
        try:
            res = rpc.get_multiple_accounts(chunk) or {}
            vals = (res or {}).get("value") or []
            for i, v in enumerate(vals):
                lamports = 0
                if isinstance(v, dict):
                    lamports = int((v.get("lamports") or 0)) if "lamports" in v else int((v.get("value") or {}).get("lamports") or 0)
                sol_map[chunk[i]] = lamports / 1_000_000_000
        except Exception:
            # 回退不填，后续按 0 处理
            pass
    return sol_map

def score_watch_for_mint(rpc: SolRpc, mint: str, watch_addrs: List[str],
                         price_url: str=None, price_key: str=None, t0: int=None,
                         decimals: int=9, sleep_ms: int=0, require_activity: bool=False) -> List[Dict[str,Any]]:
    out=[]
    if t0 is None:
        try: t0 = estimate_t0(rpc, mint, sample_holders=8)
        except Exception: t0 = None

    # 先批量拿余额，RPC 从 N 次 → N/100 次
    sol_map = _batch_sol_balances(rpc, watch_addrs)

    total=len(watch_addrs)
    m = Meter(total=total, tick=max(1, total//20 or 1))
    for i, addr in enumerate(watch_addrs, 1):
        ok=True
        sol_bal = float(sol_map.get(addr, 0.0))
        trips=[]; met={}
        try:
            trips = rounds_with_usd(rpc, addr, mint, t0, price_url, price_key, decimals=decimals)
            met = calc_metrics(trips)
        except KeyboardInterrupt:
            break
        except Exception:
            ok=False
            met = {"rounds":0,"wins":0,"win_rate":0.0,"total_pnl":0.0,"avg_pnl":0.0,"median_hold_s":0,"max_drawdown":0.0}

        if (not require_activity) or (met.get("rounds",0) >= 1):
            row={"addr": addr, "sol_balance": sol_bal, **met}
            out.append(row)
            if (i % 5)==0 or i==total:
                _log(f"[WATCH] {i}/{total} addr={addr[:8]}… sol={sol_bal:.3f} rounds={row['rounds']} win={row['win_rate']:.2f} pnl={row['total_pnl']:.2f}")

        if sleep_ms>0: time.sleep(sleep_ms/1000.0)
        m.step(ok=ok)
    return out

def filter_and_sort(rows: List[Dict[str,Any]], min_rounds:int=3, pos_expect:bool=False, sort_by:str="white") -> List[Dict[str,Any]]:
    rows = [r for r in rows if int(r.get("rounds",0)) >= min_rounds]
    if pos_expect:
        rows = [r for r in rows if float(r.get("avg_pnl",0.0)) >= 0]
    if sort_by == "sol":
        rows.sort(key=lambda r: (r.get("sol_balance",0.0), r.get("win_rate",0.0), r.get("total_pnl",0.0)), reverse=True)
    elif sort_by == "pnl":
        rows.sort(key=lambda r: (r.get("total_pnl",0.0), r.get("win_rate",0.0)), reverse=True)
    else:
        rows.sort(key=lambda r: (r.get("win_rate",0.0), r.get("total_pnl",0.0), r.get("avg_pnl",0.0)), reverse=True)
    return rows

def export_csv(rows: List[Dict[str,Any]], path: str):
    base = ["addr","sol_balance","rounds","wins","win_rate","total_pnl","avg_pnl","median_hold_s","max_drawdown"]
    with open(path,"w",newline="") as f:
        w=csv.DictWriter(f, fieldnames=base); w.writeheader()
        for r in rows: w.writerow({k:r.get(k) for k in base})

def export_txt_addrs(rows: List[Dict[str,Any]], path: str, topk:int):
    with open(path,"w") as f:
        for r in rows[:topk]:
            f.write(r["addr"]+"\n")
