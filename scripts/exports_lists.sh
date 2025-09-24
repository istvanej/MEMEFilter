cat > scripts/export_lists.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
TS=$(date +'%Y%m%d_%H%M%S')
OUT="data/exports"
DB="data/db.sqlite"
mkdir -p "$OUT"

for KIND in WHITE WATCH BLACK; do
  sqlite3 -noheader "$DB" \
    "SELECT addr FROM lists WHERE status='$KIND' ORDER BY updated_at DESC;" \
    > "$OUT/${KIND}_${TS}.txt"
  echo "[OK] $OUT/${KIND}_${TS}.txt"
done

sqlite3 -header -csv "$DB" \
  "SELECT addr,chain,status,reason,updated_at FROM lists ORDER BY status DESC, updated_at DESC;" \
  > "$OUT/lists_${TS}.csv"
echo "[OK] $OUT/lists_${TS}.csv"
SH
chmod +x scripts/export_lists.sh
