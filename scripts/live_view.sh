cat > scripts/live_view.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
DB="data/db.sqlite"
watch -n 5 "sqlite3 -header -column $DB \"
SELECT datetime(first_seen,'localtime') AS seen,
       chain,
       substr(token_address,1,10)||'…' AS token,
       addr,
       COALESCE(status,'CANDIDATE') AS status,
       COALESCE(reason,'') AS reason
FROM view_addresses
ORDER BY status DESC, seen DESC
LIMIT 200;\""
SH
chmod +x scripts/live_view.sh
