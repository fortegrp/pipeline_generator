# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Docker Compose stack (InfluxDB 2.x + Grafana) for storing performance/benchmark metrics and comparing runs. There is no application code to build or test — this repo is infrastructure config (compose file, Grafana provisioning/dashboards, shell scripts, one JMeter test plan) plus docs describing the metric line-protocol format.

## Commands

Start the stack:

```sh
cp .env.example .env
docker compose up -d
```

- Grafana: http://localhost:3000
- InfluxDB: http://localhost:8086

Reset all local data (drops volumes):

```sh
docker compose down -v
```

Write synthetic baseline/candidate sample data (60 points each, for the `Performance comparison` dashboard):

```sh
./scripts/write-sample-metrics.sh demo
```

Stream one run's points live (for the `Single run live monitoring` dashboard, refreshes every 5s):

```sh
POINTS=120 INTERVAL_SECONDS=1 ./scripts/stream-sample-metrics.sh live-demo
```

Run the sample JMeter plan (writes per-request samples to InfluxDB directly from JMeter):

```sh
./jmeter/run-google-search.sh [run_id]
```

Run the Locust/Gatling/k6 examples (each hits httpbin.org and writes the same schema — Gatling needs a local toolchain first, see README):

```sh
./locust/run-locust.sh [run_id]
./gatling/run-gatling.sh [run_id]
./k6/run-k6.sh [run_id]
```

All scripts/plans read Influx connection settings from env vars (`INFLUX_URL`/`INFLUX_ORG`/`INFLUX_BUCKET`/`INFLUX_TOKEN`, or the JMeter/Gatling equivalents `influx_url`/`influx_org`/`influx_bucket`/`influx_token`/`-Dinflux_*` system properties) with defaults matching `.env.example`. There is no test suite or linter in this repo, but there is a schema gate:

```sh
./scripts/validate-schema.sh <testRunID>
```

Queries InfluxDB for that run and asserts every required tag/field is present on every sample (see `docs/metric-model.md` for the schema, and the Architecture section below for why this exists as a separate post-write check rather than write-time validation). Exits non-zero on any violation — run it after any tool's run, or wire it into CI.

## Architecture

**Data flow:** metrics get written as InfluxDB v2 line protocol into a single measurement, `performance_http_request`, via one of four producers: `curl` against the HTTP write API (`scripts/*.sh`, CI), JMeter's Groovy `JSR223Listener` (`jmeter/google-search-influx.jmx`), Locust's `request` event listener (`locust/locustfile.py`), or a per-request session hook in Gatling's Java simulation (`gatling/src/test/java/simulations/PerformanceHttpRequestSimulation.java` — Gatling has no public per-request callback API, so this writes to InfluxDB directly from inside the request chain rather than through Gatling's own reporting, which is either an undocumented binary log or pre-aggregated Graphite output that can't produce this schema). k6 (`k6/httpbin-smoke.js`) is the exception: it keeps its own native metrics, tagged with the required tags, written through k6's built-in InfluxDB v1 output against InfluxDB v2's v1-compatibility API (`/write?db=...`, which relies on the DBRP mapping InfluxDB auto-creates per bucket). Grafana then queries InfluxDB (Flux) through the provisioned datasource and renders two dashboards — k6's data isn't visible there since it lives under k6's own measurement names, not `performance_http_request`.

**Gatling toolchain:** unlike JMeter/Locust/k6, Gatling ships as a Maven project (no CLI binary), so `gatling/` is its own self-contained Maven project (`pom.xml` + `src/test/java`) rather than a plan file pointed at a shared installed tool. `gatling/run-gatling.sh` needs `GATLING_HOME` pointing at an extracted Gatling bundle (see README for the download command) to get `mvnw` and a pre-warmed offline dependency cache.

**Metric shape** (see `docs/metric-model.md`, this is the standardized cross-tool schema — JMeter, Locust, and Gatling must all conform to it, k6 is the one exception): required tags are `project`, `environment`, `testRunID` (unique per benchmark execution — this is the field Grafana dashboards filter/compare on), `tool`, `scenario` (kept stable across runs so comparisons are apples-to-apples), and `transaction` (per-endpoint/sampler breakdown). Required fields are `response_time_ms`, `status_code`, and `failed` (boolean). Any producer must set exactly these tags/fields for the dashboards to work; extra tags/fields are allowed but the required set must never be omitted or redefined. k6 keeps its own native metrics instead of writing to `performance_http_request`, but still carries the same required tags.

**Schema enforcement is a post-write check, not a write-time gate** (`scripts/validate-schema.sh`): OSS InfluxDB has no write-time validation hooks, so nothing stops a producer from writing a non-conforming point. InfluxDB does enforce field *type* consistency on its own, though — once a field is first written as one type for a measurement, a later write with a different type for that same field gets rejected with `422` (confirmed by testing it directly), which is why the validator's own boolean-type check on `failed` is mostly reconfirmation rather than something that could otherwise slip through. Tag/field *presence* has no such native guarantee, which is the actual gap the validator closes.

**Grafana provisioning is entirely file-based and auto-applied on container start** — nothing is configured through the UI:
- `grafana/provisioning/datasources/influxdb.yml` wires the InfluxDB datasource (Flux query language) using `${INFLUXDB_*}` env vars injected into the Grafana container by `docker-compose.yml`.
- `grafana/provisioning/dashboards/performance.yml` points Grafana at `grafana/dashboards/*.json` (mounted read-only), loading them into a `Performance` folder. `allowUiUpdates: true`, so in-UI edits persist to Grafana's own DB but are not written back to these JSON files — if a dashboard is meaningfully edited in the UI, export it and update the JSON here to keep it under version control.
- `grafana/dashboards/performance-comparison.json`: multi-run overlay/comparison view (variable-driven: `Test runs` multi-select, plus `Transaction` regex and a `Percentile` selector).
- `grafana/dashboards/single-run-monitoring.json`: live view scoped to one `Run`, 5s auto-refresh.

**Secrets/config:** `.env` (gitignored) holds InfluxDB and Grafana admin credentials plus the InfluxDB token, templated from `.env.example`. `docker-compose.yml` passes these through to both containers via environment variables — InfluxDB uses them for its one-time setup (`DOCKER_INFLUXDB_INIT_*`), Grafana uses them for admin login and to parameterize the datasource provisioning file above.

**JMeter plan** (`jmeter/google-search-influx.jmx`): parameterized via `${__P(name,default)}` properties (see `jmeter/google-search-influx.properties`), so overrides go through the `.properties` file or `-J` flags in `run-google-search.sh`, not by editing the `.jmx` directly. Each HTTP sampler is tagged as its own `transaction` value so the comparison dashboard can break results down per transaction.
