from .db import upsert_pool, add_candidates
from .rpc import SolRpc
from .solana_spl import recent_token_owners
from .txscan import find_early_buyers

def import_token(chain: str, mint: str, amm="raydium", base="USDC", quote="SOL", source="manual"):
    """
    把 token/mint 写进 pools 表（若已存在则更新 last_seen）
    """
    upsert_pool(chain, mint, amm, base, quote, source)

def scan_candidates_for_mint(chain: str, mint: str, rpc: SolRpc, topn=200, mode="early"):
    """
    入口层扫描候选地址：
      - mode='holders'：基于 Token Accounts 的当前持有人（amount>0）
      - mode='early'  ：基于 ATA 交易回放选“早期净买入者”
    """
    if mode == "holders":
        owners = recent_token_owners(rpc, mint, topn=topn)
        add_candidates(chain, mint, owners, source="mint_scan")
        return owners
    elif mode == "early":
        base = recent_token_owners(rpc, mint, topn=topn*3)  # 扩一圈基础样本
        early = find_early_buyers(rpc, mint, base, topn=min(100, topn))
        add_candidates(chain, mint, early, source="early_buyers")
        return early
    else:
        raise ValueError("mode must be 'holders' or 'early'")
