#!/bin/bash
set -e

echo "Fetching platform URLs and versions..."

# Create metadata directory if it doesn't exist
mkdir -p metadata
status_tmp_file="metadata/status.tmp.jsonl"
status_output_file="metadata/status.json"
status_checked_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
: > "$status_tmp_file"

# Fetch platform URLs and versions
curl -s https://central-server.kelvininc.com/platformurls > metadata/platformurls.json
curl -s https://central-server.kelvininc.com/platformversions > metadata/platformversions.json

echo "Fetching individual environment metadata..."

# Read all environments from platformurls
environments=$(cat metadata/platformurls.json | jq -r 'keys[]')

# Fetch metadata for each environment
for env in $environments; do
  echo "Fetching metadata for: $env"

  # Get the base URL for this environment
  base_url=$(cat metadata/platformurls.json | jq -r ".\"$env\"")

  # Add https:// if not present
  if [[ ! $base_url =~ ^https?:// ]]; then
    base_url="https://$base_url"
  fi

  # Check base URL status (server-side, no CORS)
  status_code=$(curl -s -o /dev/null -w "%{http_code}" -m 10 -L -I "$base_url" || true)
  if [ "$status_code" = "405" ] || [ "$status_code" = "000" ] || [ -z "$status_code" ]; then
    status_code=$(curl -s -o /dev/null -w "%{http_code}" -m 10 -L "$base_url" || true)
  fi
  if [[ ! "$status_code" =~ ^[0-9]+$ ]]; then
    status_code=0
  fi
  if [ "$status_code" -ge 500 ] || [ "$status_code" -eq 0 ]; then
    status="offline"
  else
    status="online"
  fi

  jq -n --arg env "$env" --arg status "$status" --arg code "$status_code" --arg checkedAt "$status_checked_at" \
    '{($env): {status: $status, code: ($code|tonumber), checkedAt: $checkedAt}}' >> "$status_tmp_file"

  # Fetch metadata and save to file
  metadata_url="${base_url}/metadata"
  output_file="metadata/${env}.json"

  if curl -s -f -m 10 "$metadata_url" > "$output_file" 2>/dev/null; then
    echo "  ✓ Successfully fetched metadata for $env"
  else
    echo "  ✗ Failed to fetch metadata for $env (using fallback)"
    # Use version data as fallback
    cat metadata/platformversions.json | jq ".\"$env\"" > "$output_file"
  fi
done

jq -s --arg updatedAt "$status_checked_at" \
  'reduce .[] as $item ({}; . * $item) | {updatedAt: $updatedAt, environments: .}' \
  "$status_tmp_file" > "$status_output_file"
rm -f "$status_tmp_file"

echo "Metadata fetch complete!"
echo "Total environments: $(echo "$environments" | wc -l)"

echo ""
echo "Fetching OpenAPI specification..."

# Use Python script for Keycloak authentication
API_BASE_URL="https://beta.kelvininc.com"

if command -v python3 &> /dev/null; then
  echo "Authenticating to beta environment..."

  # Get access token using Python Keycloak auth
  # Set environment variables for non-interactive auth
  export KEYCLOAK_URL="${API_BASE_URL}"

  # Check if credentials are provided
  if [ -z "$KEYCLOAK_USERNAME" ] || [ -z "$KEYCLOAK_PASSWORD" ]; then
    echo "  ✗ KEYCLOAK_USERNAME and KEYCLOAK_PASSWORD must be set"
    echo "  Skipping OpenAPI fetch"
    echo ""
    echo "All done!"
    exit 0
  fi

  # Run authentication and capture both stdout and stderr
  # Use kelvin-client for API operations (including OpenAPI spec access)
  # Temporarily disable exit on error for auth attempt
  set +e
  AUTH_OUTPUT=$(python3 -c "
import sys
import os
sys.path.insert(0, '.')
try:
    # Use kelvin-client for API operations
    os.environ['KEYCLOAK_CLIENT_ID'] = 'kelvin-client'
    from keycloak_auth import authenticate
    token = authenticate('${API_BASE_URL}', '${KEYCLOAK_USERNAME}', '${KEYCLOAK_PASSWORD}', prompt=False)
    if token:
        print(token)
    else:
        print('Authentication returned None', file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
" 2>&1)

  AUTH_EXIT_CODE=$?
  set -e

  # Check if authentication succeeded
  if [ $AUTH_EXIT_CODE -eq 0 ] && [ -n "$AUTH_OUTPUT" ]; then
    ACCESS_TOKEN="$AUTH_OUTPUT"
    echo "  ✓ Authentication successful"

    # Fetch OpenAPI spec with Bearer token
    if curl -s -L -H "Authorization: Bearer $ACCESS_TOKEN" -f "${API_BASE_URL}/api/swagger/openapi.json" > openapi.json 2>/dev/null; then
      # Check if we got valid JSON
      if jq empty openapi.json 2>/dev/null; then
        echo "  ✓ Successfully fetched OpenAPI specification"

        # Build servers array with actual URLs from platformurls.json
        servers_json=$(cat metadata/platformurls.json | jq '[
          to_entries | .[] | {
            "url": ("https://" + .value + "/api/v4"),
            "description": ("Kelvin Platform - " + .key)
          }
        ] | sort_by(.description)')

        # Modify the servers section with actual environment URLs
        jq --argjson servers "$servers_json" '.servers = $servers' openapi.json > openapi.json.tmp && mv openapi.json.tmp openapi.json

        env_count=$(echo "$servers_json" | jq 'length')
        echo "  ✓ Modified servers with $env_count environment URLs"
        echo "  File size: $(wc -c < openapi.json) bytes"
      else
        echo "  ✗ Failed to fetch OpenAPI specification (invalid JSON)"
        rm -f openapi.json
      fi
    else
      echo "  ✗ Failed to fetch OpenAPI specification"
    fi
  else
    echo "  ✗ Authentication failed"
    echo "  Error output: $AUTH_OUTPUT"
    echo "  Skipping OpenAPI fetch"
  fi
else
  echo "  ✗ Python3 not found, skipping OpenAPI fetch"
fi

echo ""
echo "All done!"
exit 0
