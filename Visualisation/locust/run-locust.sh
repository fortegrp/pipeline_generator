#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
RUN_ID="${1:-locust-$(date +%Y%m%d%H%M%S)}"

TEST_RUN_ID="${RUN_ID}" \
PROJECT="${PROJECT:-httpbin-demo}" \
ENVIRONMENT="${ENVIRONMENT:-local}" \
SCENARIO="${SCENARIO:-httpbin-smoke}" \
INFLUX_URL="${INFLUX_URL:-http://localhost:8086}" \
INFLUX_ORG="${INFLUX_ORG:-performance}" \
INFLUX_BUCKET="${INFLUX_BUCKET:-performance}" \
INFLUX_TOKEN="${INFLUX_TOKEN:-change-me-super-secret-token}" \
locust -f "${SCRIPT_DIR}/locustfile.py" \
  --headless \
  --users "${USERS:-3}" \
  --spawn-rate "${SPAWN_RATE:-3}" \
  --run-time "${RUN_TIME:-20s}" \
  --host "${TARGET_HOST:-https://httpbin.org}"
