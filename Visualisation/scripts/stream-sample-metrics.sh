#!/usr/bin/env sh
set -eu

INFLUX_URL="${INFLUX_URL:-http://localhost:8086}"
INFLUX_ORG="${INFLUX_ORG:-performance}"
INFLUX_BUCKET="${INFLUX_BUCKET:-performance}"
INFLUX_TOKEN="${INFLUX_TOKEN:-change-me-super-secret-token}"

RUN="${1:-live-demo}"
POINTS="${POINTS:-120}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-1}"

write_line() {
  curl --fail --silent --show-error \
    --request POST "${INFLUX_URL}/api/v2/write?org=${INFLUX_ORG}&bucket=${INFLUX_BUCKET}&precision=ns" \
    --header "Authorization: Token ${INFLUX_TOKEN}" \
    --data-binary "$1"
}

i=0
while [ "$i" -lt "$POINTS" ]; do
  timestamp="$(date +%s)000000000"
  case $((i % 3)) in
    0)
      transaction="GET_/cart"
      offset=0
      ;;
    1)
      transaction="POST_/orders"
      offset=18
      ;;
    *)
      transaction="GET_/orders_id"
      offset=10
      ;;
  esac

  latency=$((95 + offset + (i % 18)))

  status=200
  if [ $((i % 37)) -eq 0 ]; then
    status=500
  fi
  failed=$([ "$status" = 500 ] && echo true || echo false)

  write_line "performance_http_request,project=checkout,environment=local,testRunID=${RUN},tool=sample,scenario=submit_order,transaction=${transaction} response_time_ms=${latency}i,status_code=${status}i,failed=${failed} ${timestamp}"
  echo "Wrote point $((i + 1))/${POINTS} for ${RUN}"

  i=$((i + 1))
  if [ "$i" -lt "$POINTS" ]; then
    sleep "$INTERVAL_SECONDS"
  fi
done
