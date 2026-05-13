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
	@$(PYTHON) -m src.setup_agent --doctor

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
	@$(PYTHON) -m src.setup_agent onboard --customer $(CUSTOMER) --dry-run=$(DRY_RUN)

.PHONY: add-agent
add-agent: ## Add a new agent to an existing customer (CUSTOMER=<slug> AGENT=<name>)
	@if [ -z "$(CUSTOMER)" ] || [ -z "$(AGENT)" ]; then echo "Usage: make add-agent CUSTOMER=<slug> AGENT=<name>"; exit 1; fi
	@$(PYTHON) -m src.setup_agent add-agent --customer $(CUSTOMER) --agent $(AGENT) --dry-run=$(DRY_RUN)

.PHONY: health
health: ## Run health check across all customers
	@$(PYTHON) scripts/healthcheck.py

.PHONY: watchdog
watchdog: ## Start watchdog loop (foreground)
	@$(PYTHON) scripts/watchdog.py

.PHONY: decom
decom: ## Decommission a customer (CUSTOMER=<slug>)
	@if [ -z "$(CUSTOMER)" ]; then echo "Usage: make decom CUSTOMER=<slug>"; exit 1; fi
	@$(PYTHON) -m src.setup_agent decommission --customer $(CUSTOMER) --dry-run=$(DRY_RUN)

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
