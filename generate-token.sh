#!/bin/bash
set -e

# Script to generate a Keycloak token for the Kelvin API
# Usage: ./generate-token.sh [environment]

# Fetch platform URLs if not present
if [ ! -f "metadata/platformurls.json" ]; then
  echo "Fetching platform URLs..."
  mkdir -p metadata
  curl -s https://central-server.kelvininc.com/platformurls > metadata/platformurls.json
fi

# Get environment name (default to beta if not specified)
ENVIRONMENT="${1:-beta}"

# Look up the URL for this environment
API_BASE_URL=$(cat metadata/platformurls.json | jq -r ".\"$ENVIRONMENT\"" 2>/dev/null)

if [ "$API_BASE_URL" == "null" ] || [ -z "$API_BASE_URL" ]; then
  echo "Error: Environment '$ENVIRONMENT' not found"
  echo ""
  echo "Available environments:"
  cat metadata/platformurls.json | jq -r 'keys[]' | sort
  exit 1
fi

# Add https:// if not present
if [[ ! $API_BASE_URL =~ ^https?:// ]]; then
  API_BASE_URL="https://$API_BASE_URL"
fi

echo "Generating Keycloak token for: $ENVIRONMENT ($API_BASE_URL)"
echo ""

# Check if credentials are provided
if [ -z "$KEYCLOAK_USERNAME" ] || [ -z "$KEYCLOAK_PASSWORD" ]; then
  echo "Please provide credentials:"
  read -p "Username: " KEYCLOAK_USERNAME
  read -s -p "Password: " KEYCLOAK_PASSWORD
  echo ""
fi

# Check if Python is available
if ! command -v python3 &> /dev/null; then
  echo "Error: python3 is required but not found"
  exit 1
fi

# Generate token using Python Keycloak auth
echo "Authenticating..."
TOKEN=$(python3 -c "
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
        print('Authentication failed', file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1)

if [ $? -eq 0 ]; then
  echo "✓ Authentication successful!"
  echo ""
  echo "Token saved to: token"
  echo "$TOKEN" > token
  echo ""
  echo "You can use this token with:"
  echo "  curl -H \"Authorization: Bearer \$(cat token)\" https://${ENVIRONMENT}.kelvininc.com/api/v4/..."
  echo ""
  echo "Token preview:"
  echo "${TOKEN:0:80}..."
else
  echo "✗ Authentication failed"
  echo "$TOKEN"
  exit 1
fi
