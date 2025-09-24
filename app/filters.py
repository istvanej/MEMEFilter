# app/filters.py
import time
from datetime import datetime
from typing import Tuple
from .db import fetch_candidates, set_list, conn
from .rpc import SolRpc, TOKEN_PROGRAM_ID
from .insider import is_insider_like

SYSTEM_PROGRAM = "11111111111111111111111111111111"
KNOWN_PROGRAM_IDS = set([TOKEN_PROGRAM_ID])  # 可持续补充

def _ts():
    return datetime.now().strftime("%H:%M:%S")

def _log(*args, flush=True):
    print(f"[{_ts()}]", *args, flush=flush)

def is_program_like(addr: str) -> bool:
    # v2: 先只拦已知 ProgramID；后续可把常见 AMM/DEX 程序加入 KNOWN_PROGRAM_IDS
    return addr in KNOWN_PROGRAM_IDS or addr == SYSTEM_PROGRAM

def soft_filter(rpc: SolRpc, batch_limit: int = 300, verbose: bool = False) -> Tuple[int,int,int]:
    """
    软过滤：把明显程序/系统角色踢黑，其余先入 WATCH 等待硬核校验。
    日志：verbose=True 打印逐条；否则每 25 条汇报一次进度。
    """
    cands = fetch_candidates(limit=batch_limit)
    total = len(cands)
    _log(f"[SOFT] start: candidates={total} limit={batch_limit}")

    white=watch=black=0
    for i, (addr, chain, mint) in enumerate(cands, 1):
        if is_program_like(addr):
            set_list(addr, chain, "BLACK", "known_program_or_system")
            black += 1
            if verbose:
                _log(f"[SOFT][BLACK] {addr} chain={chain} mint={mint[:8]}… reason=known_program_or_system")
        else:
            set_list(addr, chain, "WATCH", "pending_verify")
            watch += 1
            if verbose:
                _log(f"[SOFT][WATCH] {addr} chain={chain} mint={mint[:8]}… reason=pending_verify")
        if not verbose and (i % 25 == 0 or i == total):
            _log(f"[SOFT] progress {i}/{total} W={white} Wa={watch} B={black}")
    _log(f"[SOFT] done: W={white} Wa={watch} B={black}")
    return white, watch, black

def hard_verify(rpc: SolRpc, batch_limit: int = 200, verbose: bool = False, sleep_ms: int = 0) -> Tuple[int,int,int]:
    """
    硬过滤（轻量版）：对 WATCH/CANDIDATE 逐个 getAccountInfo：
      - executable=False 且 owner=SystemProgram → 近似 EOA
          - 再做 Insider 守门：命中 → BLACK；否则 → WHITE
      - 其它 owner 或可执行 → BLACK
    日志：verbose=True 逐条打印分类结果；否则每 20 条汇报一次。
    速率：sleep_ms>0 则每条间隔，避免打爆 RPC。
    """
    with conn() as c:
        cur = c.execute("""
        SELECT DISTINCT c.addr, c.chain, c.token_address
        FROM view_addresses c
        WHERE c.status IN ('WATCH','CANDIDATE')
        ORDER BY c.first_seen DESC
        LIMIT ?;""", (batch_limit,))
        rows = cur.fetchall()

    total = len(rows)
    _log(f"[HARD] start: rows={total} limit={batch_limit} sleep_ms={sleep_ms}")

    white=watch=black=0
    for i, (addr, chain, mint) in enumerate(rows, 1):
        try:
            info = rpc.get_account_info(addr)
            v = info.get("value")
            if not v:
                set_list(addr, chain, "WATCH", "no_account_info")
                watch += 1
                if verbose: _log(f"[HARD][WATCH] {addr} reason=no_account_info")
            else:
                executable = v.get("executable", False)
                owner = v.get("owner", "")
                if (executable is False) and (owner == SYSTEM_PROGRAM):
                    # Insider 守门
                    if is_insider_like(addr, mint, rpc):
                        set_list(addr, chain, "BLACK", "insider_like_largest")
                        black += 1
                        if verbose: _log(f"[HARD][BLACK] {addr} reason=insider_like_largest mint={mint[:8]}…")
                    else:
                        set_list(addr, chain, "WHITE", "eoalike_not_insider")
                        white += 1
                        if verbose: _log(f"[HARD][WHITE] {addr} reason=eoalike_not_insider")
                else:
                    set_list(addr, chain, "BLACK", f"non_system_owner:{owner}")
                    black += 1
                    if verbose: _log(f"[HARD][BLACK] {addr} reason=non_system_owner owner={owner}")
        except KeyboardInterrupt:
            _log("[HARD] interrupted by user")
            break
        except Exception as e:
            set_list(addr, chain, "WATCH", "rpc_error_retry")
            watch += 1
            if verbose: _log(f"[HARD][WATCH] {addr} reason=rpc_error_retry err={e}")
        finally:
            if not verbose and (i % 20 == 0 or i == total):
                _log(f"[HARD] progress {i}/{total} W={white} Wa={watch} B={black}")
            if sleep_ms > 0:
                time.sleep(sleep_ms/1000.0)

    _log(f"[HARD] done: W={white} Wa={watch} B={black}")
    return white, watch, black
