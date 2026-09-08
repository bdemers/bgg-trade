#!/bin/bash
# Helper script to execute BGG matching
# Usage:
#   ./run.sh                  (Run matching using cached data)
#   ./run.sh --refresh-geeklist   (Refresh math trade data from BGG and match)
#   ./run.sh --refresh-collection (Refresh your collection data from BGG and match)
#   ./run.sh --refresh-collection --refresh-geeklist (Refresh everything)

# Work from the repo root so .env, preferences.toml and the cache dirs resolve
# no matter where this is invoked from.
cd "$(dirname "$0")" || exit 1

# Load environment variables from .env if it exists
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "$line" ]] && continue
    eval "export $line"
  done < .env
fi

python3 bgg_match.py "$@"
