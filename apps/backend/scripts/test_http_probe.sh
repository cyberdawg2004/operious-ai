#!/usr/bin/env bash
# Test HTTP probe mode on deployed connector test endpoint
#
# Usage:
#   API_BASE=https://api.example.com/api/v1 ./test_http_probe.sh <tenant_id> <tool_name> <auth_token>
#
# Example:
#   ./test_http_probe.sh tenant-123 httpbin.read "Bearer eyJ..."

set -euo pipefail

TENANT_ID="${1:-}"
TOOL_NAME="${2:-}"
AUTH_TOKEN="${3:-}"

if [[ -z "$TENANT_ID" || -z "$TOOL_NAME" || -z "$AUTH_TOKEN" ]]; then
  echo "Usage: $0 <tenant_id> <tool_name> <auth_token>" >&2
  exit 1
fi

API_BASE="${API_BASE:-https://operious-ai-imad.fly.dev/api/v1}"

echo "=== Testing connector without HTTP probe (TLS only) ===" >&2
curl --fail-with-body --show-error --silent -X POST \
  -H "Authorization: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "$API_BASE/tenant/$TENANT_ID/connectors/$TOOL_NAME/test" \
  | jq .

echo ""
echo "=== Testing connector WITH HTTP probe (real GET) ===" >&2
curl --fail-with-body --show-error --silent -X POST \
  -H "Authorization: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "$API_BASE/tenant/$TENANT_ID/connectors/$TOOL_NAME/test?probe_http=true" \
  | jq .
