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
n=0
while [ "$i" -lt 60 ]; do
  timestamp=$((NOW_NS - (60 - i) * 1000000000))

  for transaction in GET_/cart POST_/orders GET_/orders_id; do
    case "$transaction" in
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

    # n runs 0-179 across all (i, transaction) points, so these moduli fire
    # several times spread across the run instead of only once at i=0.
    baseline_status=200
    if [ $((n % 45)) -eq 0 ]; then
      baseline_status=500
    fi
    baseline_failed=$([ "$baseline_status" = 500 ] && echo true || echo false)

    candidate_status=200
    if [ $((n % 90)) -eq 0 ]; then
      candidate_status=500
    fi
    candidate_failed=$([ "$candidate_status" = 500 ] && echo true || echo false)

    write_line "performance_http_request,project=checkout,environment=local,testRunID=${RUN_PREFIX}-baseline,tool=sample,scenario=submit_order,transaction=${transaction} response_time_ms=${baseline_latency}i,status_code=${baseline_status}i,failed=${baseline_failed} ${timestamp}"
    write_line "performance_http_request,project=checkout,environment=local,testRunID=${RUN_PREFIX}-candidate,tool=sample,scenario=submit_order,transaction=${transaction} response_time_ms=${candidate_latency}i,status_code=${candidate_status}i,failed=${candidate_failed} ${timestamp}"

    n=$((n + 1))
  done

  i=$((i + 1))
done

echo "Wrote sample metrics for ${RUN_PREFIX}-baseline and ${RUN_PREFIX}-candidate."
