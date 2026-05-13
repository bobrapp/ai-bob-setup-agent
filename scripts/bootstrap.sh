#!/usr/bin/env bash
# Lightweight OS-level dependency check.
# Called by install.sh; safe to run independently.
set -euo pipefail

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing: $1" >&2
    return 1
  fi
}

missing=0
for cmd in python3 git curl; do
  if ! need_cmd "$cmd"; then
    missing=$((missing + 1))
  fi
done

if (( missing > 0 )); then
  echo "Install the missing tools above, then re-run." >&2
  exit 1
fi

echo "Bootstrap dependencies present."
