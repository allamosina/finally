#!/usr/bin/env bash
# Stop and remove the FinAlly container. Never touches db/. Idempotent.
set -euo pipefail
NAME="finally"
command -v docker >/dev/null 2>&1 || { echo "docker not found." >&2; exit 1; }
if docker container inspect "$NAME" >/dev/null 2>&1; then
  docker rm -f "$NAME" >/dev/null
  echo "Stopped and removed container '$NAME'. Data in db/ is untouched."
else
  echo "Container '$NAME' is not running."
fi
