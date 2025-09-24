# app/txscan.py
from typing import List, Tuple, Optional
from .rpc import SolRpc
from .db  import add_candidates

SYSTEM_PROGRAM = "11111111111111111111111111111111"

def extract_owner_delta_for_mint(tx: dict, owner: str, mint: str) -> int:
    """
    读取 transaction.meta 的 pre/postTokenBalances，计算该 owner 在此 mint 的持仓变化（raw amount）
    """
    meta = tx.get("meta") or {}
    pre = meta.get("preTokenBalances") or []
    post = meta.get("postTokenBalances") or []

    def key(b): return (b.get("owner"), b.get("mint"))
    pre_map = { key(b): int(b.get("uiTokenAmount",{}).get("amount","0")) for b in pre }
    post_map= { key(b): int(b.get("uiTokenAmount",{}).get("amount","0")) for b in post }
    a0 = pre_map.get((owner, mint), 0)
    a1 = post_map.get((owner, mint), 0)
    return a1 - a0

def guess_atas_for_owner(rpc: SolRpc, owner: str, mint: str) -> List[str]:
    """
    用 getTokenAccountsByOwner(owner, mint) 猜测该 owner 的 ATA 列表（通常一个）
    """
    res = rpc.get_token_accounts_by_owner(owner, mint)
    out = []
    for it in (res.get("value") or []):
        pubkey = it.get("pubkey")
        if pubkey: out.append(pubkey)
    return out

def replay_recent_for_owner(rpc: SolRpc, owner: str, mint: str, max_txs=400) -> Tuple[int,int]:
    """
    旧版“全量最近交易回放”：对该 owner 的 ATA 取签名后逐条 getTransaction 计算净变动
    返回: (net_delta_raw, first_buy_idx or -1)
    """
    atas = guess_atas_for_owner(rpc, owner, mint)
    if not atas:
        return (0, -1)

    sigs: List[str] = []
    for ata in atas:
        batch = rpc.get_signatures_for_address(ata, limit=max_txs) or []
        sigs.extend([s.get("signature") for s in batch if s.get("signature")])
    # 去重 + 限制
    sigs = list(dict.fromkeys(sigs))[:max_txs]

    net = 0
    first_buy_idx = -1
    for idx, sig in enumerate(sigs):
        tx = rpc.get_transaction(sig, maxv=0)
        if not tx: 
            continue
        d = extract_owner_delta_for_mint(tx, owner, mint)
        if d > 0 and first_buy_idx < 0:
            first_buy_idx = idx
        net += d
    return (net, first_buy_idx)

def replay_owner_windowed(rpc: SolRpc, owner: str, mint: str, t0: Optional[int], window_h: float = 2.0, max_sigs_per_ata: int = 600) -> Tuple[int,int]:
    """
    时间窗优化版回放：
      先用 getSignaturesForAddress 返回的 blockTime 过滤在 [t0, t0+window] 的签名，
      再仅对这些签名 getTransaction，显著减少 RPC。
    返回: (net_delta_raw_in_window, first_buy_idx_in_window or -1)
    """
    if t0 is None:
        return (0, -1)

    atas = guess_atas_for_owner(rpc, owner, mint)
    if not atas:
        return (0, -1)

    t1 = t0 + int(window_h * 3600)

    # 收集所有 ATA 的签名 + blockTime
    sig_items: List[Tuple[int, str]] = []  # (blockTime, signature)
    for ata in atas:
        arr = rpc.get_signatures_for_address(ata, limit=max_sigs_per_ata) or []
        for s in arr:
            bt = s.get("blockTime")
            sig = s.get("signature")
            if bt is None or not sig:
                continue
            if bt < t0 or bt > t1:
                continue  # 窗外直接丢弃——关键优化
            sig_items.append((bt, sig))

    # 按时间升序回放
    sig_items.sort(key=lambda x: x[0])

    net = 0
    first_buy_idx = -1
    for idx, (_, sig) in enumerate(sig_items):
        tx = rpc.get_transaction(sig, maxv=0)
        if not tx:
            continue
        d = extract_owner_delta_for_mint(tx, owner, mint)
        if d > 0 and first_buy_idx < 0:
            first_buy_idx = idx
        net += d

    return (net, first_buy_idx)

def find_early_buyers(rpc: SolRpc, mint: str, owners: List[str], topn=80) -> List[str]:
    """
    简单版早期买家识别：对 owners 走“最近回放”，选出净买入且出现早的前 topn。
    （若你在上层已有 t0，可优先用 replay_owner_windowed 来调用）
    """
    scored: List[Tuple[str,int]] = []
    for o in owners:
        try:
            net, fb = replay_recent_for_owner(rpc, o, mint, max_txs=300)
            if net > 0 and fb >= 0:
                scored.append((o, fb))
        except Exception:
            continue
    scored.sort(key=lambda x: x[1])
    return [o for (o,_) in scored[:topn]]
