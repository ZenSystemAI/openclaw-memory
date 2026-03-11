#!/usr/bin/env bash
set -euo pipefail

# === Config ===
OPENAI_URL="https://api.openai.com/v1/embeddings"
OPENAI_MODEL="text-embedding-3-small"
QDRANT_URL="http://127.0.0.1:6333"
QDRANT_COLLECTION="docs"

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
QUERY=""
SOURCE=""
LIMIT=5

while [[ $# -gt 0 ]]; do
  case $1 in
    --query) QUERY="$2"; shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$QUERY" ]; then
  echo "ERROR: --query is required" >&2
  exit 1
fi

# === Generate embedding via OpenAI ===
EMBED_PAYLOAD=$(jq -n --arg text "search_query: ${QUERY}" --arg model "$OPENAI_MODEL" \
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

# === Build filter ===
if [ -n "$SOURCE" ]; then
  FILTER="{\"must\": [{\"key\": \"source\", \"match\": {\"value\": \"${SOURCE}\"}}]}"
else
  FILTER="{}"
fi

# === Search Qdrant ===
SEARCH_BODY="{
  \"vector\": ${EMBEDDING},
  \"limit\": ${LIMIT},
  \"with_payload\": true,
  \"score_threshold\": 0.35"

if [ -n "$SOURCE" ]; then
  SEARCH_BODY="${SEARCH_BODY}, \"filter\": ${FILTER}"
fi

SEARCH_BODY="${SEARCH_BODY}}"

SEARCH_RESPONSE=$(curl -s --max-time 10 -X POST \
  "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/points/search" \
  -H "api-key: ${QDRANT_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$SEARCH_BODY")

# === Format results ===
RESULT_COUNT=$(echo "$SEARCH_RESPONSE" | jq '.result | length')

if [ "$RESULT_COUNT" = "0" ] || [ "$RESULT_COUNT" = "null" ]; then
  echo "No documentation found matching: ${QUERY}"
  if [ -n "$SOURCE" ]; then
    echo "(filtered to source: ${SOURCE})"
  fi
  exit 0
fi

echo "[DOCS_START]"
echo "Query: ${QUERY}"
if [ -n "$SOURCE" ]; then
  echo "Source filter: ${SOURCE}"
fi
echo "Results: ${RESULT_COUNT}"
echo ""

echo "$SEARCH_RESPONSE" | jq -r '.result[] |
  "---\n[" + .payload.source + "] " + .payload.section + "\nScore: " + (.score | tostring | .[0:5]) + " | Type: " + .payload.content_type + "\nURL: " + .payload.url + "\n\n" + .payload.text + "\n"'

echo "[DOCS_END]"
