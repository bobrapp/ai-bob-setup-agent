# Deploy

Systemd service files for running the ai-bob-setup-agent watchdog as a
persistent background process on the operator's host machine.

## Quick start

```bash
# 1. Bootstrap the repo (creates .venv, installs deps)
./install.sh

# 2. Install the watchdog as a systemd service
sudo ./deploy/install-watchdog.sh

# 3. Fill in API keys
sudo nano /etc/ai-bob-setup-agent/watchdog.env

# 4. Start watching
sudo systemctl restart ai-bob-watchdog
```

## Files

| File | Purpose |
|------|---------|
| `ai-bob-watchdog.service` | systemd unit template (placeholders replaced at install time) |
| `ai-bob-watchdog.env` | Environment variable template (API keys, SMTP config) |
| `install-watchdog.sh` | Installer: templates the unit, creates config dir, enables service |
| `uninstall-watchdog.sh` | Cleanup: stops, disables, removes unit and optionally env file |

## Management

```bash
# Check status
systemctl status ai-bob-watchdog

# Tail live logs
journalctl -u ai-bob-watchdog -f

# View today's logs
journalctl -u ai-bob-watchdog --since today

# Restart after config change
sudo systemctl restart ai-bob-watchdog

# Stop
sudo systemctl stop ai-bob-watchdog

# Uninstall (keeps env file for reinstall)
sudo ./deploy/uninstall-watchdog.sh --keep-env

# Full uninstall
sudo ./deploy/uninstall-watchdog.sh
```

## How it works

The watchdog polls every configured customer's Orgo cloud computers on a
configurable interval (default: 5 minutes). When a heartbeat is missed or
a VM status changes to `stopped` or `error`, it fires alerts via:

- **Telegram** — instant notification to the operator's control channel
- **Email** — SMTP-based alerts to the configured recipient

The systemd unit is configured with:

- **Restart on failure** — auto-restarts after 10s, up to 5 times in 5 minutes
- **Memory cap** — 256 MB max to catch leaks early
- **Security hardening** — `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`
- **Journald logging** — all output goes to the journal (no log files to rotate)

## Requirements

- Linux with systemd (Ubuntu 20.04+, Debian 11+, RHEL 8+)
- Python 3.10+ with `.venv` set up (run `./install.sh` first)
- Network access to Orgo API, Telegram API, and SMTP server
