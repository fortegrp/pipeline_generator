#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

set -a
source .env
set +a

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop and retry." >&2
  exit 1
fi

docker compose up -d --build

echo
echo "Jenkins:  http://localhost:${JENKINS_HTTP_PORT:-8080} (admin / admin)"
echo "InfluxDB: http://localhost:${INFLUXDB_HTTP_PORT:-8086} (${INFLUXDB_ADMIN_USER:-admin} / ${INFLUXDB_ADMIN_PASSWORD:-local-password})"
echo "Grafana:  http://localhost:${GRAFANA_HTTP_PORT:-3000} (${GRAFANA_ADMIN_USER:-admin} / ${GRAFANA_ADMIN_PASSWORD:-admin})"
