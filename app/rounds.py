# 对某“地址 × mint”回放最近交易，生成“回合（Round）”
# Round = 首次净买入后持仓>0 ——> 清仓(或超时)
# 产出：entry_ts, exit_ts, hold_s, buy_qty, sell_qty, net_tokens, pnl_tokens
# 以及：首买发生的相对时间窗（基于 t0）
from typing import Dict, List, Tuple, Optional
from .rpc import SolRpc
from .txscan import guess_atas_for_owner, extract_owner_delta_for_mint
from .t0 import time_bucket
from .price import get_token_price_usd  # 可选，没价源时返回 None

def _tx_time(rpc: SolRpc, tx: dict) -> Optional[int]:
    slot = tx.get("slot")
    if slot is None: return None
    return rpc.get_block_time(slot)

def replay_owner_rounds(rpc: SolRpc, owner: str, mint: str, t0: Optional[int], max_txs=600, timeout_s=24*3600) -> List[Dict]:
    atas = guess_atas_for_owner(rpc, owner, mint)
    if not atas: return []

    # 合并 ATA 的签名，去重，按时间正序回放
    sigs = []
    for ata in atas:
        batch = rpc.get_signatures_for_address(ata, limit=max_txs)
        sigs.extend([s["signature"] for s in (batch or [])])
    sigs = list(dict.fromkeys(sigs))[:max_txs]

    # 拉 tx 并按时间排序（旧到新）
    txs = []
    for sig in sigs:
        tx = rpc.get_transaction(sig, maxv=0)
        if not tx: continue
        ts = _tx_time(rpc, tx)
        if ts is None: continue
        txs.append((ts, tx))
    txs.sort(key=lambda x: x[0])

    rounds = []
    pos = 0  # token 最小单位
    cur = {"entry_ts": None, "buy": 0, "sell": 0, "net": 0}

    for ts, tx in txs:
        d = extract_owner_delta_for_mint(tx, owner, mint)  # token delta: +买入 / -卖出
        if d == 0: 
            # 观察超时？
            if cur["entry_ts"] and (ts - cur["entry_ts"] >= timeout_s) and pos>0:
                # 强制平仓为超时
                cur["exit_ts"] = ts; cur["hold_s"] = cur["exit_ts"] - cur["entry_ts"]
                cur["pnl_tokens"] = -cur["net"]  # 若仍持有，按净额（负债）计，v2.0简化
                cur["bucket"] = time_bucket(cur["entry_ts"], t0)
                rounds.append(cur); cur={"entry_ts":None,"buy":0,"sell":0,"net":0}; pos=0
            continue

        if d > 0:
            # 买入
            if pos == 0 and cur["entry_ts"] is None:
                cur = {"entry_ts": ts, "buy": 0, "sell": 0, "net": 0}
            cur["buy"] += d; cur["net"] += d; pos += d
        else:
            # 卖出
            cur["sell"] += (-d); cur["net"] += d; pos += d  # d<0
            if pos <= 0 and cur["entry_ts"] is not None:
                # 清仓，回合结束
                cur["exit_ts"] = ts
                cur["hold_s"] = cur["exit_ts"] - cur["entry_ts"]
                cur["pnl_tokens"] = cur["sell"] - cur["buy"]  # 仅已实现
                cur["bucket"] = time_bucket(cur["entry_ts"], t0)
                rounds.append(cur)
                cur={"entry_ts":None,"buy":0,"sell":0,"net":0}; pos=0

    # 收尾：若仍持有未清仓且超时
    if cur["entry_ts"] and pos>0:
        cur["exit_ts"] = txs[-1][0]
        cur["hold_s"] = cur["exit_ts"] - cur["entry_ts"]
        cur["pnl_tokens"] = -cur["net"]  # 未实现，按净额计
        cur["bucket"] = time_bucket(cur["entry_ts"], t0)
        rounds.append(cur)

    return rounds

def rounds_with_usd(rpc: SolRpc, owner: str, mint: str, t0: Optional[int], price_base_url: Optional[str], price_key: Optional[str], decimals: int = 9) -> List[Dict]:
    rs = replay_owner_rounds(rpc, owner, mint, t0)
    # token 最小单位 → 标准单位
    scale = 10**decimals
    px = get_token_price_usd(mint, price_base_url, price_key)  # None 则跳过
    out=[]
    for r in rs:
        buy = r["buy"]/scale; sell = r["sell"]/scale; pnl_tok = r["pnl_tokens"]/scale
        rec = dict(r)
        rec["buy_token"] = buy; rec["sell_token"]=sell; rec["pnl_token"]=pnl_tok
        if px is not None:
            rec["pnl_usd"] = pnl_tok * px
        out.append(rec)
    return out
