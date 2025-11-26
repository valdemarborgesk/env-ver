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
