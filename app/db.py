import os, sqlite3
from contextlib import contextmanager

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "db.sqlite"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS pools (
  pool_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  chain         TEXT NOT NULL,
  token_address TEXT NOT NULL,
  amm           TEXT,
  base_token    TEXT,
  quote_token   TEXT,
  tvl_usd       REAL,
  source        TEXT,
  first_seen    DATETIME DEFAULT CURRENT_TIMESTAMP,
  last_seen     DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(chain, token_address)
);

CREATE TABLE IF NOT EXISTS candidate_addrs (
  addr           TEXT NOT NULL,
  token_address  TEXT NOT NULL,
  chain          TEXT NOT NULL,
  first_seen     DATETIME DEFAULT CURRENT_TIMESTAMP,
  last_seen      DATETIME DEFAULT CURRENT_TIMESTAMP,
  source         TEXT,
  PRIMARY KEY (addr, token_address, chain)
);

CREATE TABLE IF NOT EXISTS roles_cache (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  subject        TEXT NOT NULL,
  chain          TEXT NOT NULL,
  role           TEXT NOT NULL,
  how_detected   TEXT,
  first_seen     DATETIME DEFAULT CURRENT_TIMESTAMP,
  last_seen      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lists (
  addr           TEXT NOT NULL,
  chain          TEXT NOT NULL,
  status         TEXT NOT NULL, -- WHITE / WATCH / BLACK
  reason         TEXT,
  updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (addr, chain)
);

CREATE TABLE IF NOT EXISTS addr_tags (
  addr           TEXT NOT NULL,
  chain          TEXT NOT NULL,
  tag            TEXT NOT NULL,
  updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (addr, chain, tag)
);

CREATE VIEW IF NOT EXISTS view_addresses AS
SELECT
  c.addr, c.chain, c.token_address,
  COALESCE(l.status, 'CANDIDATE') AS status,
  COALESCE(l.reason, '') AS reason,
  c.first_seen, c.last_seen
FROM candidate_addrs c
LEFT JOIN lists l ON l.addr = c.addr AND l.chain = c.chain;
"""

@contextmanager
def conn():
    # 确保 data 目录存在
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_needed = not os.path.exists(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    try:
        if init_needed:
            con.executescript(SCHEMA)
            con.commit()
        else:
            # 保险起见，每次也确保 schema 存在（幂等）
            con.executescript(SCHEMA)
            con.commit()
        yield con
    finally:
        con.close()

def upsert_pool(chain, mint, amm=None, base=None, quote=None, source="manual"):
    with conn() as c:
        c.execute("""
        INSERT INTO pools(chain, token_address, amm, base_token, quote_token, source)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(chain, token_address) DO UPDATE SET last_seen=CURRENT_TIMESTAMP;
        """, (chain, mint, amm, base, quote, source))
        c.commit()

def add_candidates(chain, mint, addrs, source="mint_scan"):
    with conn() as c:
        for a in addrs:
            c.execute("""
            INSERT OR IGNORE INTO candidate_addrs(addr, token_address, chain, source)
            VALUES(?,?,?,?)
            """, (a, mint, chain, source))
        c.commit()

def set_list(addr, chain, status, reason=""):
    with conn() as c:
        c.execute("""
        INSERT INTO lists(addr, chain, status, reason, updated_at)
        VALUES(?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(addr, chain) DO UPDATE SET status=?, reason=?, updated_at=CURRENT_TIMESTAMP;
        """, (addr, chain, status, reason, status, reason))
        c.commit()

def fetch_candidates(limit=500):
    with conn() as c:
        cur = c.execute("""
        SELECT addr, chain, token_address FROM view_addresses
        WHERE status IN ('CANDIDATE','WATCH')
        ORDER BY first_seen DESC
        LIMIT ?;
        """, (limit,))
        return cur.fetchall()
