import os, glob, csv
from typing import List, Dict, Any, Optional

def _latest(pattern: str) -> Optional[str]:
    files = glob.glob(pattern)
    if not files: return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]

def load_scored(sources: List[str], explicit_files: List[str]=None) -> List[Dict[str,Any]]:
    rows=[]; files=[]
    if explicit_files:
        files = explicit_files
    else:
        if "white" in sources:
            f=_latest("data/exports/white_scored_*.csv")
            if f: files.append(f)
        if "watch" in sources:
            f=_latest("data/exports/watch_scored_*.csv")
            if f: files.append(f)
    for path in files:
        try:
            with open(path, newline="") as f:
                r=csv.DictReader(f)
                for row in r:
                    row["_source"]=os.path.basename(path).split("_")[0]  # white / watch
                    rows.append(row)
        except Exception:
            continue
    return rows

def _f(x, key, default=0.0):
    try: return float(x.get(key, default))
    except: return default

def _i(x, key, default=0):
    try: return int(float(x.get(key, default)))
    except: return default

def filter_and_sort(rows: List[Dict[str,Any]],
                    min_rounds:int=5,
                    min_win_rate:float=0.6,
                    min_avg_pnl:float=0.0,
                    max_drawdown: Optional[float]=None,
                    min_sol: float=1.0) -> List[Dict[str,Any]]:
    """
    max_drawdown：为负数，阈值越小回撤越大；若为 None 则不限制。
    min_sol：若行包含 sol_balance 字段则生效（watch 文件有，white 可能没有）。
    """
    out=[]
    for r in rows:
        rounds = _i(r, "rounds", 0)
        win_rate = _f(r, "win_rate", 0.0)
        avg_pnl = _f(r, "avg_pnl", -1e9)
        mdd = _f(r, "max_drawdown", 0.0)
        sol = _f(r, "sol_balance", 0.0) if "sol_balance" in r else None

        if rounds < min_rounds: continue
        if win_rate < min_win_rate: continue
        if avg_pnl < min_avg_pnl: continue
        if max_drawdown is not None and mdd < max_drawdown: continue  # mdd更小=更差
        if sol is not None and sol < min_sol: continue  # 仅在有余额字段时启用

        out.append(r)

    # 排序：win_rate desc, rounds desc, avg_pnl desc, sol_balance desc(若存在)
    out.sort(key=lambda r: (
        _f(r,"win_rate",0.0),
        _i(r,"rounds",0),
        _f(r,"avg_pnl",0.0),
        _f(r,"sol_balance",0.0)
    ), reverse=True)
    return out

def export_csv(rows: List[Dict[str,Any]], path: str):
    if not rows:
        cols=["addr","sol_balance","rounds","wins","win_rate","total_pnl","avg_pnl","median_hold_s","max_drawdown","_source"]
    else:
        cols=list(rows[0].keys())
        if "addr" in cols:
            cols.remove("addr"); cols.insert(0,"addr")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    import csv as _csv
    with open(path,"w",newline="") as f:
        w=_csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows: w.writerow(r)

def export_txt(rows: List[Dict[str,Any]], path: str, topk:int):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"w") as f:
        for r in rows[:topk]:
            f.write(r.get("addr","")+"\n")
