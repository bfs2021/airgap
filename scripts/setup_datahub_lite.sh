#!/usr/bin/env bash
# One-command setup: install Airgap + DataHub Lite, seed a local DataHub with the
# Acme catalog, and import it. No Docker, no cloud — DataHub Lite is a local
# DuckDB-backed DataHub instance. Afterwards:
#
#     ./.venv/bin/airgap audit --source datahub-lite
#
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Creating venv + installing Airgap with DataHub Lite"
python3 -m venv .venv 2>/dev/null || true
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -e '.[datahub-lite]'

echo "==> Generating DataHub metadata from the Acme fixture"
PYTHONWARNINGS=ignore ./.venv/bin/python scripts/seed_datahub_lite.py

echo "==> Ensuring DataHub Lite config (~/.datahubenv)"
if [ ! -f "$HOME/.datahubenv" ]; then
  printf 'gms:\n  server: http://localhost:8080\n  token: '"''"'\nlite:\n  type: duckdb\n  config:\n    file: %s/.datahub/lite/datahub.duckdb\n    read_only: false\n' "$HOME" > "$HOME/.datahubenv"
fi

echo "==> Importing metadata into local DataHub Lite"
PYTHONWARNINGS=ignore ./.venv/bin/datahub lite import --file outputs/acme_mcps.json >/dev/null

echo ""
echo "Done. DataHub Lite now holds the Acme catalog. Audit it with:"
echo "    ./.venv/bin/airgap audit --source datahub-lite"
