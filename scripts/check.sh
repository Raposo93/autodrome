#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "Checking required tools..."

for command in git python3 npm; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Error: '$command' is not installed."
    exit 1
  fi
done

echo
echo "Running Git checks..."

git --no-pager diff --check

if git --no-pager grep -nE '^(<<<<<<< .+|=======|>>>>>>> .+)$'; then
  echo "Error: unresolved merge conflict markers found."
  exit 1
fi

echo
echo "Running backend tests..."
python3 -m pytest

echo
echo "Building frontend..."
(
  cd frontend
  npm run build
)

echo
echo "All checks passed."
