#!/bin/zsh
set -u

PROJECT_DIR="/Users/dev-luv/Sites/uppilot"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"

find_docker() {
  for bin in /usr/local/bin/docker /opt/homebrew/bin/docker /Applications/Docker.app/Contents/Resources/bin/docker; do
    if [[ -x "$bin" ]]; then
      echo "$bin"
      return 0
    fi
  done
  return 1
}

DOCKER_BIN="$(find_docker || true)"
if [[ -z "${DOCKER_BIN:-}" ]]; then
  echo "docker non trovato"
  exit 1
fi

opened_docker=0
for attempt in {1..90}; do
  if "$DOCKER_BIN" info >/dev/null 2>&1; then
    "$DOCKER_BIN" compose -f "$COMPOSE_FILE" up -d redis
    exit $?
  fi

  if [[ "$opened_docker" -eq 0 && -d /Applications/Docker.app ]]; then
    open -ga Docker >/dev/null 2>&1 || true
    opened_docker=1
  fi

  echo "Docker non pronto, ritento ($attempt/90)"
  sleep 5
done

echo "Docker non disponibile dopo il timeout"
exit 1
