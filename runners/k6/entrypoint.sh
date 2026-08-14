#!/usr/bin/env bash
set -euo pipefail

ARTIFACTS_DIR="${ARTIFACTS_DIR:-/artifacts}"
SCRIPTS_DIR="${SCRIPTS_DIR:-/scripts}"
SCRIPT_PATH="${SCRIPT_PATH:-perf_scripts/forte/k6/smoke.js}"
PROJECT="${PROJECT:-forte}"
ENVIRONMENT="${ENVIRONMENT:-local}"
TEST_RUN_ID="${TEST_RUN_ID:-local-001}"
TOOL="${TOOL:-k6}"
SCENARIO="${SCENARIO:-api-smoke}"
RUN_DESCRIPTION="${RUN_DESCRIPTION:-Local performance run}"
JENKINS_BUILD_NUMBER="${JENKINS_BUILD_NUMBER:-local}"
EXECUTION_START_TIMESTAMP="${EXECUTION_START_TIMESTAMP:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
INFLUXDB_URL="${INFLUXDB_URL:-}"
INFLUXDB_BUCKET="${INFLUXDB_BUCKET:-perf_metrics}"
INFLUXDB_ORG="${INFLUXDB_ORG:-forte}"
INFLUXDB_TOKEN="${INFLUXDB_TOKEN:-local-token}"

mkdir -p \
  "${ARTIFACTS_DIR}/logs" \
  "${ARTIFACTS_DIR}/raw" \
  "${ARTIFACTS_DIR}/summaries" \
  "${ARTIFACTS_DIR}/metadata" \
  "${ARTIFACTS_DIR}/reports"

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
  echo "Script not found inside scripts repository: ${SCRIPT_PATH}" | tee "${ARTIFACTS_DIR}/logs/k6-output.log"
  exit 2
fi

output_arg=""
if [ -n "${INFLUXDB_URL}" ]; then
  export K6_INFLUXDB_ADDR="${INFLUXDB_URL}"
  export K6_INFLUXDB_ORGANIZATION="${INFLUXDB_ORG}"
  export K6_INFLUXDB_BUCKET="${INFLUXDB_BUCKET}"
  export K6_INFLUXDB_TOKEN="${INFLUXDB_TOKEN}"
  output_arg="-o xk6-influxdb=${INFLUXDB_URL}"
  echo "k6 metrics streaming enabled: ${INFLUXDB_URL}, bucket=${INFLUXDB_BUCKET}, org=${INFLUXDB_ORG}"
else
  echo "k6 metrics streaming disabled because INFLUXDB_URL is empty"
fi

set +e
# shellcheck disable=SC2086
k6 run ${output_arg} \
  --tag project="${PROJECT}" \
  --tag environment="${ENVIRONMENT}" \
  --tag testRunID="${TEST_RUN_ID}" \
  --tag tool="${TOOL}" \
  --tag scenario="${SCENARIO}" \
  --tag runDescription="${RUN_DESCRIPTION}" \
  --summary-export "${ARTIFACTS_DIR}/summaries/k6-summary.json" \
  "${SCRIPTS_DIR}/${SCRIPT_PATH}" 2>&1 | tee "${ARTIFACTS_DIR}/logs/k6-output.log"
status=$?
set -e

cp "${ARTIFACTS_DIR}/summaries/k6-summary.json" "${ARTIFACTS_DIR}/raw/k6-summary.json" 2>/dev/null || true

cat > "${ARTIFACTS_DIR}/reports/k6-report.html" <<EOF
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>k6 Performance Report - ${TEST_RUN_ID}</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 32px; color: #1f2933; }
    h1 { margin-bottom: 4px; }
    table { border-collapse: collapse; margin: 24px 0; min-width: 520px; }
    td, th { border: 1px solid #d5dce3; padding: 8px 10px; text-align: left; }
    pre { background: #f5f7fa; padding: 16px; overflow: auto; }
  </style>
</head>
<body>
  <h1>k6 Performance Report</h1>
  <table>
    <tr><th>Project</th><td>${PROJECT}</td></tr>
    <tr><th>Environment</th><td>${ENVIRONMENT}</td></tr>
    <tr><th>Test Run ID</th><td>${TEST_RUN_ID}</td></tr>
    <tr><th>Scenario</th><td>${SCENARIO}</td></tr>
    <tr><th>Result</th><td>$(if [ "${status}" -eq 0 ]; then echo PASS; else echo FAIL; fi)</td></tr>
  </table>
  <p>Raw k6 summary is available in <code>summaries/k6-summary.json</code> and <code>raw/k6-summary.json</code>.</p>
</body>
</html>
EOF

cat > "${ARTIFACTS_DIR}/summaries/execution-summary.json" <<EOF
{
  "testRunID": "${TEST_RUN_ID}",
  "tool": "${TOOL}",
  "scenario": "${SCENARIO}",
  "run_description": "${RUN_DESCRIPTION}",
  "exit_code": ${status},
  "result": "$(if [ "${status}" -eq 0 ]; then echo PASS; else echo FAIL; fi)",
  "metrics_streaming": "$(if [ -n "${INFLUXDB_URL}" ]; then echo enabled; else echo disabled; fi)",
  "summary_file": "artifacts/summaries/k6-summary.json",
  "log_file": "artifacts/logs/k6-output.log",
  "html_report": "artifacts/reports/k6-report.html"
}
EOF

exit "${status}"
