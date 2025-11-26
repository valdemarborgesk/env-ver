#!/bin/bash
set -e

echo "Fetching platform URLs and versions..."

# Create metadata directory if it doesn't exist
mkdir -p metadata

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
    exit 0
  fi

  # Run authentication and capture both stdout and stderr
  AUTH_OUTPUT=$(python3 -c "
import sys
sys.path.insert(0, '.')
try:
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

  # Check if authentication succeeded
  if [ $AUTH_EXIT_CODE -eq 0 ] && [ -n "$AUTH_OUTPUT" ]; then
    ACCESS_TOKEN="$AUTH_OUTPUT"
    echo "  ✓ Authentication successful"

    # Fetch OpenAPI spec with Bearer token
    if curl -s -L -H "Authorization: Bearer $ACCESS_TOKEN" -f "${API_BASE_URL}/api/swagger/openapi.json" > openapi.json 2>/dev/null; then
      # Check if we got valid JSON
      if jq empty openapi.json 2>/dev/null; then
        echo "  ✓ Successfully fetched OpenAPI specification"
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
  fi
else
  echo "  ✗ Python3 not found, skipping OpenAPI fetch"
fi

echo ""
echo "All done!"
