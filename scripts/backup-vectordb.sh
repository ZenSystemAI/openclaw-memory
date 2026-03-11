#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/vectordb}"
mkdir -p "$BACKUP_DIR"

if [ -f ~/.openclaw/.env ]; then
  while IFS='=' read -r key value; do
    value="${value%"${value##*[![:space:]]}"}"  # trim trailing whitespace
    case "$key" in
      QDRANT_API_KEY) export "$key"="$value" ;;
    esac
  done < ~/.openclaw/.env
fi

if [ -z "${QDRANT_API_KEY:-}" ]; then
  echo "ERROR: QDRANT_API_KEY not set" >&2
  exit 2
fi

SNAP_RESPONSE=$(curl -s --max-time 60 -X POST \
  "http://127.0.0.1:6333/collections/memories/snapshots" \
  -H "api-key: ${QDRANT_API_KEY}")

SNAP_NAME=$(echo "$SNAP_RESPONSE" | jq -r '.result.name')

if [ "$SNAP_NAME" = "null" ] || [ -z "$SNAP_NAME" ]; then
  echo "ERROR: Snapshot creation failed" >&2
  exit 1
fi

curl -s --max-time 120 -o "${BACKUP_DIR}/${SNAP_NAME}" \
  "http://127.0.0.1:6333/collections/memories/snapshots/${SNAP_NAME}" \
  -H "api-key: ${QDRANT_API_KEY}"

gpg --symmetric --cipher-algo AES256 \
  --batch --passphrase-fd 3 3< <(grep -E 'QDRANT_API_KEY' ~/.openclaw/.env | cut -d= -f2) \
  "${BACKUP_DIR}/${SNAP_NAME}"

rm "${BACKUP_DIR}/${SNAP_NAME}"

ls -1t "${BACKUP_DIR}"/*.gpg 2>/dev/null | tail -n +8 | xargs -r rm

echo "Backup saved: ${BACKUP_DIR}/${SNAP_NAME}.gpg"
echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") BACKUP ${SNAP_NAME}.gpg" >> ~/.openclaw/memory-audit.log

unset QDRANT_API_KEY
