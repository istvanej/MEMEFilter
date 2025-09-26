import os, re, requests, math, binascii

# ---------- 读取环境：多键名 & 多端点 ----------
def get_rpc_list(chain_key: str):
    env_keys = {
        "bsc":  ["BSC_RPC_URLS","BSC_RPC_URL","BSC_RPC","BSC_HTTP_URL","BSCRPCURL"],
        "base": ["BASE_RPC_URLS","BASE_RPC_URL","BASE_RPC","BASE_HTTP_URL","BASERPCURL"],
    }[chain_key]
    urls=[]
    for k in env_keys:
        v=os.environ.get(k,"").strip()
        if not v: continue
        for u in v.replace(";",",").split(","):
            u=u.strip()
            if u: urls.append(u)
    # 去重保持顺序
    seen=set(); out=[]
    for u in urls:
        if u not in seen:
            seen.add(u); out.append(u)
    return out

CHAIN_HINT   =(os.environ.get("CHAIN_HINT","") or "").lower().strip()
CHAIN_DEFAULT=(os.environ.get("CHAIN_DEFAULT","bsc") or "bsc").lower().strip()

def is_evm(a: str) -> bool:
    return a.startswith("0x") and len(a)==42 and re.fullmatch(r"0x[0-9a-fA-F]{40}", a) is not None

def rpc_call(rpc_url: str, method: str, params: list, timeout=8):
    try:
        r = requests.post(rpc_url, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        if "error" in j: return None
        return j.get("result")
    except Exception:
        return None

def get_tip(rpc_url: str) -> int:
    x = rpc_call(rpc_url, "eth_blockNumber", [])
    return int(x, 16) if x else 0

def get_code_exists(rpc_url: str, addr: str) -> bool:
    x = rpc_call(rpc_url, "eth_getCode", [addr, "latest"])
    return isinstance(x, str) and x.startswith("0x") and len(x) > 2

def eth_call(rpc_url: str, to: str, data: str):
    return rpc_call(rpc_url, "eth_call", [{"to": to, "data": data}, "latest"])

def is_hex32_ok(x: str) -> bool:
    return isinstance(x, str) and x.startswith("0x") and len(x) >= 66  # 32 字节

def parse_uint(hexstr: str) -> int:
    if not is_hex32_ok(hexstr): return 0
    try: return int(hexstr, 16)
    except Exception: return 0

def parse_symbol(hexstr: str) -> str:
    if not isinstance(hexstr, str) or not hexstr.startswith("0x") or len(hexstr) < 4: return ""
    h = hexstr[2:]
    try:
        raw = binascii.unhexlify(h)
        s = raw.decode(errors="ignore").strip("\x00")
        s = "".join(ch for ch in s if 32 <= ord(ch) <= 126)
        return s[:16]
    except Exception:
        return ""

def probe_erc20_strict(rpc_url: str, token: str, require_code=True):
    if not rpc_url:
        return (False, 0, -1, "", {"reason": "no_rpc"})
    code_ok = get_code_exists(rpc_url, token)
    dec_hex = eth_call(rpc_url, token, "0x313ce567")  # decimals()
    ts_hex  = eth_call(rpc_url, token, "0x18160ddd")  # totalSupply()
    sym_hex = eth_call(rpc_url, token, "0x95d89b41")  # symbol()

    dec_ok  = is_hex32_ok(dec_hex)
    ts_ok   = is_hex32_ok(ts_hex)

    dec = parse_uint(dec_hex) if dec_ok else -1
    ts  = parse_uint(ts_hex)  if ts_ok  else 0
    sym = parse_symbol(sym_hex)

    erc20_ok = (not require_code or code_ok) and ((dec_ok and 0 <= dec <= 36) or ts_ok)

    details = {
        "code_ok": code_ok,
        "dec_hex_len": len(dec_hex) if isinstance(dec_hex,str) else 0,
        "ts_hex_len": len(ts_hex) if isinstance(ts_hex,str) else 0,
        "sym_hex_len": len(sym_hex) if isinstance(sym_hex,str) else 0
    }
    return (erc20_ok, ts, dec, sym, details)

def count_transfers(rpc_url: str, addr: str, tip: int, windows=(200_000, 100_000, 50_000, 10_000)) -> tuple[int, int]:
    if tip <= 0: 
        return (-1, 0)
    topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    for w in windows:
        from_blk = max(0, tip - w)
        p = [{
            "fromBlock": hex(from_blk),
            "toBlock":   "latest",
            "address": addr,
            "topics": [topic]
        }]
        res = rpc_call(rpc_url, "eth_getLogs", p, timeout=10)
        if isinstance(res, list):
            return (len(res), w)
    return (-1, 0)

def try_chain(chain_name: str, token: str):
    # 轮询该链的所有备选 RPC，选一个“可用”的做探测
    urls = get_rpc_list(chain_name)
    last = dict(name=chain_name, url="", tip=0, erc20_ok=False, totalSupply=0, decimals=-1, nlogs=-1, code_ok=False, score=-999)
    for u in urls or [""]:
        tip = get_tip(u) if u else 0
        erc20_ok, ts, dec, sym, d = probe_erc20_strict(u, token, require_code=True) if tip>0 else (False,0,-1,"",{"code_ok":False,"dec_hex_len":0,"ts_hex_len":0})
        nlogs, used_w = count_transfers(u, token, tip)
        score = 0
        if tip <= 0: score -= 100
        if erc20_ok: score += 30
        if ts > 0:   score += 5
        if 0 <= dec <= 36: score += 3
        if nlogs > 0:
            score += 10 + min(5, int(__import__("math").log10(nlogs+1)*5))
        elif nlogs == -1:
            score -= 1
        print(f"[detect] {chain_name}: rpc={u[:60]}... tip={tip} erc20_ok={erc20_ok} (code_ok={d['code_ok']} dec_len={d.get('dec_hex_len',0)} ts_len={d.get('ts_hex_len',0)}) dec={dec} ts={ts} nlogs={nlogs}")
        cur = dict(name=chain_name, url=u, tip=tip, erc20_ok=erc20_ok, totalSupply=ts, decimals=dec, nlogs=nlogs, code_ok=d["code_ok"] if tip>0 else False, score=score)
        # 选择该链里“最好”的一个端点
        if cur["score"] > last["score"]:
            last = cur
    return last

def choose_chain(addr: str) -> str:
    if CHAIN_HINT in ("sol","bsc","base"):
        print(f"[detect] CHAIN_HINT={CHAIN_HINT} -> forced")
        return CHAIN_HINT
    if not addr or not is_evm(addr):
        print("[detect] non-EVM address -> sol")
        return "sol"

    cand = []
    if get_rpc_list("bsc"):  cand.append("bsc")
    if get_rpc_list("base"): cand.append("base")
    if not cand:
        print("[detect] no EVM RPC set, fallback to CHAIN_DEFAULT")
        return CHAIN_DEFAULT

    b = try_chain("bsc", addr)  if "bsc"  in cand else None
    a = try_chain("base", addr) if "base" in cand else None
    scored = [x for x in (b,a) if x]

    # 以“正面信号个数”作为首要决策（erc20_ok / nlogs>0 / code_ok）
    for x in scored:
        x["signals"] = int(bool(x["erc20_ok"])) + int(x["nlogs"]>0) + int(bool(x["code_ok"]))

    scored.sort(key=lambda x: (x["signals"], x["score"], x["tip"], x["name"]=="bsc"), reverse=True)
    chosen = scored[0]["name"]

    # 若所有链 signals 都为 0，则按 CHAIN_DEFAULT 回退
    if scored[0]["signals"] == 0:
        print(f"[detect] no positive signals on both chains -> fallback {CHAIN_DEFAULT}")
        chosen = CHAIN_DEFAULT

    print(f"[detect] summary: {scored} -> chosen={chosen}")
    return chosen

def main():
    import sys
    addr = (os.environ.get("TOKEN_SH","") or (sys.argv[1] if len(sys.argv)>=2 else "")).strip()
    chain = choose_chain(addr)
    print(chain)  # 最后一行只输出链名

if __name__ == "__main__":
    main()
