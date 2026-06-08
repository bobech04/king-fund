#!/usr/bin/env bash
# =============================================================================
# King Fund — Installation complète Raspberry Pi 5
# =============================================================================
#
# PRÉREQUIS
#   - Raspberry Pi 5 (4 Go RAM minimum recommandé)
#   - Raspberry Pi OS Bookworm 64-bit (Debian 12)
#   - Connexion internet active
#   - Compte No-IP créé sur https://www.noip.com (optionnel mais recommandé)
#
# USAGE
#   sudo bash install_raspberry.sh
#
# CE QUE FAIT CE SCRIPT
#   1. Mise à jour système
#   2. Installation Python 3.11 + pip + venv
#   3. Déploiement du projet dans /opt/king-fund/
#   4. Installation des dépendances pip dans un virtualenv
#   5. Configuration du fichier .env
#   6. Création du service systemd king-fund (démarrage automatique)
#   7. Installation du client DNS dynamique No-IP DUC
#   8. Création du service systemd noip2
#   9. Activation et démarrage des services
#
# APRÈS L'INSTALLATION
#   - Tester : curl http://localhost:5000/api/state
#   - Logs   : journalctl -u king-fund -f
#   - Statut : systemctl status king-fund
# =============================================================================

set -euo pipefail

# ─── Couleurs ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "\n${YELLOW}══════════════════════════════════════════${NC}"; echo -e "${YELLOW} $* ${NC}"; echo -e "${YELLOW}══════════════════════════════════════════${NC}"; }

# ─── Variables ───────────────────────────────────────────────────────────────
KINGFUND_DIR="/opt/king-fund"
VENV_DIR="${KINGFUND_DIR}/venv"
SERVICE_NAME="king-fund"
SERVICE_USER="kingfund"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"   # un niveau au-dessus de scripts/

# ─── Vérification root ───────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Ce script doit être lancé en tant que root (sudo bash install_raspberry.sh)"

# =============================================================================
# ÉTAPE 1 — Mise à jour système
# =============================================================================
section "1/9 Mise à jour système"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    git curl wget build-essential libssl-dev libffi-dev \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    sqlite3 libsqlite3-dev \
    gcc make
info "Système mis à jour"

# =============================================================================
# ÉTAPE 2 — Python 3.11
# =============================================================================
section "2/9 Python 3.11"
PYTHON="python3.11"
$PYTHON --version || error "Python 3.11 introuvable"
info "Python 3.11 : $($PYTHON --version)"

# =============================================================================
# ÉTAPE 3 — Déploiement du projet
# =============================================================================
section "3/9 Déploiement du projet dans ${KINGFUND_DIR}"

# Créer utilisateur dédié si inexistant
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /bin/false "$SERVICE_USER"
    info "Utilisateur $SERVICE_USER créé"
fi

# Copier le projet
mkdir -p "$KINGFUND_DIR"
rsync -a --delete \
    --exclude='venv/' --exclude='__pycache__/' --exclude='*.pyc' \
    --exclude='.git/' --exclude='logs/*.log' \
    "${PROJECT_ROOT}/" "${KINGFUND_DIR}/"

chown -R "$SERVICE_USER":"$SERVICE_USER" "$KINGFUND_DIR"
chmod -R 750 "$KINGFUND_DIR"
info "Projet déployé dans $KINGFUND_DIR"

# =============================================================================
# ÉTAPE 4 — Virtualenv + dépendances
# =============================================================================
section "4/9 Virtualenv et dépendances pip"
$PYTHON -m venv "$VENV_DIR"
"${VENV_DIR}/bin/pip" install --upgrade pip wheel -q

# Installer depuis requirements.txt si présent
if [[ -f "${KINGFUND_DIR}/backend/requirements.txt" ]]; then
    "${VENV_DIR}/bin/pip" install -r "${KINGFUND_DIR}/backend/requirements.txt" -q
else
    warn "requirements.txt introuvable — installation des paquets de base"
    "${VENV_DIR}/bin/pip" install -q \
        flask flask-cors flask-sock simple-websocket \
        apscheduler pytz \
        yfinance pandas requests \
        anthropic python-dotenv \
        apscheduler fpdf2
fi

# Paquets toujours nécessaires (non listés dans requirements)
"${VENV_DIR}/bin/pip" install -q apscheduler pytz fpdf2 || true

info "Dépendances installées"

# =============================================================================
# ÉTAPE 5 — Fichier .env
# =============================================================================
section "5/9 Configuration .env"
ENV_FILE="${KINGFUND_DIR}/backend/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "${KINGFUND_DIR}/backend/.env.example" ]]; then
        cp "${KINGFUND_DIR}/backend/.env.example" "$ENV_FILE"
        warn ".env créé depuis .env.example — À RENSEIGNER avant de démarrer le service"
    else
        cat > "$ENV_FILE" <<'ENVEOF'
# King Fund — Variables d'environnement
# OBLIGATOIRE : renseigner les clés API avant de démarrer

ANTHROPIC_API_KEY=
FRED_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GLASSNODE_API_KEY=
EIA_API_KEY=
ALPHA_VANTAGE_API_KEY=
COINGECKO_API_KEY=
TICK_INTERVAL=60
BATTLE_START_DATE=2026-05-30
ENVEOF
        warn ".env créé avec des valeurs vides — RENSEIGNER les clés API"
    fi
fi

chmod 600 "$ENV_FILE"
chown "$SERVICE_USER":"$SERVICE_USER" "$ENV_FILE"
info ".env configuré : $ENV_FILE"

# =============================================================================
# ÉTAPE 6 — Service systemd king-fund
# =============================================================================
section "6/9 Service systemd king-fund"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<SERVICEEOF
[Unit]
Description=King Fund Trading Engine
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${KINGFUND_DIR}/backend
ExecStart=${VENV_DIR}/bin/python app.py
EnvironmentFile=${ENV_FILE}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=king-fund

# Sécurité
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=${KINGFUND_DIR}

[Install]
WantedBy=multi-user.target
SERVICEEOF

info "Service ${SERVICE_NAME}.service créé"

# =============================================================================
# ÉTAPE 7 — No-IP DUC (DNS dynamique)
# =============================================================================
section "7/9 No-IP DUC — DNS dynamique"

NOIP_BIN="/usr/local/bin/noip2"

if [[ ! -f "$NOIP_BIN" ]]; then
    info "Téléchargement et compilation du client No-IP DUC..."
    NOIP_TMP="$(mktemp -d)"
    cd "$NOIP_TMP"
    wget -q "https://www.noip.com/client/linux/noip-duc-linux.tar.gz" -O noip-duc.tar.gz
    tar -xzf noip-duc.tar.gz
    cd noip-*
    make -s
    make install
    cd /
    rm -rf "$NOIP_TMP"
    info "No-IP DUC installé dans $NOIP_BIN"
    warn "Lancer : sudo $NOIP_BIN -C  (première configuration — entre vos identifiants No-IP)"
else
    info "No-IP DUC déjà installé : $NOIP_BIN"
fi

# =============================================================================
# ÉTAPE 8 — Service systemd noip2
# =============================================================================
section "8/9 Service systemd noip2"

cat > "/etc/systemd/system/noip2.service" <<'NOIP_SERVICE'
[Unit]
Description=No-IP Dynamic DNS Update Client
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
ExecStart=/usr/local/bin/noip2
Restart=always
RestartSec=300

[Install]
WantedBy=multi-user.target
NOIP_SERVICE

info "Service noip2.service créé"

# =============================================================================
# ÉTAPE 9 — Activation et démarrage
# =============================================================================
section "9/9 Activation des services"

systemctl daemon-reload

# king-fund — ne pas démarrer si .env n'est pas configuré
systemctl enable "${SERVICE_NAME}.service"
if grep -q "^ANTHROPIC_API_KEY=$" "$ENV_FILE" 2>/dev/null; then
    warn "ANTHROPIC_API_KEY non renseignée — service king-fund NON démarré"
    warn "→ Éditer $ENV_FILE puis : sudo systemctl start king-fund"
else
    systemctl start "${SERVICE_NAME}.service" || warn "Échec démarrage king-fund (voir journalctl -u king-fund)"
    info "Service king-fund démarré"
fi

# noip2 — uniquement si configuré
if [[ -f /etc/no-ip2.conf ]]; then
    systemctl enable noip2.service
    systemctl start noip2.service
    info "Service noip2 démarré"
else
    warn "No-IP non configuré — lancer : sudo $NOIP_BIN -C"
    warn "Puis : sudo systemctl enable noip2 && sudo systemctl start noip2"
fi

# =============================================================================
# RÉSUMÉ FINAL
# =============================================================================
section "Installation terminée"
echo ""
echo "  Projet    : $KINGFUND_DIR"
echo "  Logs      : journalctl -u king-fund -f"
echo "  Statut    : systemctl status king-fund"
echo "  Test API  : curl http://localhost:5000/api/state"
echo ""
echo "  ACTIONS REQUISES :"
echo "  1. Éditer $ENV_FILE et renseigner les clés API"
echo "  2. sudo systemctl start king-fund"
if [[ ! -f /etc/no-ip2.conf ]]; then
echo "  3. sudo $NOIP_BIN -C   (configurer No-IP)"
echo "  4. sudo systemctl enable noip2 && sudo systemctl start noip2"
fi
echo ""
info "Installation King Fund Raspberry Pi 5 — TERMINÉE"
