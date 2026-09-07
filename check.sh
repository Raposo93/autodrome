#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "Checking required tools..."

for command in git npm; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Error: '$command' is not installed."
    exit 1
  fi
done

PROJECT_PYTHON="python3"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PROJECT_PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif ! command -v "$PROJECT_PYTHON" >/dev/null 2>&1; then
  echo "Error: 'python3' is not installed."
  exit 1
fi

echo
echo "Running Git checks..."

git --no-pager diff --check

if git --no-pager grep -nE '^(<<<<<<< .+|=======|>>>>>>> .+)$'; then
  echo "Error: unresolved merge conflict markers found."
  exit 1
fi

echo
echo "Running backend tests..."
"$PROJECT_PYTHON" -m pytest

echo
echo "Installing locked frontend dependencies..."
npm ci --prefix frontend

echo
echo "Running frontend tests..."
npm test --prefix frontend

echo
echo "Building frontend..."
npm run build --prefix frontend

echo
echo "All checks passed."
