#!/usr/bin/env bash
# deploy/update.sh — Voer dit uit op de server na het kopiëren van nieuwe code via scp.
#
# Gebruik:
#   sudo bash /opt/portfoliomanager/deploy/update.sh
#
# Wat het doet:
#   1. Python-dependencies bijwerken (pip install -r requirements.txt)
#   2. Bestandsrechten corrigeren
#   3. Systemd-service herstarten

set -euo pipefail

# ── Configuratie ────────────────────────────────────────────────────────────
APP_DIR="/opt/portfoliomanager"
VENV="$APP_DIR/.venv"
SERVICE_USER="service_portfolio_manager"
SERVICE_NAME="portfoliomanager"

# ── Kleuren ─────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${YELLOW}→${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

# ── Controleer of we als root draaien ────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  err "Dit script moet als root worden uitgevoerd (gebruik sudo)."
  exit 1
fi

# ── Controleer of de app-map bestaat ────────────────────────────────────────
if [[ ! -d "$APP_DIR" ]]; then
  err "App-map '$APP_DIR' niet gevonden."
  exit 1
fi

echo ""
echo "══════════════════════════════════════════════"
echo "  PortfolioManager — update $(date '+%Y-%m-%d %H:%M:%S')"
echo "══════════════════════════════════════════════"
echo ""

# ── 0. Zorg dat rsync beschikbaar is (voor toekomstige deploys) ──────────────
if ! command -v rsync &>/dev/null; then
  info "rsync niet gevonden — wordt eenmalig geïnstalleerd…"
  apt-get install -y -qq rsync
  ok "rsync geïnstalleerd. Volgende deploy gebruikt automatisch rsync."
fi

# ── 1. Python __pycache__ wissen (voorkomt dat oude .pyc bestanden worden gebruikt) ──
info "Python cache wissen…"
find "$APP_DIR" -type d -name "__pycache__" -not -path "$APP_DIR/.venv/*" -exec rm -rf {} + 2>/dev/null || true
find "$APP_DIR" -name "*.pyc" -not -path "$APP_DIR/.venv/*" -delete 2>/dev/null || true
ok "Cache gewist."

# ── 2. Python-dependencies ───────────────────────────────────────────────────
info "Python-dependencies bijwerken…"
sudo -u "$SERVICE_USER" "$VENV/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
ok "Dependencies bijgewerkt."

# ── 3. Bestandsrechten ───────────────────────────────────────────────────────
info "Bestandsrechten corrigeren…"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
# Data-map leesbaar/schrijfbaar voor de service, niet voor anderen
chmod 750 "$APP_DIR/data" 2>/dev/null || true
ok "Rechten gecorrigeerd."

# ── 4. Service herstarten ────────────────────────────────────────────────────
info "Service herstarten…"
systemctl restart "$SERVICE_NAME"

# Wacht even en controleer of de service actief is
sleep 3
if systemctl is-active --quiet "$SERVICE_NAME"; then
  ok "Service '$SERVICE_NAME' draait."
else
  err "Service '$SERVICE_NAME' is niet gestart. Laatste logs:"
  journalctl -u "$SERVICE_NAME" -n 30 --no-pager >&2
  exit 1
fi

echo ""
ok "Update voltooid!"
echo ""
