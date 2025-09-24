import os, json, requests

HDR = {"Content-Type": "application/json"}

# SPL Token Program (mainnet)
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

class SolRpc:
    def __init__(self, url=None, timeout=15):
        self.url = url or os.environ.get("SOLANA_RPC_URL")
        if not self.url:
            raise ValueError("SOLANA_RPC_URL not set in env or args")
        self.timeout = timeout

    def call(self, method: str, params: list):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        r = requests.post(self.url, headers=HDR, data=json.dumps(payload), timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("result")

    def get_token_supply(self, mint: str):
        return self.call("getTokenSupply", [mint])

    def get_account_info(self, pubkey: str):
        return self.call("getAccountInfo", [pubkey, {"encoding": "jsonParsed"}])

    def get_token_accounts_by_owner(self, owner: str, mint: str):
        return self.call("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])

    def get_signatures_for_address(self, addr: str, limit=1000):
        return self.call("getSignaturesForAddress", [addr, {"limit": limit}])

    def get_transaction(self, sig: str, maxv=0):
        return self.call("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": maxv}])

    def get_program_accounts(self, program_id: str, filters=None):
        cfg = {"encoding": "jsonParsed"}
        if filters:
            cfg["filters"] = filters
        return self.call("getProgramAccounts", [program_id, cfg])

    def get_block_time(self, slot: int):
        return self.call("getBlockTime", [slot])

    def get_balance(self, pubkey: str):
        # returns lamports
        return self.call("getBalance", [pubkey, {"commitment": "confirmed"}])
