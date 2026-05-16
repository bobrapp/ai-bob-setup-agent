# ai-bob-setup-agent — Makefile
# Task runner. Targets are idempotent unless otherwise noted.

# -------------------------------------------------------------------------
# Variables
# -------------------------------------------------------------------------
PYTHON ?= .venv/bin/python
PIP    ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest
CUSTOMER ?=
DRY_RUN ?= false
FORCE ?=

# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1;36m%-18s\033[0m %s\n", $$1, $$2}'

# -------------------------------------------------------------------------
# Lifecycle
# -------------------------------------------------------------------------
.PHONY: install
install: ## One-command bootstrap (runs install.sh)
	@bash ./install.sh

.PHONY: doctor
doctor: ## Verify environment, .env, and connectivity to required APIs
	@$(PYTHON) -m src --doctor

.PHONY: clean
clean: ## Remove venv, caches, and build artifacts
	@rm -rf .venv .pytest_cache __pycache__ src/__pycache__ tests/__pycache__
	@find . -name '*.pyc' -delete
	@echo "Cleaned."

# -------------------------------------------------------------------------
# Quality
# -------------------------------------------------------------------------
.PHONY: lint
lint: ## Run linters
	@$(PYTHON) -m ruff check src tests scripts || true
	@$(PYTHON) -m ruff format --check src tests scripts || true

.PHONY: fmt
fmt: ## Auto-format code
	@$(PYTHON) -m ruff format src tests scripts

.PHONY: test
test: ## Run smoke tests
	@$(PYTEST) tests -v

.PHONY: ci
ci: lint test ## Full CI bundle (lint + test)

# -------------------------------------------------------------------------
# Operations
# -------------------------------------------------------------------------
.PHONY: onboard
onboard: ## Onboard a new customer (CUSTOMER=<slug>)
	@if [ -z "$(CUSTOMER)" ]; then echo "Usage: make onboard CUSTOMER=<slug>"; exit 1; fi
	@$(PYTHON) -m src onboard --customer $(CUSTOMER) --dry-run=$(DRY_RUN)

.PHONY: add-agent
add-agent: ## Add a new agent to an existing customer (CUSTOMER=<slug> AGENT=<name>)
	@if [ -z "$(CUSTOMER)" ] || [ -z "$(AGENT)" ]; then echo "Usage: make add-agent CUSTOMER=<slug> AGENT=<name>"; exit 1; fi
	@$(PYTHON) -m src add-agent --customer $(CUSTOMER) --agent $(AGENT) --dry-run=$(DRY_RUN)

.PHONY: status
status: ## Show deployment status for a customer (CUSTOMER=<slug>)
	@if [ -z "$(CUSTOMER)" ]; then echo "Usage: make status CUSTOMER=<slug>"; exit 1; fi
	@$(PYTHON) -m src status --customer $(CUSTOMER) --dry-run=$(DRY_RUN)

.PHONY: validate
validate: ## Validate a customer config (CUSTOMER=<slug>)
	@if [ -z "$(CUSTOMER)" ]; then echo "Usage: make validate CUSTOMER=<slug>"; exit 1; fi
	@$(PYTHON) -m src validate --customer $(CUSTOMER)

.PHONY: health
health: ## Run health check across all customers
	@$(PYTHON) scripts/healthcheck.py

.PHONY: watchdog
watchdog: ## Start watchdog loop (foreground)
	@$(PYTHON) scripts/watchdog.py

.PHONY: decom
decom: ## Decommission a customer (CUSTOMER=<slug>)
	@if [ -z "$(CUSTOMER)" ]; then echo "Usage: make decom CUSTOMER=<slug>"; exit 1; fi
	@$(PYTHON) -m src decommission --customer $(CUSTOMER) --dry-run=$(DRY_RUN) $(if $(FORCE),--force,)

# -------------------------------------------------------------------------
# Watchdog deployment
# -------------------------------------------------------------------------
.PHONY: watchdog-install
watchdog-install: ## Install watchdog as a systemd service (requires sudo)
	@sudo bash ./deploy/install-watchdog.sh

.PHONY: watchdog-uninstall
watchdog-uninstall: ## Uninstall the watchdog systemd service (requires sudo)
	@sudo bash ./deploy/uninstall-watchdog.sh

.PHONY: watchdog-status
watchdog-status: ## Show watchdog service status
	@systemctl status ai-bob-watchdog || true

.PHONY: watchdog-logs
watchdog-logs: ## Tail live watchdog logs from journald
	@journalctl -u ai-bob-watchdog -f

# -------------------------------------------------------------------------
# Personal + Foundation automation (internal)
# -------------------------------------------------------------------------
.PHONY: install-foundation
install-foundation: ## Bootstrap the personal + foundation automation system
	@echo "Installing personal + foundation automation dependencies..."
	@$(PIP) install -r requirements.txt
	@mkdir -p config/personal-foundation logs
	@if [ ! -f config/personal-foundation/config.yaml ]; then \
		echo "  → config/personal-foundation/config.yaml not found."; \
		echo "  → Copy config/personal-foundation/config.example.yaml and fill in credentials."; \
	else \
		echo "  → config/personal-foundation/config.yaml found."; \
	fi
	@echo "Done. Run 'make doctor-foundation' to verify your setup."

.PHONY: doctor-foundation
doctor-foundation: ## Verify the personal + foundation automation environment
	@$(PYTHON) -c "\
from src.personal_foundation.config import load_config; \
import sys; \
try: \
    cfg = load_config(); \
    print('  ✓ config/personal-foundation/config.yaml loaded and valid'); \
    print('  ✓ dry_run =', cfg.dry_run); \
    print('  ✓ bob_timezone =', cfg.bob_timezone); \
    print('Foundation doctor: OK'); \
except FileNotFoundError as e: \
    print('  ✗', e); \
    sys.exit(1); \
except Exception as e: \
    print('  ✗ Config validation error:', e); \
    sys.exit(1); \
"

.PHONY: run-foundation
run-foundation: ## Start the foundation automation orchestrator (foreground)
	@$(PYTHON) -m src.personal_foundation.orchestrator

# -------------------------------------------------------------------------
# Site / deploy
# -------------------------------------------------------------------------
.PHONY: site-serve
site-serve: ## Serve the static site locally on :8000
	@python3 -m http.server 8000

.PHONY: deploy
deploy: ## Commit and push current state (GitHub Pages auto-deploys)
	@git add -A
	@git commit -m "deploy: $$(date -u +'%Y-%m-%dT%H:%M:%SZ')" || true
	@git push origin main
