#!/usr/bin/env bash
set -euo pipefail

ARTIFACTS_DIR="${ARTIFACTS_DIR:-/artifacts}"
SCRIPTS_DIR="${SCRIPTS_DIR:-/scripts}"
SCRIPT_PATH="${SCRIPT_PATH:-perf_scripts/forte/jmeter/smoke.jmx}"
PROJECT="${PROJECT:-forte}"
ENVIRONMENT="${ENVIRONMENT:-local}"
TEST_RUN_ID="${TEST_RUN_ID:-local-001}"
TOOL="${TOOL:-jmeter}"
SCENARIO="${SCENARIO:-smoke}"
RUN_DESCRIPTION="${RUN_DESCRIPTION:-Local JMeter run}"
JENKINS_BUILD_NUMBER="${JENKINS_BUILD_NUMBER:-local}"
EXECUTION_START_TIMESTAMP="${EXECUTION_START_TIMESTAMP:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
INFLUXDB_URL="${INFLUXDB_URL:-}"
INFLUXDB_BUCKET="${INFLUXDB_BUCKET:-perf_metrics}"
INFLUXDB_ORG="${INFLUXDB_ORG:-forte}"
INFLUXDB_TOKEN="${INFLUXDB_TOKEN:-local-token}"

mkdir -p "${ARTIFACTS_DIR}/logs" "${ARTIFACTS_DIR}/raw" "${ARTIFACTS_DIR}/summaries" "${ARTIFACTS_DIR}/metadata" "${ARTIFACTS_DIR}/reports"

escape_tag() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/,/\\,/g; s/ /\\ /g; s/=/\\=/g'
}

write_influx_point() {
  if [ -z "${INFLUXDB_URL}" ]; then
    return 0
  fi

  curl -fsS -X POST "${INFLUXDB_URL}/api/v2/write?org=${INFLUXDB_ORG}&bucket=${INFLUXDB_BUCKET}&precision=ms" \
    -H "Authorization: Token ${INFLUXDB_TOKEN}" \
    --data-binary "$1" >/dev/null 2>>"${ARTIFACTS_DIR}/logs/influx-writer.log" || true
}

stream_jmeter_jtl_to_influx() {
  if [ -z "${INFLUXDB_URL}" ]; then
    return 0
  fi

  jtl_file="${ARTIFACTS_DIR}/raw/jmeter-results.jtl"
  echo "Streaming JMeter samples to InfluxDB: ${INFLUXDB_URL}, bucket=${INFLUXDB_BUCKET}, org=${INFLUXDB_ORG}" >> "${ARTIFACTS_DIR}/logs/influx-writer.log"

  while [ ! -f "${jtl_file}" ]; do
    sleep 1
  done

  tail -n +2 -F "${jtl_file}" 2>/dev/null | while IFS= read -r row; do
    [ -n "${row}" ] || continue

    timestamp="$(printf '%s' "${row}" | awk -F',' '{print $1}')"
    elapsed="$(printf '%s' "${row}" | awk -F',' '{print $2}')"
    label="$(printf '%s' "${row}" | awk -F',' '{print $3}')"
    response_code="$(printf '%s' "${row}" | awk -F',' '{print $4}')"
    success="$(printf '%s' "${row}" | awk -F',' '{print $8}')"

    case "${timestamp}" in ''|*[!0-9]*) continue ;; esac
    case "${elapsed}" in ''|*[!0-9]*) elapsed=0 ;; esac
    case "${response_code}" in ''|*[!0-9]*) response_code=0 ;; esac

    if [ "${success}" = "true" ]; then
      failed=false
    else
      failed=true
    fi

    line="performance_http_request,project=$(escape_tag "${PROJECT}"),environment=$(escape_tag "${ENVIRONMENT}"),testRunID=$(escape_tag "${TEST_RUN_ID}"),tool=jmeter,scenario=$(escape_tag "${SCENARIO}"),transaction=$(escape_tag "${label}") response_time_ms=${elapsed}i,status_code=${response_code}i,failed=${failed} ${timestamp}"
    write_influx_point "${line}"
  done
}

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
  echo "Script not found inside scripts repository: ${SCRIPT_PATH}" | tee "${ARTIFACTS_DIR}/logs/jmeter-output.log"
  exit 2
fi

start_epoch="$(date +%s)"
stream_jmeter_jtl_to_influx &
influx_stream_pid="$!"

set +e
jmeter -n \
  -t "${SCRIPTS_DIR}/${SCRIPT_PATH}" \
  -l "${ARTIFACTS_DIR}/raw/jmeter-results.jtl" \
  -j "${ARTIFACTS_DIR}/logs/jmeter-engine.log" \
  -e -o "${ARTIFACTS_DIR}/reports/jmeter-dashboard" \
  -Jjmeter.save.saveservice.output_format=csv \
  -Jjmeter.save.saveservice.print_field_names=true \
  -Jjmeter.save.saveservice.time=true \
  -Jjmeter.save.saveservice.timestamp_format=ms \
  -Jjmeter.save.saveservice.elapsed=true \
  -Jjmeter.save.saveservice.label=true \
  -Jjmeter.save.saveservice.response_code=true \
  -Jjmeter.save.saveservice.successful=true \
  -Jjmeter.save.saveservice.thread_name=true \
  -Jjmeter.save.saveservice.bytes=true \
  -Jjmeter.save.saveservice.sent_bytes=true \
  -Jjmeter.save.saveservice.latency=true \
  -Jjmeter.save.saveservice.connect_time=true \
  -Jproject="${PROJECT}" \
  -Jenvironment="${ENVIRONMENT}" \
  -JtestRunID="${TEST_RUN_ID}" \
  -Jtool="${TOOL}" \
  -Jscenario="${SCENARIO}" \
  -JrunDescription="${RUN_DESCRIPTION}" 2>&1 | tee "${ARTIFACTS_DIR}/logs/jmeter-output.log"
status=$?
set -e
duration_seconds="$(($(date +%s) - start_epoch))"
sleep 1
kill "${influx_stream_pid}" >/dev/null 2>&1 || true

if [ -n "${INFLUXDB_URL}" ]; then
  line="performance_tool_run,project=${PROJECT},environment=${ENVIRONMENT},testRunID=${TEST_RUN_ID},tool=${TOOL},scenario=${SCENARIO} exit_code=${status}i,duration_seconds=${duration_seconds}i"
  write_influx_point "${line}"
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
  "log_file": "artifacts/logs/jmeter-output.log",
  "html_report": "artifacts/reports/jmeter-dashboard/index.html",
  "raw_results": "artifacts/raw/jmeter-results.jtl"
}
EOF

exit "${status}"
