import base64, base58
from typing import List, Dict, Any
from .rpc import SolRpc, TOKEN_PROGRAM_ID

def _to_pubkey(b: bytes) -> str:
    return base58.b58encode(b).decode()

def list_token_accounts_by_mint_fast(rpc: SolRpc, mint: str) -> List[Dict[str, Any]]:
    filters = [{"dataSize": 165}, {"memcmp": {"offset": 0, "bytes": mint}}]
    cfg = {"encoding": "base64", "filters": filters, "dataSlice": {"offset": 32, "length": 40}}
    res = rpc.get_program_accounts_raw(TOKEN_PROGRAM_ID, cfg) or []
    out=[]
    for it in res:
        try:
            data_b64 = it["account"]["data"][0]
            raw = base64.b64decode(data_b64)
            owner = _to_pubkey(raw[:32])
            amount = int.from_bytes(raw[32:40], "little", signed=False)
            out.append({"owner": owner, "amount": amount})
        except Exception:
            continue
    return out

def list_token_accounts_by_mint_parsed(rpc: SolRpc, mint: str) -> List[Dict[str, Any]]:
    filters = [{"dataSize": 165}, {"memcmp": {"offset": 0, "bytes": mint}}]
    res = rpc.get_program_accounts(TOKEN_PROGRAM_ID, filters=filters) or []
    out=[]
    for it in res:
        acct = it.get("account") or {}
        data = acct.get("data")
        if isinstance(data, dict):
            info = (data.get("parsed") or {}).get("info") or {}
            amount = int(((info.get("tokenAmount") or {}).get("amount")) or "0")
            owner = info.get("owner")
            out.append({"owner": owner, "amount": amount})
    return out

def list_token_accounts_by_mint(rpc: SolRpc, mint: str) -> List[Dict[str, Any]]:
    try:
        return list_token_accounts_by_mint_fast(rpc, mint)
    except Exception:
        return list_token_accounts_by_mint_parsed(rpc, mint)

def recent_token_owners(rpc: SolRpc, mint: str, topn: int = 3000) -> List[str]:
    tas = list_token_accounts_by_mint(rpc, mint)
    owners, seen = [], set()
    for it in tas:
        if int(it.get("amount", 0)) <= 0:
            continue
        ow = it.get("owner")
        if not ow or ow in seen:
            continue
        seen.add(ow); owners.append(ow)
        if len(owners) >= topn:
            break
    return owners
