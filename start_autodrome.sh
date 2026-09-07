#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_PYTHON="$PROJECT_DIRECTORY/.venv/bin/python"
FRONTEND_DIRECTORY="$PROJECT_DIRECTORY/frontend"
VITE_EXECUTABLE="$FRONTEND_DIRECTORY/node_modules/.bin/vite"

cd "$PROJECT_DIRECTORY"

if (( BASH_VERSINFO[0] < 5 )); then
  echo "Error: start_autodrome.sh requires Bash 5 or newer."
  exit 1
fi

if [[ ! -x "$PROJECT_PYTHON" ]]; then
  echo "Error: Python environment not found at .venv/."
  echo "Run: python3.14 -m venv .venv"
  echo "Then: .venv/bin/python -m pip install -r requirements.lock"
  exit 1
fi

for command in node npm ffmpeg; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Error: required command '$command' is not installed."
    exit 1
  fi
done

if [[ ! -x "$VITE_EXECUTABLE" ]]; then
  echo "Error: frontend dependencies are not installed."
  echo "Run: npm ci --prefix frontend"
  exit 1
fi

if ! "$PROJECT_PYTHON" -c '
from autodrome.config import Config, ConfigurationError

try:
    Config().validate()
except ConfigurationError as error:
    raise SystemExit(f"Error: {error}") from error
'; then
  echo "Copy .env.example to .env and complete the required values."
  exit 1
fi

config_value() {
  "$PROJECT_PYTHON" -c '
import sys
from autodrome.config import Config

value = getattr(Config(), sys.argv[1])
print(value or "")
' "$1"
}

dotenv_value() {
  "$PROJECT_PYTHON" -c '
import os
import sys
from dotenv import load_dotenv

load_dotenv()
print(os.getenv(sys.argv[1], ""))
' "$1"
}

BACKEND_HOST="$(config_value api_host)"
BACKEND_PORT="$(config_value api_port)"

if [[ -z "${VITE_API_TOKEN:-}" ]]; then
  VITE_API_TOKEN="$(dotenv_value VITE_API_TOKEN)"
fi
if [[ -z "$VITE_API_TOKEN" ]]; then
  VITE_API_TOKEN="$(config_value api_token)"
fi
export VITE_API_TOKEN

if [[ -z "${VITE_HOST:-}" ]]; then
  VITE_HOST="$(dotenv_value VITE_HOST)"
fi
VITE_HOST="${VITE_HOST:-127.0.0.1}"
export VITE_HOST

if [[ -z "${VITE_PORT:-}" ]]; then
  VITE_PORT="$(dotenv_value VITE_PORT)"
fi
VITE_PORT="${VITE_PORT:-5173}"
if [[ ! "$VITE_PORT" =~ ^[0-9]+$ ]] \
  || (( 10#$VITE_PORT < 1 || 10#$VITE_PORT > 65535 )); then
  echo "Error: VITE_PORT must be an integer between 1 and 65535."
  exit 1
fi
export VITE_PORT

if [[ -z "${VITE_IP_HOST:-}" ]]; then
  VITE_IP_HOST="$(dotenv_value VITE_IP_HOST)"
fi
if [[ -z "$VITE_IP_HOST" ]]; then
  case "$BACKEND_HOST" in
    0.0.0.0 | ::)
      PROXY_HOST="127.0.0.1"
      ;;
    ::1)
      PROXY_HOST="[::1]"
      ;;
    *)
      PROXY_HOST="$BACKEND_HOST"
      ;;
  esac
  VITE_IP_HOST="http://$PROXY_HOST:$BACKEND_PORT"
fi
export VITE_IP_HOST

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  trap - EXIT INT TERM
  for process_id in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$process_id" ]] && kill -0 "$process_id" 2>/dev/null; then
      kill "$process_id" 2>/dev/null || true
    fi
  done
  for process_id in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$process_id" ]]; then
      wait "$process_id" 2>/dev/null || true
    fi
  done
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Starting FastAPI on http://$BACKEND_HOST:$BACKEND_PORT"
(
  cd "$PROJECT_DIRECTORY"
  exec "$PROJECT_PYTHON" -m uvicorn app:app \
    --host "$BACKEND_HOST" \
    --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

echo "Starting Vue on http://$VITE_HOST:$VITE_PORT"
(
  cd "$FRONTEND_DIRECTORY"
  exec "$VITE_EXECUTABLE" \
    --host "$VITE_HOST" \
    --port "$VITE_PORT" \
    --strictPort
) &
FRONTEND_PID=$!

echo "Autodrome is running. Press Ctrl+C to stop both processes."

set +e
wait -n "$BACKEND_PID" "$FRONTEND_PID"
EXIT_STATUS=$?
set -e

echo "One Autodrome process stopped; shutting down the other."
exit "$EXIT_STATUS"
