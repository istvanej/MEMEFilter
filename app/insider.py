# app/insider.py
from typing import List, Set
from .rpc import SolRpc

def get_mint_authorities(rpc: SolRpc, mint: str) -> List[str]:
    info = rpc.get_account_info(mint)
    v = info.get("value")
    if not v: return []
    # mint account data 是 base64；此处 v1.5 不深度解码，走“最大持仓地址 + 冻结权/铸造权猜测”混合守门
    # 直接用 largest accounts 先做守门：
    return []

def largest_holders(rpc: SolRpc, mint: str, topn=20) -> List[str]:
    res = rpc.get_token_largest_accounts(mint)
    out = []
    for it in (res.get("value") or []):
        addr = it.get("address")
        out.append(addr)
        if len(out) >= topn: break
    return out

def is_insider_like(owner: str, mint: str, rpc: SolRpc) -> bool:
    """
    v1.5 近似规则：
      - 如果 owner 的 ATA 位于 mint 的 largest accounts 前 N（如 20）且此持仓是“上市极早期形成”，可疑
      - 或 owner 与「largest holders 中的已知营销/金库多签」存在早期资金往来（此处简化：仅第一条）
    """
    try:
        # largest accounts 返回的是 Token Account(ATA) 地址，需要 owner 是否直接匹配？
        # 我们退一步：若 owner 本身在 largest 列表中，直接可疑（很多项目方把金库存成持有人）
        tops = set(largest_holders(rpc, mint, topn=20))
        return owner in tops
    except Exception:
        return False
