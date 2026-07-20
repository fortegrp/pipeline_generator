#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
RUN_ID="${1:-google-search-$(date +%Y%m%d%H%M%S)}"

jmeter -n \
  -t "${SCRIPT_DIR}/google-search-influx.jmx" \
  -q "${SCRIPT_DIR}/google-search-influx.properties" \
  -Jrun_id="${RUN_ID}"
