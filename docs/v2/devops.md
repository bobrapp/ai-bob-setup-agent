# DevOps & Deployment

## Deployment Model

**Target:** Single machine (Bob's MacBook for dev, $20/mo VPS for production).
**Philosophy:** No containers, no orchestrators, no cloud-native complexity. Just Python + SQLite + systemd.

---

## Environments

| Environment | Where | Config | Purpose |
|-------------|-------|--------|---------|
| Local dev | Bob's MacBook | `dry_run: true` | Development and testing |
| Staging | Same machine, different profile | `stage: staging` | Test with real APIs, approval required |
| Production | VPS or always-on Mac | `stage: production` | Live, serving real users |

---

## Installation

```bash
# One-command install
git clone https://github.com/bobrapp/ai-bob-setup-agent.git
cd ai-bob-setup-agent
make install-foundation

# Interactive setup
bash scripts/setup_foundation.sh

# Verify
make doctor-foundation
```

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Runtime |
| git | any | Version control |
| make | any | Task runner |
| uv (optional) | latest | Fast package installs |

---

## Process Management

### Development (foreground)
```bash
python -m src.personal_foundation --dry-run
```

### Production (systemd)
```ini
# /etc/systemd/system/aigovops-automation.service
[Unit]
Description=AIGovOps Foundation Automation
After=network.target

[Service]
Type=simple
User=bob
WorkingDirectory=/opt/ai-bob-setup-agent
ExecStart=/opt/ai-bob-setup-agent/.venv/bin/python -m src.personal_foundation
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable aigovops-automation
sudo systemctl start aigovops-automation
sudo journalctl -u aigovops-automation -f  # tail logs
```

---

## CI/CD Pipeline

```yaml
# .github/workflows/ci.yml
jobs:
  lint:
    - ruff check
    - ruff format --check
    - mypy --strict src/personal_foundation/

  unit-tests:
    - pytest tests/ -v --ignore=tests/test_integration*

  pbt-tests:
    - pytest tests/test_pbt_personal_foundation.py -v

  policy-check:
    - cedar validate policies/
    - cedar test policies/ --test-suite tests/policy_tests/

  dry-run:
    - python -m src.personal_foundation --test --dry-run

  deploy:
    if: github.ref == 'refs/heads/main'
    - ssh production "cd /opt/ai-bob-setup-agent && git pull && systemctl restart aigovops-automation"
```

---

## Monitoring

| What | How | Alert |
|------|-----|-------|
| Process alive | systemd watchdog | Auto-restart + Telegram alert |
| Agent failure rate | Audit log query (>10% in 24h) | Auto-suspend + Telegram |
| Disk space | `df` check in healthcheck | Telegram if <1GB free |
| API key expiry | Config metadata | Telegram 7 days before |
| SQLite size | File size check | Telegram if >500MB |

### Healthcheck endpoint
```
GET /api/health → { "status": "ok", "agents": 8, "pending_approvals": 3, "uptime_hours": 48.2 }
```

---

## Backup Strategy

| What | Frequency | Where | Retention |
|------|-----------|-------|-----------|
| SQLite database | Every 6 hours | `backups/foundation-{timestamp}.db` | 7 days |
| Agent YAML definitions | On every change (git) | GitHub | Forever |
| Cedar policies | On every change (git) | GitHub | Forever |
| Audit log export | Weekly | `backups/audit-week-{N}.jsonl` | 90 days |

```bash
# Automated backup (cron)
0 */6 * * * cp /opt/ai-bob-setup-agent/data/foundation.db /opt/ai-bob-setup-agent/backups/foundation-$(date +\%Y\%m\%d-\%H\%M).db
```

---

## Rollback

```bash
# Rollback to previous version
git log --oneline -5
git revert HEAD
systemctl restart aigovops-automation

# Rollback database (restore from backup)
systemctl stop aigovops-automation
cp backups/foundation-20260515-1200.db data/foundation.db
systemctl start aigovops-automation
```

---

## Secrets Management

| Secret | Storage | Access |
|--------|---------|--------|
| API keys (OpenAI, Groq, etc.) | macOS Keychain / `.env` file (chmod 600) | Read at startup only |
| Telegram bot token | Same as above | Read at startup only |
| JWT signing key | Generated on first run, stored in keychain | API gateway only |
| SQLCipher passphrase | macOS Keychain | Database layer only |

**Never in git. Never in logs. Never in API responses.**
