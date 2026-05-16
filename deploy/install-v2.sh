#!/usr/bin/env bash
# install-v2.sh — Deploy AIGovOps Foundation Automation v2 to production
#
# Run: sudo bash deploy/install-v2.sh
#
# Prerequisites: Python 3.11+, git, systemd

set -e

INSTALL_DIR="/opt/ai-bob-setup-agent"
SERVICE_NAME="aigovops-v2"
USER="bob"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  AIGovOps Foundation Automation v2 — Production Install  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash deploy/install-v2.sh"
    exit 1
fi

# Create user if needed
if ! id "$USER" &>/dev/null; then
    echo "Creating user: $USER"
    useradd -m -s /bin/bash "$USER"
fi

# Clone or update repo
if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing installation..."
    cd "$INSTALL_DIR"
    sudo -u "$USER" git pull origin main
else
    echo "Cloning repository..."
    git clone https://github.com/bobrapp/ai-bob-setup-agent.git "$INSTALL_DIR"
    chown -R "$USER:$USER" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    sudo -u "$USER" python3 -m venv .venv
fi

# Install dependencies
echo "Installing dependencies..."
sudo -u "$USER" .venv/bin/pip install -q --upgrade pip
sudo -u "$USER" .venv/bin/pip install -q -r requirements.txt

# Create directories
echo "Creating data directories..."
sudo -u "$USER" mkdir -p data logs backups config/personal-foundation

# Check config
if [ ! -f "config/personal-foundation/config.yaml" ]; then
    echo ""
    echo "⚠️  Config not found. Copy the example and fill in credentials:"
    echo "    cp config/personal-foundation/config.example.yaml config/personal-foundation/config.yaml"
    echo "    nano config/personal-foundation/config.yaml"
    echo ""
fi

# Check .env
if [ ! -f ".env" ]; then
    echo "⚠️  .env not found. Copy the example:"
    echo "    cp .env.example .env"
    echo "    nano .env"
fi

# Install systemd service
echo "Installing systemd service..."
cp deploy/aigovops-v2.service /etc/systemd/system/${SERVICE_NAME}.service
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}

# Setup backup cron
echo "Setting up backup cron (every 6 hours)..."
CRON_LINE="0 */6 * * * cp ${INSTALL_DIR}/data/foundation.db ${INSTALL_DIR}/backups/foundation-\$(date +\%Y\%m\%d-\%H\%M).db"
(crontab -u "$USER" -l 2>/dev/null | grep -v "foundation.db"; echo "$CRON_LINE") | crontab -u "$USER" -

# Cleanup old backups (keep 7 days)
CLEANUP_LINE="0 0 * * * find ${INSTALL_DIR}/backups -name 'foundation-*.db' -mtime +7 -delete"
(crontab -u "$USER" -l 2>/dev/null | grep -v "foundation-\*.db.*-delete"; echo "$CLEANUP_LINE") | crontab -u "$USER" -

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅ Installation complete!                               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Next steps:"
echo "    1. Fill in config: nano ${INSTALL_DIR}/config/personal-foundation/config.yaml"
echo "    2. Fill in .env:   nano ${INSTALL_DIR}/.env"
echo "    3. Test:           sudo -u ${USER} ${INSTALL_DIR}/.venv/bin/python -m src.personal_foundation.v2 --test"
echo "    4. Start:          systemctl start ${SERVICE_NAME}"
echo "    5. Check:          systemctl status ${SERVICE_NAME}"
echo "    6. Logs:           journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "  API will be at: http://localhost:8000"
echo "  API docs:       http://localhost:8000/docs"
echo ""
