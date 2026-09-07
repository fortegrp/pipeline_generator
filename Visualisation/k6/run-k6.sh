#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
RUN_ID="${1:-k6-$(date +%Y%m%d%H%M%S)}"

INFLUX_HOST="${INFLUX_HOST:-localhost:8086}"
INFLUX_BUCKET="${INFLUX_BUCKET:-performance}"
INFLUX_TOKEN="${INFLUX_TOKEN:-change-me-super-secret-token}"

# k6's built-in InfluxDB output only speaks the v1 write protocol, so this goes through
# InfluxDB v2's v1-compatibility API (/write?db=...), which requires a DBRP mapping from that
# v1 "database" name to the v2 bucket. InfluxDB auto-creates one named after the bucket when
# the bucket itself is created (as ours is, via DOCKER_INFLUXDB_INIT_BUCKET) - if you're
# pointing this at a bucket that was created differently, create the mapping yourself first:
# influx v1 dbrp create --db <bucket> --rp autogen --bucket-id <id> --default
TEST_RUN_ID="${RUN_ID}" \
PROJECT="${PROJECT:-httpbin-demo}" \
ENVIRONMENT="${ENVIRONMENT:-local}" \
SCENARIO="${SCENARIO:-httpbin-smoke}" \
USERS="${USERS:-3}" \
RUN_TIME="${RUN_TIME:-20s}" \
k6 run --out "influxdb=http://any:${INFLUX_TOKEN}@${INFLUX_HOST}/${INFLUX_BUCKET}" \
  "${SCRIPT_DIR}/httpbin-smoke.js"
