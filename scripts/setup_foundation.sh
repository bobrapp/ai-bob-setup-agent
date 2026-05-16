#!/usr/bin/env bash
# setup_foundation.sh — Interactive setup wizard for the Personal + Foundation Automation
#
# Run: bash scripts/setup_foundation.sh
#
# This script:
# 1. Checks prerequisites (Python 3.11+, pip, git)
# 2. Creates a virtual environment if needed
# 3. Installs dependencies
# 4. Walks you through filling in config/personal-foundation/config.yaml
# 5. Runs doctor to verify
# 6. Sends a test message to Telegram
# 7. Starts the system in dry-run mode

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  AIGovOps Foundation — Personal Automation Setup Wizard     ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# --- Prerequisites ---
echo -e "${CYAN}Checking prerequisites...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 not found. Install Python 3.11+ first.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "${GREEN}✓ Python ${PYTHON_VERSION}${NC}"

if ! command -v git &> /dev/null; then
    echo -e "${RED}✗ git not found. Install git first.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ git$(git --version | cut -d' ' -f3)${NC}"

# --- Virtual environment ---
if [ ! -d ".venv" ]; then
    echo -e "${CYAN}Creating virtual environment...${NC}"
    python3 -m venv .venv
fi
source .venv/bin/activate
echo -e "${GREEN}✓ Virtual environment active${NC}"

# --- Dependencies ---
echo -e "${CYAN}Installing dependencies...${NC}"
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"

# --- Config file ---
CONFIG_DIR="config/personal-foundation"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
EXAMPLE_FILE="${CONFIG_DIR}/config.example.yaml"

mkdir -p "$CONFIG_DIR"

if [ -f "$CONFIG_FILE" ]; then
    echo -e "${GREEN}✓ Config file exists: ${CONFIG_FILE}${NC}"
    echo -e "  (To reconfigure, delete it and re-run this script)"
else
    echo ""
    echo -e "${BOLD}Let's set up your credentials.${NC}"
    echo -e "You'll need these ready:"
    echo -e "  • OpenAI API key (for the AI agents)"
    echo -e "  • Telegram bot token (from @BotFather)"
    echo -e "  • Your Telegram chat ID (for notifications)"
    echo ""

    cp "$EXAMPLE_FILE" "$CONFIG_FILE"

    # OpenAI
    echo -e "${CYAN}1/6 — OpenAI API Key${NC}"
    echo -n "  Paste your OpenAI API key (sk-...): "
    read -r OPENAI_KEY
    if [ -n "$OPENAI_KEY" ]; then
        sed -i '' "s|YOUR_PERPLEXITY_API_KEY|${OPENAI_KEY}|" "$CONFIG_FILE" 2>/dev/null || \
        sed -i "s|YOUR_PERPLEXITY_API_KEY|${OPENAI_KEY}|" "$CONFIG_FILE"
    fi

    # Telegram bot token
    echo -e "${CYAN}2/6 — Telegram Bot Token${NC}"
    echo "  Create a bot via @BotFather on Telegram, then paste the token."
    echo -n "  Bot token: "
    read -r TG_TOKEN
    if [ -n "$TG_TOKEN" ]; then
        sed -i '' "s|YOUR_TELEGRAM_BOT_TOKEN|${TG_TOKEN}|" "$CONFIG_FILE" 2>/dev/null || \
        sed -i "s|YOUR_TELEGRAM_BOT_TOKEN|${TG_TOKEN}|" "$CONFIG_FILE"
    fi

    # Telegram chat IDs
    echo -e "${CYAN}3/6 — Your Telegram Chat ID (Bob)${NC}"
    echo "  Send /start to your bot, then visit: https://api.telegram.org/bot${TG_TOKEN}/getUpdates"
    echo "  Look for 'chat': {'id': YOUR_NUMBER}"
    echo -n "  Bob's chat ID: "
    read -r BOB_CHAT
    if [ -n "$BOB_CHAT" ]; then
        sed -i '' "s|YOUR_BOB_CHAT_ID|${BOB_CHAT}|" "$CONFIG_FILE" 2>/dev/null || \
        sed -i "s|YOUR_BOB_CHAT_ID|${BOB_CHAT}|" "$CONFIG_FILE"
        # Use same as approval channel for now
        sed -i '' "s|YOUR_APPROVAL_CHAT_ID|${BOB_CHAT}|" "$CONFIG_FILE" 2>/dev/null || \
        sed -i "s|YOUR_APPROVAL_CHAT_ID|${BOB_CHAT}|" "$CONFIG_FILE"
    fi

    echo -e "${CYAN}4/6 — Ken's Telegram Chat ID${NC}"
    echo -n "  Ken's chat ID (or press Enter to use Bob's for now): "
    read -r KEN_CHAT
    KEN_CHAT="${KEN_CHAT:-$BOB_CHAT}"
    if [ -n "$KEN_CHAT" ]; then
        sed -i '' "s|YOUR_KEN_CHAT_ID|${KEN_CHAT}|" "$CONFIG_FILE" 2>/dev/null || \
        sed -i "s|YOUR_KEN_CHAT_ID|${KEN_CHAT}|" "$CONFIG_FILE"
    fi

    # Circle.so (optional)
    echo -e "${CYAN}5/6 — Circle.so API Key (optional — press Enter to skip)${NC}"
    echo -n "  Circle.so API key: "
    read -r CIRCLE_KEY
    if [ -n "$CIRCLE_KEY" ]; then
        sed -i '' "s|YOUR_CIRCLE_API_KEY|${CIRCLE_KEY}|" "$CONFIG_FILE" 2>/dev/null || \
        sed -i "s|YOUR_CIRCLE_API_KEY|${CIRCLE_KEY}|" "$CONFIG_FILE"
    fi

    # Composio (optional)
    echo -e "${CYAN}6/6 — Composio API Key (optional — press Enter to skip)${NC}"
    echo -n "  Composio API key: "
    read -r COMPOSIO_KEY
    if [ -n "$COMPOSIO_KEY" ]; then
        sed -i '' "s|YOUR_COMPOSIO_API_KEY|${COMPOSIO_KEY}|" "$CONFIG_FILE" 2>/dev/null || \
        sed -i "s|YOUR_COMPOSIO_API_KEY|${COMPOSIO_KEY}|" "$CONFIG_FILE"
    fi

    echo ""
    echo -e "${GREEN}✓ Config saved to ${CONFIG_FILE}${NC}"
    echo -e "  You can edit it later to add more service keys."
fi

# --- Also set OPENAI_API_KEY in .env for the audit log ---
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${YELLOW}  → Created .env from .env.example (fill in remaining keys as needed)${NC}"
fi

# --- Doctor check ---
echo ""
echo -e "${CYAN}Running doctor check...${NC}"
python3 -c "
from src.personal_foundation.config import load_config
import sys
try:
    cfg = load_config()
    print('  ✓ Config loaded and valid')
    print(f'  ✓ dry_run = {cfg.dry_run}')
    print(f'  ✓ Telegram bot token: ...{cfg.telegram.bot_token[-8:] if len(cfg.telegram.bot_token) > 8 else \"(not set)\"}')
    print(f'  ✓ Approval chat: {cfg.telegram.approval_chat_id}')
except FileNotFoundError as e:
    print(f'  ✗ {e}')
    sys.exit(1)
except Exception as e:
    print(f'  ✗ Config error: {e}')
    print('  → Edit config/personal-foundation/config.yaml and try again')
    sys.exit(1)
" || { echo -e "${RED}Doctor check failed. Fix the config and re-run.${NC}"; exit 1; }

echo -e "${GREEN}✓ Doctor check passed${NC}"

# --- Test Telegram ---
echo ""
echo -e "${CYAN}Sending test message to Telegram...${NC}"
python3 -m src.personal_foundation --test --dry-run 2>&1 | tail -3

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  ✅ Setup complete!                                          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}To start in dry-run mode (safe, no real actions):${NC}"
echo -e "    ${CYAN}python -m src.personal_foundation --dry-run${NC}"
echo ""
echo -e "  ${BOLD}To go live (real LLM calls, real Telegram notifications):${NC}"
echo -e "    ${CYAN}python -m src.personal_foundation${NC}"
echo ""
echo -e "  ${BOLD}Telegram commands available:${NC}"
echo -e "    /status  — System health"
echo -e "    /pending — Show approval queue"
echo -e "    /suspend personal/email_agent — Pause an agent"
echo -e "    /resume personal/email_agent  — Resume an agent"
echo ""
echo -e "  ${BOLD}Docs:${NC} https://bobrapp.github.io/ai-bob-setup-agent/automation.html"
echo ""
