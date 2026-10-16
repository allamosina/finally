#!/usr/bin/env bash
# Start FinAlly in Docker (macOS/Linux). Idempotent. Usage: start_mac.sh [--build] [--no-open]
set -euo pipefail

IMAGE="finally"
NAME="finally"
PORT=8000
URL="http://localhost:${PORT}"
TIMEOUT=90

BUILD=0
OPEN=1
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --no-open) OPEN=0 ;;
    -h|--help) echo "Usage: $0 [--build] [--no-open]"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v docker >/dev/null 2>&1 || { echo "docker not found. Install Docker first." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is not running." >&2; exit 1; }

mkdir -p db

if [ "$BUILD" -eq 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building image '$IMAGE'..."
  docker build -t "$IMAGE" .
fi

ENV_ARGS=()
if [ -f .env ]; then
  ENV_ARGS=(--env-file .env)
else
  echo "Warning: .env not found; copy .env.example to .env. Chat will report 'LLM not configured' unless LLM_MOCK=true." >&2
fi

# Idempotent: replace any existing container of the same name
if docker container inspect "$NAME" >/dev/null 2>&1; then
  echo "Replacing existing container '$NAME'..."
  docker rm -f "$NAME" >/dev/null
fi

echo "Starting container '$NAME'..."
docker run -d --rm --name "$NAME" \
  -v "$ROOT/db:/app/db" \
  -p "${PORT}:8000" \
  ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} \
  "$IMAGE" >/dev/null

echo "Waiting for ${URL}/api/health (up to ${TIMEOUT}s)..."
deadline=$((SECONDS + TIMEOUT))
until curl -fsS "${URL}/api/health" 2>/dev/null | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'; do
  if ! docker container inspect "$NAME" >/dev/null 2>&1; then
    echo "Container exited before becoming healthy. Check: docker logs $NAME" >&2
    exit 1
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "Timed out waiting for health. Logs:" >&2
    docker logs --tail 50 "$NAME" >&2 || true
    exit 1
  fi
  sleep 1
done

echo "FinAlly is running at ${URL}"
if [ "$OPEN" -eq 1 ]; then
  if command -v open >/dev/null 2>&1; then
    open "$URL" || echo "Could not open the browser; visit ${URL}"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || echo "Could not open the browser; visit ${URL}"
  fi
fi
