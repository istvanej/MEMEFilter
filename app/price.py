import os, requests
from dotenv import load_dotenv
load_dotenv()

BIRD=os.getenv("BIRD_EYE_API","").rstrip("/")
KEY =os.getenv("BIRD_EYE_KEY","")

def get_token_price_usd(mint: str, base_url: str = None, key: str = None):
    base = base_url or BIRD
    api  = key or KEY
    if not base:
        return None
    try:
        # 轻价源（示例）：/public/price?address=<mint>&chain=solana
        url=f"{base}/public/price?address={mint}&chain=solana"
        headers={}
        if api: headers["X-API-KEY"]=api
        r=requests.get(url, headers=headers, timeout=8)
        r.raise_for_status()
        j=r.json()
        # 不同供应商结构不同，容错提取
        for k in ("price","value","data"):
            if k in j:
                v=j[k]
                if isinstance(v, dict):
                    for kk in ("price","value","usd"):
                        if kk in v: return float(v[kk])
                else:
                    try: return float(v)
                    except: pass
        return None
    except Exception:
        return None
