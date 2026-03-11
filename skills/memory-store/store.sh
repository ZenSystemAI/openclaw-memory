#!/usr/bin/env bash
set -euo pipefail

# === Config ===
OPENAI_URL="https://api.openai.com/v1/embeddings"
OPENAI_MODEL="text-embedding-3-small"
QDRANT_URL="http://127.0.0.1:6333"
QDRANT_COLLECTION="memories"

# Load secrets from .env
if [ -f ~/.openclaw/.env ]; then
  while IFS='=' read -r key value; do
    case "$key" in
      QDRANT_API_KEY|OPENAI_API_KEY) export "$key=$value" ;;
    esac
  done < ~/.openclaw/.env
fi

if [ -z "${QDRANT_API_KEY:-}" ]; then
  echo "ERROR: QDRANT_API_KEY not set" >&2
  exit 2
fi

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY not set" >&2
  exit 2
fi

# === Parse args ===
TEXT=""
CLIENT_ID=""
CATEGORY="semantic"
IMPORTANCE="medium"

while [[ $# -gt 0 ]]; do
  case $1 in
    --text) TEXT="$2"; shift 2 ;;
    --client_id) CLIENT_ID="$2"; shift 2 ;;
    --category) CATEGORY="$2"; shift 2 ;;
    --importance) IMPORTANCE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$TEXT" ] || [ -z "$CLIENT_ID" ]; then
  echo "ERROR: --text and --client_id are required" >&2
  exit 1
fi

# === Credential scrubbing ===
CLEAN_TEXT=$(echo "$TEXT" | sed \
  -e 's/sk-[a-zA-Z0-9_-]\{20,\}/[REDACTED_KEY]/g' \
  -e 's/ghp_[a-zA-Z0-9]\{36,\}/[REDACTED_GH_TOKEN]/g' \
  -e 's/AKIA[A-Z0-9]\{16\}/[REDACTED_AWS_KEY]/g' \
  -e 's/xoxb-[a-zA-Z0-9-]\+/[REDACTED_SLACK_TOKEN]/g' \
  -e 's/xapp-[a-zA-Z0-9-]\+/[REDACTED_SLACK_APP]/g' \
  -e 's/-----BEGIN [A-Z ]*PRIVATE KEY-----/[REDACTED_PRIVATE_KEY]/g' \
  -e 's/[a-zA-Z0-9._%+-]\+@[a-zA-Z0-9.-]\+\.[a-zA-Z]\{2,\}/[REDACTED_EMAIL]/g' \
  -e 's/Bearer [a-zA-Z0-9._-]\+/Bearer [REDACTED]/g' \
)

if [ "$CLEAN_TEXT" != "$TEXT" ]; then
  echo "[WARNING] Credential patterns detected and scrubbed before storage" >&2
fi

# === Generate embedding via OpenAI ===
EMBED_PAYLOAD=$(jq -n --arg text "search_document: ${CLEAN_TEXT}" --arg model "$OPENAI_MODEL" \
  '{"model": $model, "input": $text, "dimensions": 768}')
EMBED_RESPONSE=$(curl -s --max-time 30 "${OPENAI_URL}" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" \
  -d "$EMBED_PAYLOAD")

if ! echo "$EMBED_RESPONSE" | jq -e '.data[0].embedding' > /dev/null 2>&1; then
  echo "ERROR: Embedding generation failed" >&2
  echo "$EMBED_RESPONSE" | head -c 200 >&2
  exit 1
fi

EMBEDDING=$(echo "$EMBED_RESPONSE" | jq -c '.data[0].embedding')

# === Generate unique ID (uint64-safe) ===
POINT_ID_NUM=$(shuf -i 1000000000000-999999999999999999 -n 1)

# === Store in Qdrant ===
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

STORE_RESPONSE=$(curl -s --max-time 10 -X PUT \
  "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/points" \
  -H "api-key: ${QDRANT_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"points\": [{
      \"id\": ${POINT_ID_NUM},
      \"vector\": ${EMBEDDING},
      \"payload\": {
        \"text\": $(echo "$CLEAN_TEXT" | jq -Rs .),
        \"client_id\": \"${CLIENT_ID}\",
        \"category\": \"${CATEGORY}\",
        \"importance\": \"${IMPORTANCE}\",
        \"created_at\": \"${TIMESTAMP}\",
        \"last_accessed\": \"${TIMESTAMP}\",
        \"access_count\": 0,
        \"consolidated\": false
      }
    }]
  }")

if echo "$STORE_RESPONSE" | jq -e '.status == "ok"' > /dev/null 2>&1; then
  echo "Memory stored (id: ${POINT_ID_NUM}, client: ${CLIENT_ID}, category: ${CATEGORY})"
else
  echo "ERROR: Qdrant store failed" >&2
  echo "$STORE_RESPONSE" | sed 's/"api-key": ".*"/"api-key": "REDACTED"/g' >&2
  exit 1
fi
