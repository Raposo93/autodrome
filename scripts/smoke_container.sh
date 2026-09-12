#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:?Usage: smoke_container.sh IMAGE [EXPECTED_COMMIT]}"
EXPECTED_COMMIT="${2:-}"
CONTAINER="autodrome-smoke-$$"
API_TOKEN="container-smoke-token-0123456789abcdef"

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --detach --name "$CONTAINER" \
  --env API_TOKEN="$API_TOKEN" \
  --env CONTACT_EMAIL=container-smoke@example.test \
  --env GOOGLE_API_KEY=container-smoke-key \
  "$IMAGE" >/dev/null

health="starting"
for _ in {1..30}; do
  health="$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER")"
  case "$health" in
    healthy) break ;;
    unhealthy)
      docker logs "$CONTAINER"
      exit 1
      ;;
  esac
  sleep 2
done

if [[ "$health" != "healthy" ]]; then
  docker logs "$CONTAINER"
  echo "Error: container did not become healthy"
  exit 1
fi

docker exec \
  --env API_TOKEN="$API_TOKEN" \
  --env EXPECTED_AUTODROME_COMMIT="$EXPECTED_COMMIT" \
  --interactive "$CONTAINER" python - < scripts/smoke_container.py
