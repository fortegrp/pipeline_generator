#!/usr/bin/env bash
set -euo pipefail

ARTIFACTS_DIR="${ARTIFACTS_DIR:-/artifacts}"
SCRIPTS_DIR="${SCRIPTS_DIR:-/scripts}"
SCRIPT_PATH="${SCRIPT_PATH:-perf_scripts/forte/gatling/ForteSmokeSimulation.scala}"
PROJECT="${PROJECT:-forte}"
ENVIRONMENT="${ENVIRONMENT:-local}"
TEST_RUN_ID="${TEST_RUN_ID:-local-001}"
TOOL="${TOOL:-gatling}"
SCENARIO="${SCENARIO:-smoke}"
RUN_DESCRIPTION="${RUN_DESCRIPTION:-Local Gatling run}"
JENKINS_BUILD_NUMBER="${JENKINS_BUILD_NUMBER:-local}"
EXECUTION_START_TIMESTAMP="${EXECUTION_START_TIMESTAMP:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
INFLUXDB_URL="${INFLUXDB_URL:-}"
INFLUXDB_BUCKET="${INFLUXDB_BUCKET:-perf_metrics}"
INFLUXDB_ORG="${INFLUXDB_ORG:-forte}"
INFLUXDB_TOKEN="${INFLUXDB_TOKEN:-local-token}"

mkdir -p "${ARTIFACTS_DIR}/logs" "${ARTIFACTS_DIR}/raw" "${ARTIFACTS_DIR}/summaries" "${ARTIFACTS_DIR}/metadata" "${ARTIFACTS_DIR}/reports" /tmp/gatling-user-files/simulations

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

stream_gatling_log_to_influx() {
  if [ -z "${INFLUXDB_URL}" ]; then
    return 0
  fi

  echo "Streaming Gatling request samples to InfluxDB: ${INFLUXDB_URL}, bucket=${INFLUXDB_BUCKET}, org=${INFLUXDB_ORG}" >> "${ARTIFACTS_DIR}/logs/influx-writer.log"

  while true; do
    simulation_log="$(find "${ARTIFACTS_DIR}/reports" -name simulation.log -type f 2>/dev/null | head -1 || true)"
    if [ -n "${simulation_log}" ]; then
      break
    fi
    sleep 1
  done

  tail -n +1 -F "${simulation_log}" 2>/dev/null | while IFS= read -r row; do
    case "${row}" in
      REQUEST$'\t'*)
        name="$(printf '%s' "${row}" | awk -F'\t' '{print $3}')"
        start_ms="$(printf '%s' "${row}" | awk -F'\t' '{print $4}')"
        end_ms="$(printf '%s' "${row}" | awk -F'\t' '{print $5}')"
        result="$(printf '%s' "${row}" | awk -F'\t' '{print $6}')"
        ;;
      *) continue ;;
    esac

    case "${start_ms}" in ''|*[!0-9]*) continue ;; esac
    case "${end_ms}" in ''|*[!0-9]*) continue ;; esac

    elapsed="$((end_ms - start_ms))"
    if [ "${result}" = "OK" ]; then
      failed=false
      status_code=200
    else
      failed=true
      status_code=500
    fi

    line="performance_http_request,project=$(escape_tag "${PROJECT}"),environment=$(escape_tag "${ENVIRONMENT}"),testRunID=$(escape_tag "${TEST_RUN_ID}"),tool=gatling,scenario=$(escape_tag "${SCENARIO}"),transaction=$(escape_tag "${name}") response_time_ms=${elapsed}i,status_code=${status_code}i,failed=${failed} ${end_ms}"
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
  echo "Script not found inside scripts repository: ${SCRIPT_PATH}" | tee "${ARTIFACTS_DIR}/logs/gatling-output.log"
  exit 2
fi

cp "${SCRIPTS_DIR}/${SCRIPT_PATH}" /tmp/gatling-user-files/simulations/
simulation_class="$(basename "${SCRIPT_PATH}" .scala)"

start_epoch="$(date +%s)"
stream_gatling_log_to_influx &
influx_stream_pid="$!"

set +e
gatling.sh \
  --run-mode local \
  -sf /tmp/gatling-user-files/simulations \
  -rf "${ARTIFACTS_DIR}/reports" \
  -s "${simulation_class}" 2>&1 | tee "${ARTIFACTS_DIR}/logs/gatling-output.log"
status=$?
set -e
duration_seconds="$(($(date +%s) - start_epoch))"
sleep 1
kill "${influx_stream_pid}" >/dev/null 2>&1 || true
find "${ARTIFACTS_DIR}/reports" -name simulation.log -type f -exec cp {} "${ARTIFACTS_DIR}/raw/gatling-simulation.log" \; 2>/dev/null || true
find "${ARTIFACTS_DIR}/reports" -name index.html -type f | head -1 | while IFS= read -r report_index; do
  cp "${report_index}" "${ARTIFACTS_DIR}/reports/index.html"
done

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
  "log_file": "artifacts/logs/gatling-output.log",
  "html_report": "artifacts/reports/index.html",
  "raw_results": "artifacts/raw/gatling-simulation.log"
}
EOF

exit "${status}"
