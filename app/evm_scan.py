from typing import List, Tuple
import os, re

from .evm_rpc import EvmRpc

# ERC20 Transfer(address indexed from, address indexed to, uint256)
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

AVG_BLOCK_TIME = {
    "bsc": 3.0,   # 约 3s
    "base": 2.0,  # 约 2s
}

def _topic_addr(addr: str) -> str:
    # 32字节右对齐：0x000... + 20B 地址
    return "0x" + ("0"*24) + addr.lower()[2:]

def holders_recent(chain: str, rpc: EvmRpc, token: str, lookback_blocks=120_000, step=4000, topn=800) -> List[str]:
    tip = rpc.block_number()
    lo  = max(0, tip - lookback_blocks)
    addrs=set()
    start = lo
    while start <= tip and len(addrs) < topn:
        end = min(start + step - 1, tip)
        logs = rpc.get_logs_chunked(start, end, token, [TRANSFER_TOPIC])
        for it in logs:
            topics = it.get("topics") or []
            if len(topics) < 3: continue
            # topics[1]=from, topics[2]=to
            for t in topics[1:3]:
                if isinstance(t,str) and len(t)==66 and t.startswith("0x"):
                    a = "0x"+t[-40:]
                    addrs.add(a)
                    if len(addrs) >= topn: break
        start = end + 1
    return list(addrs)[:topn]

def estimate_t0_by_first_transfer(rpc: EvmRpc, token: str, lookback=200_000, chunk=4000) -> Tuple[int,int]:
    """
    从最早的一条 Transfer 日志估计 T0 区块。
    使用递增小块扫描（分片），避免大跨度查询触发 400。
    返回 (bn0, bn0)；若找不到，返回 (tip, tip)。
    """
    tip = rpc.block_number()
    lo  = max(0, tip - lookback)
    first_bn = None
    start = lo
    while start <= tip:
        end = min(start + chunk - 1, tip)
        logs = rpc.get_logs_chunked(start, end, token, [TRANSFER_TOPIC])
        if logs:
            # 找到当前块段最早的一条
            bn = min(int(x["blockNumber"],16) for x in logs if isinstance(x.get("blockNumber"), str))
            first_bn = bn
            break
        start = end + 1
    if first_bn is None:
        return (tip, tip)
    return (first_bn, first_bn)

def early_buyers(chain: str, rpc: EvmRpc, token: str, owners: List[str], window_h: float=1.0) -> List[str]:
    """
    用 T0 附近窗口统计“在窗口内首次接收该 token”的地址作为早买家。
    不逐个 owner 回放交易，而是按 receiver 过滤 topics[2]，极大降低 RPC 压力。
    """
    bn0, _ = estimate_t0_by_first_transfer(rpc, token)
    # 窗口换算成区块数
    sec = window_h * 3600.0
    avg = AVG_BLOCK_TIME.get(chain, 3.0)
    window_blocks = max(2, int(sec/avg))

    tip = rpc.block_number()
    hi  = min(tip, bn0 + window_blocks)

    # 先扫窗口内所有 Transfer 日志
    logs = rpc.get_logs_chunked(bn0, hi, token, [TRANSFER_TOPIC])

    # 只统计窗口期首次接收的人
    first_seen = {}
    for it in logs:
        topics = it.get("topics") or []
        if len(topics) < 3: continue
        to_topic = topics[2]
        if not (isinstance(to_topic,str) and len(to_topic)==66): continue
        addr = "0x"+to_topic[-40:]
        bn   = int(it["blockNumber"],16)
        if addr not in first_seen or bn < first_seen[addr]:
            first_seen[addr] = bn

    # 与候选 owners 求交集（如果 owners 为空，则把窗口首次接收者全返回）
    if owners:
        base = set(a.lower() for a in owners)
        hits = [a for a in first_seen.keys() if a.lower() in base]
    else:
        hits = list(first_seen.keys())

    # 返回最多 200 个
    hits.sort(key=lambda a: first_seen[a])
    return hits[:200]
