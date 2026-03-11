#!/usr/bin/env bash
set -euo pipefail

QDRANT_URL="http://127.0.0.1:6333"
QDRANT_COLLECTION="memories"

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

CLIENT_ID=""
POINT_ID=""
CONFIRM=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --client_id) CLIENT_ID="$2"; shift 2 ;;
    --point_id) POINT_ID="$2"; shift 2 ;;
    --confirm) CONFIRM=true; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

# Validate inputs
if [ -n "$CLIENT_ID" ] && ! echo "$CLIENT_ID" | grep -qE '^[a-zA-Z0-9._-]+$'; then
  echo "ERROR: --client_id contains invalid characters" >&2
  exit 1
fi

if [ -n "$POINT_ID" ] && ! echo "$POINT_ID" | grep -qE '^[0-9]+$'; then
  echo "ERROR: --point_id must be a numeric ID" >&2
  exit 1
fi

if [ -n "$POINT_ID" ]; then
  RESPONSE=$(curl -s --max-time 10 -X POST \
    "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/points/delete" \
    -H "api-key: ${QDRANT_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"points\": [${POINT_ID}]}")

  if echo "$RESPONSE" | jq -e '.status == "ok"' > /dev/null 2>&1; then
    echo "Memory ${POINT_ID} deleted"
    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") DELETE point_id=${POINT_ID}" >> ~/.openclaw/memory-audit.log
  else
    echo "ERROR: Delete failed" >&2
    echo "$RESPONSE" | sed 's/"api-key": ".*"/"api-key": "REDACTED"/g' >&2
    exit 1
  fi
  exit 0
fi

if [ -n "$CLIENT_ID" ]; then
  if [ "$CONFIRM" != "true" ]; then
    COUNT=$(curl -s --max-time 10 -X POST \
      "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/points/count" \
      -H "api-key: ${QDRANT_API_KEY}" \
      -H "Content-Type: application/json" \
      -d "{\"filter\": {\"must\": [{\"key\": \"client_id\", \"match\": {\"value\": \"${CLIENT_ID}\"}}]}}" \
      | jq '.result.count')

    echo "[WARNING] This would delete ${COUNT} memories for client '${CLIENT_ID}'"
    echo "Run with --confirm to proceed (this is permanent)"
    exit 0
  fi

  RESPONSE=$(curl -s --max-time 30 -X POST \
    "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/points/delete" \
    -H "api-key: ${QDRANT_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"filter\": {\"must\": [{\"key\": \"client_id\", \"match\": {\"value\": \"${CLIENT_ID}\"}}]}}")

  if echo "$RESPONSE" | jq -e '.status == "ok"' > /dev/null 2>&1; then
    echo "All memories for client '${CLIENT_ID}' deleted (GDPR erasure)"
    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") GDPR_DELETE client_id=${CLIENT_ID}" >> ~/.openclaw/memory-audit.log
  else
    echo "ERROR: Bulk delete failed" >&2
    exit 1
  fi
  exit 0
fi

echo "ERROR: Must specify --point_id or --client_id" >&2
exit 1
