#!/usr/bin/env bash
# deploy/update.sh — Voer dit uit op de server na het kopiëren van nieuwe code via scp.
#
# Gebruik:
#   sudo bash /opt/portfoliomanager/deploy/update.sh
#   sudo bash /opt/portfoliomanager/deploy/update.sh --from-git
#
# Wat het doet:
#   1. Optioneel de vertrouwde main-branch ophalen (--from-git)
#   2. Python-dependencies bijwerken (pip install -r requirements.txt)
#   3. Bestandsrechten corrigeren
#   4. Systemd-service herstarten

set -euo pipefail

# ── Configuratie ────────────────────────────────────────────────────────────
APP_DIR="/opt/portfoliomanager"
VENV="$APP_DIR/.venv"
SERVICE_USER="service_portfolio_manager"
SERVICE_NAME="portfoliomanager"
OFFICIAL_REPOSITORY="Sharpe-nl/PortfolioManager"

UPDATE_FROM_GIT=false
case "${1:-}" in
  "") ;;
  --from-git) UPDATE_FROM_GIT=true ;;
  *) echo "Gebruik: $0 [--from-git]" >&2; exit 2 ;;
esac

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

# ── 0. Optioneel bijwerken vanaf de officiële main-branch ───────────────────
if "$UPDATE_FROM_GIT"; then
  info "Officiële main-branch ophalen…"
  if ! git -C "$APP_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    err "'$APP_DIR' is geen git checkout; gebruik de handmatige updateprocedure."
    exit 1
  fi
  if [[ "$(git -C "$APP_DIR" branch --show-current)" != "main" ]]; then
    err "Self-update werkt alleen vanaf de main-branch."
    exit 1
  fi
  origin_url="$(git -C "$APP_DIR" remote get-url origin 2>/dev/null || true)"
  case "$origin_url" in
    "https://github.com/$OFFICIAL_REPOSITORY"|"https://github.com/$OFFICIAL_REPOSITORY.git"|\
    "git@github.com:$OFFICIAL_REPOSITORY.git"|"ssh://git@github.com/$OFFICIAL_REPOSITORY.git") ;;
    *)
      err "De git-origin is niet de officiële PortfolioManager-repository."
      exit 1
      ;;
  esac
  if [[ -n "$(git -C "$APP_DIR" status --porcelain --untracked-files=no)" ]]; then
    err "De checkout bevat lokale wijzigingen; self-update is afgebroken."
    exit 1
  fi
  git -C "$APP_DIR" fetch --quiet origin main
  git -C "$APP_DIR" merge --ff-only --quiet FETCH_HEAD
  ok "Broncode bijgewerkt vanaf main."
fi

# ── 1. Zorg dat rsync beschikbaar is (voor toekomstige deploys) ──────────────
if ! command -v rsync &>/dev/null; then
  info "rsync niet gevonden — wordt eenmalig geïnstalleerd…"
  apt-get install -y -qq rsync
  ok "rsync geïnstalleerd. Volgende deploy gebruikt automatisch rsync."
fi

# ── 2. Python __pycache__ wissen (voorkomt dat oude .pyc bestanden worden gebruikt) ──
info "Python cache wissen…"
find "$APP_DIR" -type d -name "__pycache__" -not -path "$APP_DIR/.venv/*" -exec rm -rf {} + 2>/dev/null || true
find "$APP_DIR" -name "*.pyc" -not -path "$APP_DIR/.venv/*" -delete 2>/dev/null || true
ok "Cache gewist."

# ── 3. Python-dependencies ───────────────────────────────────────────────────
info "Python-dependencies bijwerken…"
sudo -u "$SERVICE_USER" "$VENV/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
ok "Dependencies bijgewerkt."

# ── 4. Bestandsrechten ───────────────────────────────────────────────────────
info "Bestandsrechten corrigeren…"
# The update unit runs this script as root. Keep the checkout, its Git
# metadata and deploy scripts root-owned so the web-service account can never
# alter something that is later executed as root. The application only needs
# to write its data directory and virtual environment.
chown -R root:root "$APP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/data" "$VENV"
# Data-map leesbaar/schrijfbaar voor de service, niet voor anderen.
chmod 750 "$APP_DIR/data" 2>/dev/null || true
chmod 750 "$APP_DIR/deploy/update.sh"
ok "Rechten gecorrigeerd."

# ── 5. Service herstarten ────────────────────────────────────────────────────
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
