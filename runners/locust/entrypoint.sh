#!/usr/bin/env bash
set -euo pipefail

ARTIFACTS_DIR="${ARTIFACTS_DIR:-/artifacts}"
SCRIPTS_DIR="${SCRIPTS_DIR:-/scripts}"
SCRIPT_PATH="${SCRIPT_PATH:-perf_scripts/forte/locust/smoke.py}"
PROJECT="${PROJECT:-forte}"
ENVIRONMENT="${ENVIRONMENT:-local}"
TEST_RUN_ID="${TEST_RUN_ID:-local-001}"
TOOL="${TOOL:-locust}"
SCENARIO="${SCENARIO:-smoke}"
RUN_DESCRIPTION="${RUN_DESCRIPTION:-Local Locust run}"
JENKINS_BUILD_NUMBER="${JENKINS_BUILD_NUMBER:-local}"
EXECUTION_START_TIMESTAMP="${EXECUTION_START_TIMESTAMP:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
INFLUXDB_URL="${INFLUXDB_URL:-}"
INFLUXDB_BUCKET="${INFLUXDB_BUCKET:-perf_metrics}"
INFLUXDB_ORG="${INFLUXDB_ORG:-forte}"
INFLUXDB_TOKEN="${INFLUXDB_TOKEN:-local-token}"
LOCUST_HOST="${LOCUST_HOST:-https://test.k6.io}"
LOCUST_USERS="${LOCUST_USERS:-1}"
LOCUST_SPAWN_RATE="${LOCUST_SPAWN_RATE:-1}"
LOCUST_RUN_TIME="${LOCUST_RUN_TIME:-30s}"

mkdir -p "${ARTIFACTS_DIR}/logs" "${ARTIFACTS_DIR}/raw" "${ARTIFACTS_DIR}/summaries" "${ARTIFACTS_DIR}/metadata" "${ARTIFACTS_DIR}/reports"

cat > "${ARTIFACTS_DIR}/metadata/execution-metadata.json" <<EOF
{
  "project": "${PROJECT}",
  "environment": "${ENVIRONMENT}",
  "testRunID": "${TEST_RUN_ID}",
  "tool": "${TOOL}",
  "scenario": "${SCENARIO}",
  "jenkins_build_number": "${JENKINS_BUILD_NUMBER}",
  "execution_start_timestamp": "${EXECUTION_START_TIMESTAMP}",
  "timestamp": "${EXECUTION_START_TIMESTAMP}",
  "run_description": "${RUN_DESCRIPTION}",
  "script_path": "${SCRIPT_PATH}"
}
EOF

env | sort > "${ARTIFACTS_DIR}/raw/execution-env.txt"

if [ ! -f "${SCRIPTS_DIR}/${SCRIPT_PATH}" ]; then
  echo "Script not found inside scripts repository: ${SCRIPT_PATH}" | tee "${ARTIFACTS_DIR}/logs/locust-output.log"
  exit 2
fi

start_epoch="$(date +%s)"
set +e
locust \
  -f "${SCRIPTS_DIR}/${SCRIPT_PATH}" \
  --headless \
  --host "${LOCUST_HOST}" \
  -u "${LOCUST_USERS}" \
  -r "${LOCUST_SPAWN_RATE}" \
  --run-time "${LOCUST_RUN_TIME}" \
  --csv "${ARTIFACTS_DIR}/raw/locust" \
  --html "${ARTIFACTS_DIR}/reports/locust-report.html" 2>&1 | tee "${ARTIFACTS_DIR}/logs/locust-output.log"
status=$?
set -e
duration_seconds="$(($(date +%s) - start_epoch))"

if [ -n "${INFLUXDB_URL}" ]; then
  python - "${status}" "${duration_seconds}" <<'PY' || true
import os
import sys
import time
import requests

def esc(value):
    return str(value).replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")

status = int(sys.argv[1])
duration = int(sys.argv[2])
url = os.environ["INFLUXDB_URL"].rstrip("/")
org = os.environ["INFLUXDB_ORG"]
bucket = os.environ["INFLUXDB_BUCKET"]
token = os.environ["INFLUXDB_TOKEN"]
line = (
    "performance_tool_run,"
    f"project={esc(os.environ.get('PROJECT', 'forte'))},"
    f"environment={esc(os.environ.get('ENVIRONMENT', 'local'))},"
    f"testRunID={esc(os.environ.get('TEST_RUN_ID', 'local-001'))},"
    "tool=locust,"
    f"scenario={esc(os.environ.get('SCENARIO', 'smoke'))} "
    f"exit_code={status}i,duration_seconds={duration}i {int(time.time())}"
)
requests.post(
    f"{url}/api/v2/write",
    params={"org": org, "bucket": bucket, "precision": "s"},
    headers={"Authorization": f"Token {token}"},
    data=line,
    timeout=3,
)
PY
fi

cat > "${ARTIFACTS_DIR}/summaries/execution-summary.json" <<EOF
{
  "testRunID": "${TEST_RUN_ID}",
  "tool": "${TOOL}",
  "scenario": "${SCENARIO}",
  "run_description": "${RUN_DESCRIPTION}",
  "exit_code": ${status},
  "result": "$(if [ "${status}" -eq 0 ]; then echo PASS; else echo FAIL; fi)",
  "metrics_streaming": "$(if [ -n "${INFLUXDB_URL}" ]; then echo influxdb-v2; else echo disabled; fi)",
  "summary_file": "artifacts/summaries/execution-summary.json",
  "log_file": "artifacts/logs/locust-output.log",
  "html_report": "artifacts/reports/locust-report.html",
  "raw_results": "artifacts/raw/locust_stats.csv"
}
EOF

exit "${status}"
