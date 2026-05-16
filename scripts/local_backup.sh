#!/usr/bin/env bash
# local_backup.sh — Backs up secrets + database locally
# Run via launchd (macOS) every hour
#
# What it backs up:
# - .env (secrets)
# - config/personal-foundation/config.yaml (credentials)
# - data/ (SQLite database)
# - logs/ (audit log)
#
# Where: ~/aigovops-backups/ (timestamped)

set -e

REPO_DIR="/Users/bobrapp/ai-bob-setup-agent"
BACKUP_BASE="$HOME/aigovops-backups"
TIMESTAMP=$(date +%Y%m%d-%H%M)
BACKUP_DIR="${BACKUP_BASE}/${TIMESTAMP}"

mkdir -p "$BACKUP_DIR"

# Backup secrets (these aren't in git)
[ -f "$REPO_DIR/.env" ] && cp "$REPO_DIR/.env" "$BACKUP_DIR/.env"
[ -f "$REPO_DIR/config/personal-foundation/config.yaml" ] && cp "$REPO_DIR/config/personal-foundation/config.yaml" "$BACKUP_DIR/config.yaml"

# Backup database
[ -f "$REPO_DIR/data/foundation.db" ] && cp "$REPO_DIR/data/foundation.db" "$BACKUP_DIR/foundation.db"

# Backup audit log
[ -d "$REPO_DIR/logs" ] && cp -r "$REPO_DIR/logs" "$BACKUP_DIR/logs"

# Cleanup: keep only last 48 backups (2 days at hourly)
cd "$BACKUP_BASE"
ls -dt */ 2>/dev/null | tail -n +49 | xargs rm -rf 2>/dev/null || true

echo "✓ Backup complete: $BACKUP_DIR ($(du -sh "$BACKUP_DIR" | cut -f1))"
