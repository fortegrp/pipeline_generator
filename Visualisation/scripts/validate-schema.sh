#!/usr/bin/env sh
set -eu

# Post-write schema gate: queries InfluxDB for one testRunID and checks it actually conforms
# to docs/metric-model.md - the six required tags and three required fields for
# performance_http_request, or just the six required tags for k6's native metrics. InfluxDB
# itself can't validate writes (OSS has no write-time hooks), so this is what "enforce the
# schema" means in this stack: run it after any tool's run (or as a CI step) and it exits
# non-zero if that run's data doesn't conform.

INFLUX_URL="${INFLUX_URL:-http://localhost:8086}"
INFLUX_ORG="${INFLUX_ORG:-performance}"
INFLUX_BUCKET="${INFLUX_BUCKET:-performance}"
INFLUX_TOKEN="${INFLUX_TOKEN:-change-me-super-secret-token}"

RUN_ID="${1:?usage: validate-schema.sh <testRunID>}"

violations=0
fail() {
  echo "FAIL: $1"
  violations=$((violations + 1))
}
pass() {
  echo "OK:   $1"
}

# Extracts the _value column from the last data row of a Flux CSV response.
# Prints 0 if the response has no data rows (query matched nothing).
flux_value() {
  curl -s \
    --header "Authorization: Token ${INFLUX_TOKEN}" \
    --header "Accept: application/csv" \
    --header "Content-Type: application/vnd.flux" \
    --data "$1" \
    "${INFLUX_URL}/api/v2/query?org=${INFLUX_ORG}" \
  | awk -F',' '
      { sub(/\r$/, "") }
      /^#/ { next }
      NF <= 1 { next }
      !header_done {
        for (i = 1; i <= NF; i++) if ($i == "_value") value_col = i
        header_done = 1
        next
      }
      { last = $value_col }
      END { if (last != "") print last; else print "0" }
    '
}

count_query() {
  # $1 = measurement, $2 = field
  flux_value "
from(bucket: \"${INFLUX_BUCKET}\")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == \"$1\")
  |> filter(fn: (r) => r.testRunID == \"${RUN_ID}\")
  |> filter(fn: (r) => r._field == \"$2\")
  |> count()
  |> group()
  |> sum()
"
}

tagged_count_query() {
  # $1 = measurement, $2 = field, $3 = tag
  flux_value "
from(bucket: \"${INFLUX_BUCKET}\")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == \"$1\")
  |> filter(fn: (r) => r.testRunID == \"${RUN_ID}\")
  |> filter(fn: (r) => r._field == \"$2\")
  |> filter(fn: (r) => exists r[\"$3\"])
  |> count()
  |> group()
  |> sum()
"
}

echo "Validating schema for testRunID=${RUN_ID}"
echo

http_count="$(count_query performance_http_request response_time_ms)"

if [ "${http_count}" -gt 0 ]; then
  MODE="performance_http_request"
else
  k6_count="$(count_query http_req_duration value)"
  if [ "${k6_count}" -gt 0 ]; then
    MODE="k6"
  else
    echo "No data found for testRunID=${RUN_ID} in either performance_http_request or k6's http_req_duration."
    exit 2
  fi
fi

echo "Detected mode: ${MODE}"
echo

if [ "${MODE}" = "performance_http_request" ]; then
  total="${http_count}"
  echo "Total samples (response_time_ms): ${total}"

  for field in status_code failed; do
    count="$(count_query performance_http_request "${field}")"
    if [ "${count}" = "${total}" ]; then
      pass "field ${field} present on all ${total} samples"
    else
      fail "field ${field} present on only ${count}/${total} samples"
    fi
  done

  # Type check: this map only succeeds if every failed value is already boolean. In practice
  # InfluxDB itself already rejects (422) any write where a field's type doesn't match the
  # type that field was first written as, for that measurement - confirmed by testing a
  # conflicting write directly. So this mostly reconfirms that guarantee rather than catching
  # something that could otherwise slip through; it stays as a direct, explicit check on the
  # data actually stored rather than trusting that guarantee blindly.
  bool_status="$(curl -s -o /dev/null -w '%{http_code}' \
    --header "Authorization: Token ${INFLUX_TOKEN}" \
    --header "Accept: application/csv" \
    --header "Content-Type: application/vnd.flux" \
    --data "
from(bucket: \"${INFLUX_BUCKET}\")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == \"performance_http_request\")
  |> filter(fn: (r) => r.testRunID == \"${RUN_ID}\")
  |> filter(fn: (r) => r._field == \"failed\")
  |> map(fn: (r) => ({ r with _value: if r._value then 1 else 0 }))
  |> count()
" \
    "${INFLUX_URL}/api/v2/query?org=${INFLUX_ORG}")"
  if [ "${bool_status}" = "200" ]; then
    pass "field failed is boolean-typed on every sample"
  else
    fail "field failed is not boolean-typed on every sample (InfluxDB returned HTTP ${bool_status})"
  fi

  for tag in project environment tool scenario transaction; do
    tagged="$(tagged_count_query performance_http_request response_time_ms "${tag}")"
    if [ "${tagged}" = "${total}" ]; then
      pass "tag ${tag} present on all ${total} samples"
    else
      fail "tag ${tag} present on only ${tagged}/${total} samples"
    fi
  done
else
  total="${k6_count}"
  echo "Total samples (http_req_duration): ${total}"

  for tag in project environment tool scenario transaction; do
    tagged="$(tagged_count_query http_req_duration value "${tag}")"
    if [ "${tagged}" = "${total}" ]; then
      pass "tag ${tag} present on all ${total} samples"
    else
      fail "tag ${tag} present on only ${tagged}/${total} samples"
    fi
  done
fi

echo
if [ "${violations}" -eq 0 ]; then
  echo "Schema OK: ${RUN_ID} conforms to docs/metric-model.md"
  exit 0
else
  echo "Schema violations: ${violations}"
  exit 1
fi
