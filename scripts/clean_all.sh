#!/usr/bin/env bash
set -e
rm -f data/*.sqlite
rm -f data/exports/*.txt data/exports/*.csv
rm -f logs/*.log
echo "[OK] Cleaned all DB/exports/logs"
