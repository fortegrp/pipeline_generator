#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
RUN_ID="${1:-gatling-$(date +%Y%m%d%H%M%S)}"

GATLING_HOME="${GATLING_HOME:-/opt/homebrew/Cellar/gatling/3.15.1}"

REPO_HOME="${GATLING_HOME}/.m2/repository" \
  "${GATLING_HOME}/mvnw" -f "${SCRIPT_DIR}/pom.xml" -q -o gatling:test \
  -Dgatling.simulationClass=simulations.PerformanceHttpRequestSimulation \
  -Dinflux_url="${INFLUX_URL:-http://localhost:8086}" \
  -Dinflux_org="${INFLUX_ORG:-performance}" \
  -Dinflux_bucket="${INFLUX_BUCKET:-performance}" \
  -Dinflux_token="${INFLUX_TOKEN:-change-me-super-secret-token}" \
  -Dproject="${PROJECT:-httpbin-demo}" \
  -Denvironment="${ENVIRONMENT:-local}" \
  -Dtest_run_id="${RUN_ID}" \
  -Dscenario="${SCENARIO:-httpbin-smoke}" \
  -Dusers="${USERS:-2}"
