import argparse, csv, os, time, sqlite3
from app.rpc import SolRpc
from app.entry import import_token, scan_candidates_for_mint
from app.filters import soft_filter, hard_verify
from app.db import conn
from app.t0 import estimate_t0
from app.rounds import rounds_with_usd
from app.score import (
    fetch_white, fetch_watch,
    score_white_for_mint, score_watch_for_mint,
    filter_and_sort as score_filter_and_sort,
    export_csv as score_export_csv, export_txt_addrs as score_export_txt
)
from app.select import load_scored as select_load_scored, filter_and_sort as select_filter_and_sort
from app.select import export_csv as select_export_csv, export_txt as select_export_txt

def cmd_reset_mint(a):
    with conn() as c:
        try:
            c.execute("DELETE FROM lists WHERE token_address=?", (a.mint,))
            c.execute("DELETE FROM candidates WHERE token_address=?", (a.mint,))
        except sqlite3.OperationalError:
            try: c.execute("DELETE FROM lists WHERE token_address=?", (a.mint,))
            except: pass
        c.commit()
    print(f"[OK] reset-mint done for {a.mint}")

def cmd_import(a):
    import_token("sol", a.mint, a.amm, a.base, a.quote, source="manual")
    print(f"[OK] Imported {a.mint}", flush=True)

def cmd_scan(a):
    rpc = SolRpc()
    owners = scan_candidates_for_mint("sol", a.mint, rpc, topn=a.topn, mode=a.mode)
    print(f"[OK] candidates+={len(owners)} mode={a.mode}", flush=True)

def cmd_soft(a):
    rpc = SolRpc()
    w, wa, b = soft_filter(rpc, batch_limit=a.limit, verbose=a.verbose)
    print(f"[SOFT] total: W={w} Wa={wa} B={b}", flush=True)

def cmd_hard(a):
    rpc = SolRpc()
    w, wa, b = hard_verify(rpc, batch_limit=a.limit, verbose=a.verbose, sleep_ms=a.sleep_ms)
    print(f"[HARD] total: W={w} Wa={wa} B={b}", flush=True)

def cmd_view(a):
    with conn() as c:
        cur = c.execute(
            """SELECT datetime(first_seen,'localtime') AS seen, chain,
                      substr(token_address,1,10)||'…' AS token, addr,
                      COALESCE(status,'CANDIDATE') AS status, COALESCE(reason,'')
               FROM view_addresses
               ORDER BY status DESC, seen DESC
               LIMIT ?;""", (a.limit,)
        )
        rows = cur.fetchall()
    print("seen\t\tchain\ttoken\t\taddr\t\tstatus\treason", flush=True)
    for r in rows:
        print("\t".join(str(x) for x in r), flush=True)

def cmd_export_lists(a):
    with conn() as c:
        cur = c.execute("SELECT addr FROM lists WHERE status=? ORDER BY updated_at DESC;", (a.kind,))
        addrs = [r[0] for r in cur.fetchall()]
        os.makedirs("data/exports", exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        txt = f"data/exports/{a.kind}_{ts}.txt"
        with open(txt, "w") as f:
            for x in addrs: f.write(x + "\n")
        cur = c.execute("SELECT addr,chain,status,reason,updated_at FROM lists ORDER BY status DESC,updated_at DESC;")
        csvp = f"data/exports/lists_{ts}.csv"
        with open(csvp, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["addr", "chain", "status", "reason", "updated_at"]); w.writerows(cur.fetchall())
    print(f"[OK] {txt}\n[OK] {csvp}", flush=True)

def cmd_t0(a):
    rpc = SolRpc()
    t0 = estimate_t0(rpc, a.mint, sample_holders=a.sample)
    print(f"T0={t0}  ({'None' if t0 is None else time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t0))})", flush=True)

def cmd_rounds(a):
    rpc = SolRpc()
    dec = 9
    try:
        sup = rpc.get_token_supply(a.mint); dec = int(sup.get("value", {}).get("decimals", 9))
    except: pass
    t0 = None
    try: t0 = estimate_t0(rpc, a.mint, sample_holders=10)
    except: pass
    with conn() as c:
        if a.addr: addr_list = [a.addr]
        else:
            cur = c.execute("SELECT addr FROM lists WHERE status='WHITE' ORDER BY updated_at DESC LIMIT ?;", (a.limit,))
            addr_list = [r[0] for r in cur.fetchall()]
    os.makedirs("data/exports", exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = f"data/exports/rounds_{a.mint[:6]}_{ts}.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["addr","entry_ts","exit_ts","hold_s","bucket","buy_token","sell_token","pnl_token","pnl_usd"])
        for addr in addr_list:
            rs = rounds_with_usd(rpc, addr, a.mint, t0, a.price_url, a.price_key, decimals=dec)
            for r in rs:
                w.writerow([addr, r.get("entry_ts"), r.get("exit_ts"), r.get("hold_s"),
                            r.get("bucket"), r.get("buy_token"), r.get("sell_token"),
                            r.get("pnl_token"), r.get("pnl_usd")])
    print(f"[OK] rounds → {out}", flush=True)

def cmd_score_white(a):
    rpc = SolRpc()
    dec = 9
    try:
        sup = rpc.get_token_supply(a.mint); dec = int(sup.get("value", {}).get("decimals", 9))
    except: pass
    addrs = fetch_white(limit=a.limit)
    print(f"[SCORE] white addrs loaded: {len(addrs)}", flush=True)
    rows = score_white_for_mint(rpc, a.mint, addrs, price_url=a.price_url, price_key=a.price_key, t0=None, decimals=dec, sleep_ms=a.sleep_ms)
    print(f"[SCORE] scored rows: {len(rows)}", flush=True)
    rows = score_filter_and_sort(rows, min_rounds=a.min_rounds, pos_expect=a.pos_expect, sort_by="white")
    print(f"[SCORE] after filter: {len(rows)}", flush=True)
    ts = time.strftime("%Y%m%d_%H%M%S"); os.makedirs("data/exports", exist_ok=True)
    csvp = f"data/exports/white_scored_{a.mint[:6]}_{ts}.csv"
    score_export_csv(rows, csvp); print(f"[OK] CSV  -> {csvp}", flush=True)
    if a.topk > 0:
        txtp = f"data/exports/white_top_{a.mint[:6]}_{ts}.txt"
        score_export_txt(rows, txtp, a.topk); print(f"[OK] TOPK -> {txtp}", flush=True)

def cmd_score_watch(a):
    rpc = SolRpc()
    dec = 9
    try:
        sup = rpc.get_token_supply(a.mint); dec = int(sup.get("value", {}).get("decimals", 9))
    except: pass
    addrs = fetch_watch(limit=a.limit)
    print(f"[SCORE][WATCH] watch addrs loaded: {len(addrs)}", flush=True)
    rows = score_watch_for_mint(rpc, a.mint, addrs, price_url=a.price_url, price_key=a.price_key,
                                t0=None, decimals=dec, sleep_ms=a.sleep_ms, require_activity=a.require_activity)
    print(f"[SCORE][WATCH] scored rows: {len(rows)}", flush=True)
    rows = score_filter_and_sort(rows, min_rounds=a.min_rounds, pos_expect=a.pos_expect, sort_by=a.sort_by)
    print(f"[SCORE][WATCH] after filter: {len(rows)}", flush=True)
    ts = time.strftime("%Y%m%d_%H%M%S"); os.makedirs("data/exports", exist_ok=True)
    csvp = f"data/exports/watch_scored_{a.mint[:6]}_{ts}.csv"
    score_export_csv(rows, csvp); print(f"[OK] CSV  -> {csvp}", flush=True)
    if a.topk > 0:
        txtp = f"data/exports/watch_top_{a.mint[:6]}_{ts}.txt"
        score_export_txt(rows, txtp, a.topk); print(f"[OK] TOPK -> {txtp}", flush=True)

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

def cmd_score_select(a):
    srcs = [s.strip() for s in (a.sources or "white,watch").split(",") if s.strip()]
    files = [s.strip() for s in (a.files or "").split(",") if s.strip()]
    rows = select_load_scored(srcs, files if files else None)
    print(f"[SELECT] loaded rows: {len(rows)} from sources={srcs} files={files}", flush=True)
    rows = select_filter_and_sort(rows, min_rounds=a.min_rounds, min_win_rate=a.min_win_rate,
                                  min_avg_pnl=a.min_avg_pnl, max_drawdown=a.max_drawdown, min_sol=a.min_sol)
    if a.max_sol is not None:
        rows = [r for r in rows if _f(r.get("sol_balance", 0.0)) <= a.max_sol]
    print(f"[SELECT] after filter: {len(rows)}", flush=True)
    ts=time.strftime("%Y%m%d_%H%M%S"); os.makedirs("data/exports", exist_ok=True)
    csvp=f"data/exports/highwin_{a.mint[:6]}_{ts}.csv"
    txtp=f"data/exports/highwin_{a.mint[:6]}_{ts}.txt"
    select_export_csv(rows, csvp); select_export_txt(rows, txtp, a.topk)
    print(f"[OK] CSV -> {csvp}\n[OK] TXT -> {txtp}")

def main():
    ap = argparse.ArgumentParser(prog="meme-follow-sol")
    sub = ap.add_subparsers()

    p = sub.add_parser("reset-mint")
    p.add_argument("--mint", required=True); p.set_defaults(func=cmd_reset_mint)

    p = sub.add_parser("import-token")
    p.add_argument("--mint", required=True); p.add_argument("--amm", default="raydium")
    p.add_argument("--base", default="USDC"); p.add_argument("--quote", default="SOL")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("scan-mint")
    p.add_argument("--mint", required=True); p.add_argument("--topn", type=int, default=200)
    p.add_argument("--mode", choices=["holders", "early"], default="early")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("soft-filter")
    p.add_argument("--limit", type=int, default=800); p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_soft)

    p = sub.add_parser("hard-verify")
    p.add_argument("--limit", type=int, default=400); p.add_argument("--verbose", action="store_true")
    p.add_argument("--sleep-ms", type=int, default=0); p.set_defaults(func=cmd_hard)

    p = sub.add_parser("view")
    p.add_argument("--limit", type=int, default=200); p.set_defaults(func=cmd_view)

    p = sub.add_parser("export")
    p.add_argument("--kind", choices=["WHITE", "WATCH", "BLACK"], required=True); p.set_defaults(func=cmd_export_lists)

    p = sub.add_parser("t0")
    p.add_argument("--mint", required=True); p.add_argument("--sample", type=int, default=15); p.set_defaults(func=cmd_t0)

    p = sub.add_parser("rounds")
    p.add_argument("--mint", required=True); p.add_argument("--addr"); p.add_argument("--limit", type=int, default=50)
    p.add_argument("--price_url"); p.add_argument("--price_key"); p.set_defaults(func=cmd_rounds)

    p = sub.add_parser("score-white")
    p.add_argument("--mint", required=True); p.add_argument("--limit", type=int, default=500)
    p.add_argument("--min-rounds", type=int, default=3); p.add_argument("--pos-expect", action="store_true")
    p.add_argument("--topk", type=int, default=50); p.add_argument("--sleep-ms", type=int, default=0)
    p.add_argument("--price_url"); p.add_argument("--price_key"); p.set_defaults(func=cmd_score_white)

    p = sub.add_parser("score-watch")
    p.add_argument("--mint", required=True); p.add_argument("--limit", type=int, default=800)
    p.add_argument("--min-rounds", type=int, default=1); p.add_argument("--pos-expect", action="store_true")
    p.add_argument("--require-activity", action="store_true")
    p.add_argument("--sort-by", choices=["white", "sol", "pnl"], default="sol")
    p.add_argument("--topk", type=int, default=50); p.add_argument("--sleep-ms", type=int, default=0)
    p.add_argument("--price_url"); p.add_argument("--price_key"); p.set_defaults(func=cmd_score_watch)

    p = sub.add_parser("score-select")
    p.add_argument("--mint", required=True)
    p.add_argument("--sources", default="white,watch")
    p.add_argument("--files")
    p.add_argument("--min-rounds", type=int, default=3)
    p.add_argument("--min-win-rate", type=float, default=0.55)
    p.add_argument("--min-avg-pnl", type=float, default=0.0)
    p.add_argument("--max-drawdown", type=float, default=None)
    p.add_argument("--min-sol", type=float, default=0.5)
    p.add_argument("--max-sol", type=float, default=15.0)
    p.add_argument("--topk", type=int, default=200)
    p.set_defaults(func=cmd_score_select)

    a = ap.parse_args()
    if hasattr(a, "func"): a.func(a)
    else: ap.print_help()

if __name__ == "__main__":
    main()
