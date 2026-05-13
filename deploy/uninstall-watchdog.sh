#!/usr/bin/env bash
# uninstall-watchdog.sh — remove the ai-bob-watchdog systemd service
#
# Usage:
#   sudo ./deploy/uninstall-watchdog.sh              # stop and remove
#   sudo ./deploy/uninstall-watchdog.sh --keep-env   # remove service, keep env file
#   sudo ./deploy/uninstall-watchdog.sh --dry-run    # print what would happen
#
# This does NOT delete the repo, .venv, or customer configs.
# It only removes the systemd unit and optionally the env file.

set -euo pipefail

SERVICE_NAME="ai-bob-watchdog"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_DIR="/etc/ai-bob-setup-agent"
ENV_DST="${ENV_DIR}/watchdog.env"

DRY_RUN="false"
KEEP_ENV="false"

for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN="true" ;;
    --keep-env)  KEEP_ENV="true" ;;
    -h|--help)
      cat <<'EOF'
ai-bob-watchdog uninstaller

USAGE:
  sudo ./deploy/uninstall-watchdog.sh [OPTIONS]

OPTIONS:
  --dry-run     Print what would happen without making changes
  --keep-env    Keep /etc/ai-bob-setup-agent/watchdog.env (useful for reinstall)
  -h, --help    Show this help
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

log()  { printf "\033[1;34m[watchdog-uninstall]\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m[ok]\033[0m                %s\n" "$*"; }
warn() { printf "\033[1;33m[warn]\033[0m              %s\n" "$*"; }
err()  { printf "\033[1;31m[err]\033[0m               %s\n" "$*" >&2; }

run() {
  if [[ "$DRY_RUN" == "true" ]]; then
    printf "\033[2m[dry-run]\033[0m %s\n" "$*"
  else
    eval "$@"
  fi
}

# Must be root
if [[ "$EUID" -ne 0 && "$DRY_RUN" == "false" ]]; then
  err "This script must be run as root (sudo)."
  exit 1
fi

log "Uninstalling ${SERVICE_NAME}..."
echo

# Stop the service if running
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
  log "Stopping ${SERVICE_NAME}..."
  run "systemctl stop ${SERVICE_NAME}"
  ok "Service stopped"
else
  ok "Service not running"
fi

# Disable from boot
if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
  log "Disabling ${SERVICE_NAME}..."
  run "systemctl disable ${SERVICE_NAME}"
  ok "Service disabled"
else
  ok "Service not enabled"
fi

# Remove unit file
if [[ -f "$UNIT_DST" ]]; then
  log "Removing unit file at $UNIT_DST..."
  run "rm -f '$UNIT_DST'"
  ok "Unit file removed"
else
  ok "Unit file already absent"
fi

# Reload systemd
log "Reloading systemd daemon..."
run "systemctl daemon-reload"

# Optionally remove env file
if [[ "$KEEP_ENV" == "true" ]]; then
  warn "Keeping env file at $ENV_DST (--keep-env)"
else
  if [[ -f "$ENV_DST" ]]; then
    log "Removing env file at $ENV_DST..."
    run "rm -f '$ENV_DST'"
    ok "Env file removed"
  fi
  if [[ -d "$ENV_DIR" ]]; then
    # Only remove if empty
    if [[ -z "$(ls -A "$ENV_DIR" 2>/dev/null)" ]]; then
      run "rmdir '$ENV_DIR'"
      ok "Config directory removed"
    else
      warn "Config directory $ENV_DIR not empty, leaving in place"
    fi
  fi
fi

echo
ok "Uninstall complete. The repo, .venv, and customer configs are untouched."
