#!/usr/bin/env bash
# install-watchdog.sh — install the ai-bob-watchdog as a systemd service
#
# Usage:
#   sudo ./deploy/install-watchdog.sh              # install and start
#   sudo ./deploy/install-watchdog.sh --no-start   # install only
#   sudo ./deploy/install-watchdog.sh --dry-run    # print what would happen
#
# Prerequisites:
#   - Linux with systemd
#   - .venv with dependencies installed (run ./install.sh first)
#   - .env or /etc/ai-bob-setup-agent/watchdog.env with credentials
#
# What it does:
#   1. Detects the deploy directory and running user
#   2. Creates /etc/ai-bob-setup-agent/ for the env file
#   3. Copies and templates the systemd unit file
#   4. Copies the env template (if no env file exists yet)
#   5. Reloads systemd, enables and starts the service

set -euo pipefail

# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="ai-bob-watchdog"
UNIT_SRC="$SCRIPT_DIR/ai-bob-watchdog.service"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_DIR="/etc/ai-bob-setup-agent"
ENV_DST="${ENV_DIR}/watchdog.env"
ENV_SRC="$SCRIPT_DIR/ai-bob-watchdog.env"
LOG_DIR="$REPO_DIR/logs"

DRY_RUN="false"
NO_START="false"

# -------------------------------------------------------------------------
# Argument parsing
# -------------------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN="true" ;;
    --no-start)  NO_START="true" ;;
    -h|--help)
      cat <<'EOF'
ai-bob-watchdog systemd installer

USAGE:
  sudo ./deploy/install-watchdog.sh [OPTIONS]

OPTIONS:
  --dry-run     Print what would happen without making changes
  --no-start    Install the unit file but don't start the service
  -h, --help    Show this help

WHAT IT DOES:
  1. Creates /etc/ai-bob-setup-agent/ for the env file
  2. Templates and installs the systemd unit to /etc/systemd/system/
  3. Copies the env template if no env file exists
  4. Creates a logs/ directory for ReadWritePaths
  5. Enables and starts the watchdog service

PREREQUISITES:
  - Linux with systemd (Ubuntu 20.04+, Debian 11+, RHEL 8+)
  - Run ./install.sh first (creates .venv with dependencies)
  - Fill in /etc/ai-bob-setup-agent/watchdog.env with real API keys

MANAGEMENT:
  systemctl status ai-bob-watchdog     # check status
  systemctl restart ai-bob-watchdog    # restart after config changes
  journalctl -u ai-bob-watchdog -f     # tail logs
  make watchdog-uninstall              # remove the service
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
log()  { printf "\033[1;34m[watchdog-install]\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m[ok]\033[0m              %s\n" "$*"; }
warn() { printf "\033[1;33m[warn]\033[0m            %s\n" "$*"; }
err()  { printf "\033[1;31m[err]\033[0m             %s\n" "$*" >&2; }

run() {
  if [[ "$DRY_RUN" == "true" ]]; then
    printf "\033[2m[dry-run]\033[0m %s\n" "$*"
  else
    eval "$@"
  fi
}

# -------------------------------------------------------------------------
# Preflight checks
# -------------------------------------------------------------------------
preflight() {
  # Must be root (or dry-run)
  if [[ "$EUID" -ne 0 && "$DRY_RUN" == "false" ]]; then
    err "This script must be run as root (sudo)."
    exit 1
  fi

  # systemd must be present
  if ! command -v systemctl >/dev/null 2>&1; then
    err "systemctl not found. This script requires systemd."
    exit 1
  fi

  # Unit template must exist
  if [[ ! -f "$UNIT_SRC" ]]; then
    err "Unit file not found at $UNIT_SRC"
    exit 1
  fi

  # .venv must exist
  if [[ ! -d "$REPO_DIR/.venv" ]]; then
    err ".venv not found. Run ./install.sh first."
    exit 1
  fi

  # Detect the non-root user who owns the repo
  DEPLOY_USER="$(stat -c '%U' "$REPO_DIR")"
  DEPLOY_GROUP="$(stat -c '%G' "$REPO_DIR")"
  log "Deploy user:  $DEPLOY_USER"
  log "Deploy group: $DEPLOY_GROUP"
  log "Deploy dir:   $REPO_DIR"
}

# -------------------------------------------------------------------------
# Step 1: Create config directory
# -------------------------------------------------------------------------
create_config_dir() {
  log "Creating config directory at $ENV_DIR..."
  if [[ -d "$ENV_DIR" ]]; then
    ok "Config directory already exists"
  else
    run "mkdir -p '$ENV_DIR'"
    run "chmod 750 '$ENV_DIR'"
    ok "Created $ENV_DIR"
  fi
}

# -------------------------------------------------------------------------
# Step 2: Copy env template (if no env file exists)
# -------------------------------------------------------------------------
copy_env_template() {
  if [[ -f "$ENV_DST" ]]; then
    ok "Env file already exists at $ENV_DST"
  else
    log "Copying env template to $ENV_DST..."
    run "cp '$ENV_SRC' '$ENV_DST'"
    run "chmod 600 '$ENV_DST'"
    warn "Fill in $ENV_DST with real API keys before starting the service"
  fi
}

# -------------------------------------------------------------------------
# Step 3: Template and install unit file
# -------------------------------------------------------------------------
install_unit() {
  log "Installing systemd unit to $UNIT_DST..."

  if [[ "$DRY_RUN" == "true" ]]; then
    printf "\033[2m[dry-run]\033[0m Would template and copy %s -> %s\n" "$UNIT_SRC" "$UNIT_DST"
    printf "\033[2m[dry-run]\033[0m  __DEPLOY_DIR__   -> %s\n" "$REPO_DIR"
    printf "\033[2m[dry-run]\033[0m  __DEPLOY_USER__  -> %s\n" "$DEPLOY_USER"
    printf "\033[2m[dry-run]\033[0m  __DEPLOY_GROUP__ -> %s\n" "$DEPLOY_GROUP"
  else
    sed \
      -e "s|__DEPLOY_DIR__|${REPO_DIR}|g" \
      -e "s|__DEPLOY_USER__|${DEPLOY_USER}|g" \
      -e "s|__DEPLOY_GROUP__|${DEPLOY_GROUP}|g" \
      "$UNIT_SRC" > "$UNIT_DST"
    chmod 644 "$UNIT_DST"
  fi
  ok "Unit file installed"
}

# -------------------------------------------------------------------------
# Step 4: Create logs directory
# -------------------------------------------------------------------------
create_log_dir() {
  if [[ -d "$LOG_DIR" ]]; then
    ok "Logs directory already exists"
  else
    log "Creating logs directory at $LOG_DIR..."
    run "mkdir -p '$LOG_DIR'"
    run "chown '${DEPLOY_USER}:${DEPLOY_GROUP}' '$LOG_DIR'"
    ok "Created $LOG_DIR"
  fi
}

# -------------------------------------------------------------------------
# Step 5: Reload, enable, and start
# -------------------------------------------------------------------------
activate() {
  log "Reloading systemd daemon..."
  run "systemctl daemon-reload"

  log "Enabling ${SERVICE_NAME} to start on boot..."
  run "systemctl enable ${SERVICE_NAME}"

  if [[ "$NO_START" == "true" ]]; then
    warn "Skipping start (--no-start). Start manually with: systemctl start ${SERVICE_NAME}"
  else
    log "Starting ${SERVICE_NAME}..."
    run "systemctl start ${SERVICE_NAME}"
    ok "Service started"
  fi
}

# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
main() {
  log "ai-bob-watchdog systemd installer"
  echo

  preflight
  echo

  create_config_dir
  copy_env_template
  install_unit
  create_log_dir
  echo

  activate
  echo

  ok "Watchdog installation complete."
  cat <<EOF

Management commands:
  systemctl status ${SERVICE_NAME}         # check status
  systemctl restart ${SERVICE_NAME}        # restart after config changes
  systemctl stop ${SERVICE_NAME}           # stop the watchdog
  journalctl -u ${SERVICE_NAME} -f         # tail live logs
  journalctl -u ${SERVICE_NAME} --since today  # today's logs
  make watchdog-uninstall                  # remove the service

Config:
  Env file:   $ENV_DST
  Unit file:  $UNIT_DST
  Logs:       journalctl -u ${SERVICE_NAME}

EOF
}

main "$@"
