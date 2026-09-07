#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST="${API_HOST:-127.0.0.1}"
BACKEND_PORT="${API_PORT:-5000}"
PROVIDED_API_TOKEN="${API_TOKEN:-}"

if [[ "$BACKEND_HOST" != "127.0.0.1" \
  && "$BACKEND_HOST" != "::1" \
  && "$BACKEND_HOST" != "localhost" \
  && ${#PROVIDED_API_TOKEN} -lt 32 ]]; then
  echo "Error: API_TOKEN must contain at least 32 characters when API_HOST is not loopback."
  exit 1
fi

export API_HOST="$BACKEND_HOST"
export API_PORT="$BACKEND_PORT"

# Lanzar backend en segundo plano y guardar su PID
(
  cd "$PROJECT_DIRECTORY"
  source .venv/bin/activate
  nohup uvicorn app:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT" > /tmp/autodrome_backend.log 2>&1 &
  echo $! > /tmp/autodrome_backend.pid
)

# Lanzar frontend en segundo plano y guardar su PID
(
  cd "$PROJECT_DIRECTORY/frontend"
  nohup npm run dev > /tmp/autodrome_frontend.log 2>&1 &
  echo $! > /tmp/autodrome_frontend.pid
)

echo "Autodrome backend and frontend started in the background."
