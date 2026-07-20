#!/usr/bin/env sh
set -eu

INFLUX_URL="${INFLUX_URL:-http://localhost:8086}"
INFLUX_ORG="${INFLUX_ORG:-performance}"
INFLUX_BUCKET="${INFLUX_BUCKET:-performance}"
INFLUX_TOKEN="${INFLUX_TOKEN:-change-me-super-secret-token}"

RUN_PREFIX="${1:-local}"
NOW_NS="$(date +%s)000000000"

write_line() {
  curl --fail --silent --show-error \
    --request POST "${INFLUX_URL}/api/v2/write?org=${INFLUX_ORG}&bucket=${INFLUX_BUCKET}&precision=ns" \
    --header "Authorization: Token ${INFLUX_TOKEN}" \
    --data-binary "$1"
}

i=0
while [ "$i" -lt 60 ]; do
  timestamp=$((NOW_NS - (60 - i) * 1000000000))

  for request in GET_/cart POST_/orders GET_/orders_id; do
    case "$request" in
      GET_/cart)
        baseline_offset=0
        candidate_offset=0
        ;;
      POST_/orders)
        baseline_offset=35
        candidate_offset=18
        ;;
      GET_/orders_id)
        baseline_offset=18
        candidate_offset=10
        ;;
    esac

    baseline_latency=$((120 + baseline_offset + (i % 8)))
    candidate_latency=$((95 + candidate_offset + (i % 6)))
    baseline_throughput=$((780 - baseline_offset + (i % 10) * 3))
    candidate_throughput=$((910 - candidate_offset + (i % 12) * 4))

    write_line "performance,run=${RUN_PREFIX}-baseline,suite=checkout,test=submit_order,request=${request} latency_ms=${baseline_latency},throughput_ops_s=${baseline_throughput},error_rate=0.012,cpu_percent=63 ${timestamp}"
    write_line "performance,run=${RUN_PREFIX}-candidate,suite=checkout,test=submit_order,request=${request} latency_ms=${candidate_latency},throughput_ops_s=${candidate_throughput},error_rate=0.006,cpu_percent=58 ${timestamp}"
  done

  i=$((i + 1))
done

echo "Wrote sample metrics for ${RUN_PREFIX}-baseline and ${RUN_PREFIX}-candidate."
