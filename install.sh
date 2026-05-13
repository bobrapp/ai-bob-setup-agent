#!/usr/bin/env bash
# ai-bob-setup-agent — one-command idempotent bootstrap
# Usage: ./install.sh [--dry-run] [--skip-pip] [--skip-deps]
# Re-runs are safe: every step checks before acting.

set -euo pipefail

# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=10
VENV_DIR="${SCRIPT_DIR}/.venv"
DRY_RUN="${DRY_RUN:-false}"
SKIP_PIP="false"
SKIP_DEPS="false"

# -------------------------------------------------------------------------
# Argument parsing
# -------------------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN="true" ;;
    --skip-pip)  SKIP_PIP="true" ;;
    --skip-deps) SKIP_DEPS="true" ;;
    -h|--help)
      cat <<'EOF'
ai-bob-setup-agent installer

USAGE:
  ./install.sh [OPTIONS]

OPTIONS:
  --dry-run     Print intended actions, do not execute
  --skip-pip    Skip pip install (assume packages already present)
  --skip-deps   Skip OS-level dependency check
  -h, --help    Show this help

WHAT IT DOES:
  1. Verifies Python >= 3.10 is present
  2. Creates a virtualenv in .venv if missing
  3. Installs Python dependencies from requirements.txt
  4. Verifies .env exists (copies from .env.example if not)
  5. Runs `python -m src.setup_agent --doctor` to verify the environment
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
# Logging helpers
# -------------------------------------------------------------------------
log() { printf "\033[1;34m[setup]\033[0m %s\n" "$*"; }
ok()  { printf "\033[1;32m[ok]\033[0m    %s\n" "$*"; }
warn(){ printf "\033[1;33m[warn]\033[0m  %s\n" "$*"; }
err() { printf "\033[1;31m[err]\033[0m   %s\n" "$*" >&2; }

run() {
  if [[ "$DRY_RUN" == "true" ]]; then
    printf "\033[2m[dry-run]\033[0m %s\n" "$*"
  else
    eval "$@"
  fi
}

# -------------------------------------------------------------------------
# Step 1: Python version check
# -------------------------------------------------------------------------
check_python() {
  log "Checking Python version..."
  if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found. Install Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR} or newer."
    exit 1
  fi
  local version major minor
  version=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  major=${version%.*}
  minor=${version#*.}
  if (( major < PYTHON_MIN_MAJOR )) || (( major == PYTHON_MIN_MAJOR && minor < PYTHON_MIN_MINOR )); then
    err "Python $version found, need >= ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}"
    exit 1
  fi
  ok "Python $version"
}

# -------------------------------------------------------------------------
# Step 2: Virtualenv
# -------------------------------------------------------------------------
ensure_venv() {
  if [[ -d "$VENV_DIR" ]]; then
    ok "Virtualenv already present at $VENV_DIR"
  else
    log "Creating virtualenv at $VENV_DIR"
    run "python3 -m venv '$VENV_DIR'"
  fi
}

# -------------------------------------------------------------------------
# Step 3: Pip install
# -------------------------------------------------------------------------
pip_install() {
  if [[ "$SKIP_PIP" == "true" ]]; then
    warn "Skipping pip install (--skip-pip)"
    return
  fi
  log "Installing Python dependencies..."
  run "'$VENV_DIR/bin/pip' install --upgrade pip wheel >/dev/null"
  if [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
    run "'$VENV_DIR/bin/pip' install -r '$SCRIPT_DIR/requirements.txt'"
    ok "Dependencies installed"
  else
    warn "requirements.txt missing — skipping"
  fi
}

# -------------------------------------------------------------------------
# Step 4: .env
# -------------------------------------------------------------------------
ensure_env() {
  if [[ -f "$SCRIPT_DIR/.env" ]]; then
    ok ".env already present"
  elif [[ -f "$SCRIPT_DIR/.env.example" ]]; then
    log "Copying .env.example to .env (fill in your credentials)"
    run "cp '$SCRIPT_DIR/.env.example' '$SCRIPT_DIR/.env'"
    warn "Edit .env before running anything that hits real APIs"
  else
    err ".env.example missing — cannot bootstrap config"
    exit 1
  fi
}

# -------------------------------------------------------------------------
# Step 5: Doctor
# -------------------------------------------------------------------------
run_doctor() {
  log "Running environment doctor..."
  if [[ "$DRY_RUN" == "true" ]]; then
    printf "\033[2m[dry-run]\033[0m would run: python -m src.setup_agent --doctor\n"
  else
    # Doctor surfaces missing keys without failing the install.
    "$VENV_DIR/bin/python" -m src.setup_agent --doctor || warn "Doctor reported issues — fill in .env"
  fi
}

# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
main() {
  log "ai-bob-setup-agent installer"
  log "Working dir: $SCRIPT_DIR"
  log "Dry run:     $DRY_RUN"
  echo
  check_python
  ensure_venv
  pip_install
  ensure_env
  run_doctor
  echo
  ok "Bootstrap complete."
  cat <<EOF

Next steps:
  1. Edit .env and fill in your API keys.
  2. Copy config/customers.example.yaml to config/customers/<your-customer>.yaml
  3. Run: make onboard CUSTOMER=<slug>
  4. Read: ./docs/spec.md or https://bobrapp.github.io/ai-bob-setup-agent

EOF
}

main "$@"
