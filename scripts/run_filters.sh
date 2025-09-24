#!/usr/bin/env bash
set -euo pipefail
python -m app.cli soft-filter --limit 800
python -m app.cli hard-verify --limit 400
