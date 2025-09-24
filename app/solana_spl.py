# app/solana_spl.py
from typing import List, Dict, Any
from .rpc import SolRpc, TOKEN_PROGRAM_ID

def _get(d: Dict[str, Any], path: List[str], default=None):
    cur = d
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur

def list_token_accounts_by_mint(rpc: SolRpc, mint: str) -> List[Dict[str, Any]]:
    """
    返回 SPL Token Program 下某个 mint 的所有 Token Account（jsonParsed）。
    兼容性处理：如果返回是 base64 数组结构，直接跳过（我们只用 parsed）。
    """
    filters = [
        {"dataSize": 165},                  # SPL Token Account 固定大小
        {"memcmp": {"offset": 0, "bytes": mint}},  # mint 匹配
    ]
    res = rpc.get_program_accounts(TOKEN_PROGRAM_ID, filters=filters) or []
    out = []
    for it in res:
        acct = it.get("account") or {}
        data = acct.get("data")
        # 兼容：jsonParsed 是 dict，base64 是 list；我们只处理 dict
        if isinstance(data, dict):
            parsed = data.get("parsed") or {}
            info = parsed.get("info") or {}
            out.append({
                "pubkey": it.get("pubkey"),
                "owner": info.get("owner"),  # 拥有者（钱包）
                "mint": info.get("mint"),
                "amount": int(_get(info, ["tokenAmount", "amount"], "0")),
                "delegate": info.get("delegate"),
                "isNative": _get(info, ["isNative"], False),
                "state": info.get("state"),
            })
        else:
            # base64 模式：不使用，跳过
            continue
    return out

def recent_token_owners(rpc: SolRpc, mint: str, topn: int = 300) -> List[str]:
    """
    取某 mint 的“当前持有人”候选：
      - 从 Token Accounts（jsonParsed）提取 owner
      - 仅保留 amount>0 的账户
      - 去重（按出现顺序）
      - 截取 topn
    这不是严格的“最近交易者”，但对入口层抓样本足够轻巧稳定。
    """
    tas = list_token_accounts_by_mint(rpc, mint)
    owners: List[str] = []
    seen = set()
    for it in tas:
        if int(it.get("amount", 0)) <= 0:
            continue
        ow = it.get("owner")
        if not ow or ow in seen:
            continue
        seen.add(ow)
        owners.append(ow)
        if len(owners) >= topn:
            break
    return owners
