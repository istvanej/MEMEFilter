import argparse, os, csv, time, re
from pathlib import Path
from typing import Dict, List

try:
    from app.rpc import SolRpc
except Exception:
    SolRpc = None

def _ts(): return time.strftime("%H:%M:%S")
def log(msg): print(f"[{_ts()}] {msg}", flush=True)

def _f(v, default=0.0):
    try:
        if v is None: return default
        if isinstance(v, str):
            s = v.strip()
            if s == "": return default
            if s.endswith("%"):
                s = s[:-1]
            return float(s)
        return float(v)
    except (ValueError, TypeError):
        return default

def _i(v, default=0):
    try:
        if v is None: return default
        if isinstance(v, str) and v.strip()=="":
            return default
        return int(v)
    except (ValueError, TypeError):
        return default

def list_scored_files(mint6: str, sources: List[str]) -> List[Path]:
    base = Path("data/exports")
    pats = []
    if "white" in sources: pats.append(f"white_scored_{mint6}_*.csv")
    if "watch" in sources: pats.append(f"watch_scored_{mint6}_*.csv")
    files: List[Path] = []
    for pat in pats:
        files.extend(sorted(base.glob(pat)))
    return files

def load_scored_rows(mint6: str, sources: List[str]) -> List[Dict]:
    files = list_scored_files(mint6, sources)
    if not files:
        log(f"[WARN] 没找到 scored CSV：data/exports/({'|'.join(sources)})_scored_{mint6}_*.csv")
        return []
    rows_map: Dict[str, Dict] = {}
    for fp in files:
        try:
            with open(fp, "r", newline="") as f:
                r = csv.DictReader(f)
                cnt = 0
                for row in r:
                    cnt += 1
                    addr = (row.get("addr") or row.get("address") or row.get("owner") or "").strip()
                    if not addr: continue
                    rows_map[addr] = row
            log(f"加载 {fp.name}: {cnt} 行")
        except Exception as e:
            log(f"[ERR] 读取 {fp.name} 失败：{e}")
    log(f"合并后唯一地址: {len(rows_map)}")
    return list(rows_map.values())

def normalize_row(raw: Dict) -> Dict:
    # 地址
    addr = (raw.get("addr") or raw.get("address") or raw.get("owner") or "").strip()
    # 胜率（兼容 wr/winrate/win_rate/百分号/0~100）
    win_raw = raw.get("win_rate") or raw.get("winrate") or raw.get("wr") or raw.get("win") or 0
    win = _f(win_raw, 0.0)
    if win > 1.0:   # 自动把百分数转成 0~1
        win = win / 100.0
    if win < 0.0: win = 0.0
    if win > 1.0: win = 1.0
    # 回合
    rounds = _i(raw.get("rounds") or raw.get("n_rounds") or raw.get("num_rounds") or 0, 0)
    # 余额（兼容 sol/sol_balance/balance；空串与异常按 0.0）
    sol = _f(raw.get("sol_balance") or raw.get("sol") or raw.get("balance") or 0.0, 0.0)
    x = dict(raw)
    x.update({"addr": addr, "win_rate": win, "rounds": rounds, "sol_balance": sol})
    return x

def refresh_balances(rows: List[Dict], sleep_ms: int=0):
    if SolRpc is None:
        log("[WARN] 找不到 app.rpc.SolRpc，无法刷新余额（沿用 CSV 的 sol_balance）")
        return
    rpc = SolRpc()
    n = len(rows)
    ok = err = 0
    for i, x in enumerate(rows, 1):
        a = x["addr"]
        try:
            r = rpc.get_balance(a)  # lamports
            v = r.get("value")
            if isinstance(v, dict): v = v.get("value", 0)
            x["sol_balance"] = (v or 0) / 1_000_000_000
            ok += 1
        except Exception:
            err += 1
        if (i % max(1,n//10 or 1)) == 0 or i == n:
            print(f"[{_ts()}] [balance] {i}/{n} ok={ok} err={err}", flush=True)
        if sleep_ms>0: time.sleep(sleep_ms/1000.0)

def main():
    ap = argparse.ArgumentParser(description="GMGN筛选：胜率 & SOL余额（带日志/进度）")
    ap.add_argument("--mint", required=True)
    ap.add_argument("--sources", default="white,watch")
    ap.add_argument("--min-win", type=float, default=0.50)  # 0~1
    ap.add_argument("--min-sol", type=float, default=1.0)
    ap.add_argument("--max-sol", type=float, default=50.0)
    ap.add_argument("--min-rounds", type=int, default=0)
    ap.add_argument("--refresh-balance", action="store_true")
    ap.add_argument("--balance-sleep-ms", type=int, default=0)
    ap.add_argument("--topk", type=int, default=0)
    ap.add_argument("--show-head", type=int, default=10)
    ap.add_argument("--dry", action="store_true", help="只打印各阶段计数，不导出文件")
    args = ap.parse_args()

    mint6 = args.mint[:6]
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    log(f"开始：mint6={mint6} sources={sources} 规则: win>={args.min_win}, sol∈[{args.min_sol},{args.max_sol}], rounds>={args.min_rounds}")

    raw_rows = load_scored_rows(mint6, sources)
    if not raw_rows:
        log("无数据，退出。"); return

    rows = [normalize_row(r) for r in raw_rows]
    total = len(rows)
    empty_addr = sum(1 for x in rows if not x["addr"])
    zero_sol = sum(1 for x in rows if _f(x["sol_balance"],0.0) == 0.0)
    zero_round = sum(1 for x in rows if _i(x["rounds"],0) == 0)
    # 估计胜率规模（看是否大于1）
    gt1 = sum(1 for x in rows if _f(x["win_rate"],0.0) > 1.0)
    log(f"汇总：total={total}, empty_addr={empty_addr}, zero_sol={zero_sol}, zero_rounds={zero_round}, win_rate>1 的行数={gt1}")

    if args.refresh_balance:
        log("刷新余额中…")
        refresh_balances(rows, sleep_ms=args.balance_sleep_ms)
        zero_sol = sum(1 for x in rows if _f(x["sol_balance"],0.0) == 0.0)
        log(f"余额刷新后 zero_sol={zero_sol}")

    # 逐步过滤并打印每步计数
    kept = list(rows)
    before = len(kept)
    # 胜率
    kept = [x for x in kept if _f(x.get("win_rate"),0.0) >= args.min_win]
    log(f"胜率过滤：{before} -> {len(kept)} (min_win={args.min_win})")
    before = len(kept)
    # 余额
    kept = [x for x in kept if args.min_sol <= _f(x.get("sol_balance"),0.0) <= args.max_sol]
    log(f"余额过滤：{before} -> {len(kept)} (sol∈[{args.min_sol},{args.max_sol}])")
    before = len(kept)
    # 回合
    if args.min_rounds > 0:
        kept = [x for x in kept if _i(x.get("rounds"),0) >= args.min_rounds]
        log(f"回合过滤：{before} -> {len(kept)} (min_rounds={args.min_rounds})")

    # 排序
    kept.sort(key=lambda z: (_f(z.get("win_rate"),0.0), _i(z.get("rounds"),0), _f(z.get("sol_balance"),0.0)), reverse=True)
    if args.topk and len(kept) > args.topk:
        kept = kept[:args.topk]
        log(f"截断到前 {args.topk} 条")

    # 预览
    headn = min(args.show_head, len(kept))
    if headn>0:
        log(f"预览前 {headn}：")
        for i in range(headn):
            x = kept[i]
            print(f"{i+1:>3}. {x['addr']} | win={_f(x['win_rate']):.2f} | rounds={_i(x['rounds'])} | sol={_f(x['sol_balance']):.3f}", flush=True)

    if args.dry:
        log("[DRY] 只预览不过账，不导出文件。")
        return

    # 导出
    os.makedirs("data/exports", exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    csvp = f"data/exports/gmgn_select_{mint6}_{ts}.csv"
    txtp = f"data/exports/gmgn_select_{mint6}_{ts}.txt"
    with open(csvp,"w",newline="") as f:
        w = csv.writer(f); w.writerow(["addr","win_rate","rounds","sol_balance"])
        for x in kept:
            w.writerow([x["addr"], _f(x["win_rate"]), _i(x["rounds"]), _f(x["sol_balance"])])
    with open(txtp,"w") as f:
        for x in kept:
            f.write(x["addr"]+"\n")
    log(f"[OK] filtered={len(kept)}")
    log(f"[OK] CSV -> {csvp}")
    log(f"[OK] TXT -> {txtp}")
