#!/usr/bin/env bash
# backup.sh — Backup the SQLite database
# Run manually or via cron: 0 */6 * * * bash /opt/ai-bob-setup-agent/scripts/backup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DB_FILE="${REPO_ROOT}/data/foundation.db"
BACKUP_DIR="${REPO_ROOT}/backups"
TIMESTAMP=$(date +%Y%m%d-%H%M)

mkdir -p "$BACKUP_DIR"

if [ -f "$DB_FILE" ]; then
    cp "$DB_FILE" "${BACKUP_DIR}/foundation-${TIMESTAMP}.db"
    echo "✓ Backup created: backups/foundation-${TIMESTAMP}.db ($(du -h "$DB_FILE" | cut -f1))"
else
    echo "⚠ No database found at ${DB_FILE}"
fi

# Cleanup backups older than 7 days
find "$BACKUP_DIR" -name "foundation-*.db" -mtime +7 -delete 2>/dev/null
REMAINING=$(ls -1 "$BACKUP_DIR"/foundation-*.db 2>/dev/null | wc -l)
echo "✓ Backups retained: ${REMAINING}"
