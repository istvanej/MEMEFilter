# 推断某 mint 的“上市起点” T0（秒级 Unix time）
# 思路：取若干代表性地址的最早相关交易时间的最小值：
#   - mint 自身签名（若有）
#   - largest accounts 的第一条 ATA 交易时间
#   - 随机若干当前持有者的第一条相关交易时间
from typing import List, Optional
from .rpc import SolRpc
from .solana_spl import list_token_accounts_by_mint
import random

def _sig_time(rpc: SolRpc, signature: str) -> Optional[int]:
    tx = rpc.get_transaction(signature, maxv=0)
    if not tx: return None
    slot = tx.get("slot")
    if slot is None: return None
    t = rpc.get_block_time(slot)
    return t

def estimate_t0(rpc: SolRpc, mint: str, sample_holders: int = 15) -> Optional[int]:
    # (A) mint 地址本身
    t_candidates = []
    try:
        sigs = rpc.get_signatures_for_address(mint, limit=20) or []
        for s in sigs:
            t = _sig_time(rpc, s["signature"])
            if t: t_candidates.append(t)
    except Exception:
        pass

    # (B) largest accounts（通常包含初期注入/团队仓）
    try:
        la = rpc.get_token_largest_accounts(mint).get("value") or []
        for it in la[:10]:
            ata = it.get("address")
            if not ata: continue
            sigs = rpc.get_signatures_for_address(ata, limit=10) or []
            for s in sigs:
                t = _sig_time(rpc, s["signature"])
                if t: t_candidates.append(t)
    except Exception:
        pass

    # (C) 当前持有者抽样
    try:
        tas = list_token_accounts_by_mint(rpc, mint, limit=500)
        owners = [a["owner"] for a in tas]
        owners = random.sample(owners, min(sample_holders, len(owners)))
        for o in owners:
            # 拿 owner 的 ATA tx
            res = rpc.get_token_accounts_by_owner(o, mint)
            for it in (res.get("value") or []):
                ata = it.get("pubkey")
                sigs = rpc.get_signatures_for_address(ata, limit=10) or []
                for s in sigs:
                    t = _sig_time(rpc, s["signature"])
                    if t: t_candidates.append(t)
    except Exception:
        pass

    if not t_candidates: return None
    t0 = min(t_candidates)
    return t0

def time_bucket(ts: int, t0: int) -> str:
    if t0 is None or ts is None: return "unknown"
    dt = ts - t0
    if dt < 0: return "prelaunch"
    h = dt/3600.0
    if h <= 2: return "0-2h"
    if h <= 24: return "2-24h"
    if h <= 72: return "24-72h"
    return ">72h"
