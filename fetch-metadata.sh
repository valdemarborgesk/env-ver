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

API_BASE_URL="https://beta.kelvininc.com"

# Fetch OpenAPI spec directly (no authentication required for this endpoint)
if curl -s -L -f "${API_BASE_URL}/api/swagger/openapi.json" > openapi.json 2>/dev/null; then
  # Check if we got valid JSON
  if jq empty openapi.json 2>/dev/null; then
    echo "  ✓ Successfully fetched OpenAPI specification"

    # Get list of environments from platformurls.json
    env_list=$(cat metadata/platformurls.json | jq -r 'keys | sort | @json')

    # Modify the servers section to use {environment}.kelvin.ai with actual environments
    jq --argjson envs "$env_list" '.servers = [{
      "url": "https://{environment}.kelvin.ai/api/v4",
      "description": "Kelvin Platform API",
      "variables": {
        "environment": {
          "default": "beta",
          "description": "Select environment",
          "enum": $envs
        }
      }
    }]' openapi.json > openapi.json.tmp && mv openapi.json.tmp openapi.json

    echo "  ✓ Modified servers to use {environment}.kelvin.ai with $(echo $env_list | jq 'length') environments"
    echo "  File size: $(wc -c < openapi.json) bytes"
  else
    echo "  ✗ Failed to fetch OpenAPI specification (invalid JSON)"
    rm -f openapi.json
  fi
else
  echo "  ✗ Failed to fetch OpenAPI specification"
fi

echo ""
echo "All done!"
