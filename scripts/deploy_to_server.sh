#!/usr/bin/env bash
# scripts/deploy_to_server.sh — Kopieer de projectmap naar de server en voer het update-script uit.
#
# Gebruik:
#   bash scripts/deploy_to_server.sh [server]
#
# Voorbeelden:
#   bash scripts/deploy_to_server.sh                     # gebruikt PM_SERVER uit omgeving
#   bash scripts/deploy_to_server.sh root@YOUR_SERVER
#
# Stel de server in als omgevingsvariabele om het argument weg te laten:
#   export PM_SERVER=root@YOUR_SERVER

set -euo pipefail

# ── Configuratie ─────────────────────────────────────────────────────────────
SERVER="${1:-${PM_SERVER:-}}"
REMOTE_DIR="/opt/portfoliomanager"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# ── Kleuren ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${YELLOW}→${NC} $*"; }
warn() { echo -e "${RED}!${NC} $*"; }

if [[ -z "$SERVER" ]]; then
  echo "Gebruik: $0 root@YOUR_SERVER" >&2
  echo "Of stel PM_SERVER=root@YOUR_SERVER in." >&2
  exit 2
fi

echo ""
echo "══════════════════════════════════════════════"
echo "  PortfolioManager — deploy naar $SERVER"
echo "══════════════════════════════════════════════"
echo ""

# ── 1. Kopieer bestanden naar server ─────────────────────────────────────────
info "Bestanden kopiëren naar $SERVER:$REMOTE_DIR …"

# Gebruik rsync als het beschikbaar is op de server (sneller, incrementeel).
# Anders: tar + ssh pipe (werkt altijd, geen extra software nodig).
RSYNC_LOCAL="$(command -v rsync 2>/dev/null || true)"
RSYNC_REMOTE="$(ssh "$SERVER" 'command -v rsync 2>/dev/null || echo ""' 2>/dev/null || true)"

if [[ -n "$RSYNC_LOCAL" && -n "$RSYNC_REMOTE" ]]; then
  info "rsync beschikbaar op beide kanten — gebruikt rsync."
  "$RSYNC_LOCAL" -az --delete \
    --exclude='.venv/' \
    --exclude='data/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache/' \
    --exclude='.DS_Store' \
    --exclude='*.egg-info/' \
    "$LOCAL_DIR/" \
    "$SERVER:$REMOTE_DIR/"
else
  warn "rsync niet gevonden op de server — gebruikt tar+ssh (langzamer maar altijd werkend)."
  warn "Installeer rsync op de server voor snellere deploys: apt install -y rsync"
  # tar+ssh: pakt alle bestanden lokaal in, stuurt ze via ssh, pakt ze uit op de server
  tar -czf - \
    --exclude='./.venv' \
    --exclude='./data' \
    --exclude='./__pycache__' \
    --exclude='./*.pyc' \
    --exclude='./.pytest_cache' \
    --exclude='./.DS_Store' \
    --exclude='./*.egg-info' \
    -C "$LOCAL_DIR" . \
  | ssh "$SERVER" "mkdir -p $REMOTE_DIR && cd $REMOTE_DIR && tar -xzf -"
fi

ok "Bestanden gekopieerd."

# ── 2. Voer het update-script uit op de server ───────────────────────────────
info "Update-script uitvoeren op server…"
ssh "$SERVER" "bash $REMOTE_DIR/deploy/update.sh"

echo ""
ok "Deploy klaar!"
echo ""
