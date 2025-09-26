import os, time, math, requests

def _pick_rpc(chain: str):
    # 支持多环境名 + 多端点，逗号/分号分隔
    KEYS = {
        "bsc":  ["BSC_RPC_URLS","BSC_RPC_URL","BSC_RPC","BSC_HTTP_URL","BSCRPCURL"],
        "base": ["BASE_RPC_URLS","BASE_RPC_URL","BASE_RPC","BASE_HTTP_URL","BASERPCURL"],
    }[chain]
    urls=[]
    for k in KEYS:
        v=os.environ.get(k,"").strip()
        if not v: continue
        for u in v.replace(";",",").split(","):
            u=u.strip()
            if u: urls.append(u)
    # 去重
    seen=set(); out=[]
    for u in urls:
        if u not in seen:
            seen.add(u); out.append(u)
    if not out: raise ValueError(f"no RPC url for {chain}")
    return out[0]  # 先用第一个

class EvmRpc:
    def __init__(self, chain: str):
        chain = chain.lower()
        if chain not in ("bsc","base"):
            raise ValueError(f"unsupported evm chain: {chain}")
        self.chain = chain
        self.url   = _pick_rpc(chain)
        self.timeout = 15

    def call(self, method: str, params: list):
        r = requests.post(self.url, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=self.timeout)
        r.raise_for_status()  # 若 400/500 会直接抛
        j = r.json()
        if "error" in j:
            raise RuntimeError(f"rpc error: {j['error']}")
        return j.get("result")

    # 基础方法
    def block_number(self) -> int:
        x = self.call("eth_blockNumber", [])
        return int(x,16) if isinstance(x,str) else int(x)

    def get_balance(self, addr: str) -> float:
        w = self.call("eth_getBalance", [addr, "latest"])
        wei = int(w,16) if isinstance(w,str) else int(w)
        # 返回本地币（BNB/ETH）单位
        return wei / 1e18

    # 原始一次性 getLogs（可能被 provider 拒绝）
    def get_logs(self, from_block: int, to_block: int, address: str, topics: list, timeout=None):
        p=[{
            "fromBlock": hex(from_block),
            "toBlock":   hex(to_block),
            "address": address,
            "topics": topics
        }]
        return self.call("eth_getLogs", p)

    # 安全分片版：自动按区间切块，出错降块宽重试
    def get_logs_chunked(self, from_block: int, to_block: int, address: str, topics: list,
                         max_span: int = 4000, min_span: int = 256, backoff: float=0.3):
        if to_block < from_block:
            return []
        res=[]
        start = from_block
        span = max_span
        while start <= to_block:
            end = min(start + span - 1, to_block)
            try:
                logs = self.get_logs(start, end, address, topics)
                if isinstance(logs, list):
                    res.extend(logs)
                else:
                    # 不应出现，但做兜底
                    time.sleep(backoff)
                # 成功了，尝试扩张一点（自适应）
                start = end + 1
                if span < max_span:
                    span = min(max_span, span*2)
            except requests.HTTPError as e:
                # provider 400/timeout：缩小块宽重试
                if span <= min_span:
                    # 块宽已缩到底，跳过这个区间防死锁
                    start = end + 1
                else:
                    span = max(min_span, span // 2)
                time.sleep(backoff)
            except Exception:
                time.sleep(backoff)
                start = end + 1
        return res
