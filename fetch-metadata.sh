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

# Login credentials
API_EMAIL="test@test.com"
API_PASSWORD='Hello123$567'
API_BASE_URL="https://beta.kelvininc.com"

# Create a temporary cookie jar
COOKIE_JAR=$(mktemp)

# Try to login and fetch OpenAPI spec
echo "Authenticating to beta environment..."

# Login to get session cookie (using form data)
login_response=$(curl -s -c "$COOKIE_JAR" -L -X POST \
  "${API_BASE_URL}/auth" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=${API_EMAIL}&password=${API_PASSWORD}" \
  -w "\n%{http_code}")

http_code=$(echo "$login_response" | tail -n1)

if [ "$http_code" = "200" ] || [ "$http_code" = "204" ]; then
  echo "  ✓ Authentication successful"

  # Fetch OpenAPI spec with session cookie
  if curl -s -L -b "$COOKIE_JAR" -c "$COOKIE_JAR" -f "${API_BASE_URL}/api/swagger/openapi.json" > openapi.json 2>/dev/null; then
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
  echo "  ✗ Authentication failed (HTTP $http_code)"
fi

# Cleanup cookie jar
rm -f "$COOKIE_JAR"

echo ""
echo "All done!"
