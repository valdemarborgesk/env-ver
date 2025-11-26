#!/bin/bash

COOKIE_JAR=$(mktemp)
PASSWORD='Hello123$567'

echo "=== Logging in ==="
curl -s -c "$COOKIE_JAR" -L -X POST \
  "https://beta.kelvininc.com/auth" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "email=test@test.com" \
  --data-urlencode "password=$PASSWORD" \
  -w "\nHTTP Status: %{http_code}\n"

echo ""
echo "=== Cookies ==="
cat "$COOKIE_JAR"

echo ""
echo "=== Fetching OpenAPI ==="
curl -s -L -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
  "https://beta.kelvininc.com/api/swagger/openapi.json" \
  | head -20

rm -f "$COOKIE_JAR"
