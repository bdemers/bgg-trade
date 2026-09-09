#!/bin/bash
# Helper script to review and edit the trade matrix in a browser.
# Usage:
#   ./review.sh              (open the matrix, edits save as you click)
#   ./review.sh --port 9000  (serve somewhere else)
#   ./review.sh --no-browser (print the URL instead of opening it)
#
# Run ./run.sh first: this page reads the plan that produces.
# Run ./run.sh again afterwards to fold your edits into the report.

# Work from the repo root so the plan, the caches and the overrides file
# resolve no matter where this is invoked from.
cd "$(dirname "$0")" || exit 1

# Load environment variables from .env if it exists (same loader as run.sh)
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "$line" ]] && continue
    eval "export $line"
  done < .env
fi

python3 review.py "$@"
