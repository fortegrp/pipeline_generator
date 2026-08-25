# Performance Metrics Stack

Docker Compose stack for storing performance metrics in InfluxDB and comparing different benchmark runs in Grafana.

This is the quick start. For the full architecture — how each producer writes metrics and why, the Grafana query patterns, and the gotchas behind them — see [docs/architecture.md](docs/architecture.md).

## Services

- InfluxDB 2.x stores time-series metrics.
- Grafana visualizes and compares runs.
- Grafana provisioning automatically creates the InfluxDB datasource and a `Performance comparison` dashboard.

## Start

```sh
cp .env.example .env
docker compose up -d
```

Open:

- Grafana: http://localhost:3000
- InfluxDB: http://localhost:8086

Default credentials come from `.env`.

## Write Metrics

Every tool (JMeter, Locust, Gatling) writes HTTP samples to the same measurement and schema:

```text
performance_http_request,project=checkout,environment=local,testRunID=run-2026-06-10-baseline,tool=jmeter,scenario=submit_order,transaction=POST_/orders response_time_ms=118i,status_code=200i,failed=false
```

The important comparison tag is `testRunID`. Use a unique value per benchmark execution, release, branch, commit, environment, or experiment. Keep `project`, `scenario`, and `transaction` stable so Grafana can compare like-for-like results. k6 is the exception: it keeps its own native metrics but must still carry the same required tags.

See [docs/metric-model.md](docs/metric-model.md) for the required tags and fields.

## Smoke Test With Sample Data

After the stack is running:

```sh
chmod +x scripts/write-sample-metrics.sh
./scripts/write-sample-metrics.sh demo
```

Then open Grafana and go to `Dashboards` -> `Performance` -> `Performance comparison`. Select multiple values in the `Test runs` variable to overlay and compare results.

For online monitoring of one active test run, open `Dashboards` -> `Performance` -> `Single run live monitoring`. It refreshes every 5 seconds and is scoped to one selected `Run`.

To simulate a running test:

```sh
POINTS=120 INTERVAL_SECONDS=1 ./scripts/stream-sample-metrics.sh live-demo
```

Keep that script running while the `Single run live monitoring` dashboard is open, then select `live-demo` in the `Run` variable.

## Writing From CI

Use the InfluxDB HTTP write API:

```sh
curl --request POST "http://localhost:8086/api/v2/write?org=performance&bucket=performance&precision=ns" \
  --header "Authorization: Token change-me-super-secret-token" \
  --data-binary "performance_http_request,project=checkout,environment=ci,testRunID=${CI_COMMIT_SHA},tool=jmeter,scenario=submit_order,transaction=POST_/orders response_time_ms=118i,status_code=200i,failed=false"
```

For real CI, store `INFLUXDB_TOKEN` as a secret and pass a meaningful `testRunID` tag such as a commit SHA, build number, branch name, or release version.

## JMeter Google Search Example

The sample JMeter plan at `jmeter/google-search-influx.jmx` runs several Google Search requests and writes per-sample metrics to InfluxDB v2. Each sampler is stored as a `transaction` tag, so the comparison dashboard can show per-transaction graphs and summary rows.

```sh
./jmeter/run-google-search.sh
```

Pass a run id as the first argument to override the generated one.

After it finishes, open `Performance comparison`, select the new `google-search-*` run in `Test runs`, and use the `Transaction` variable to focus on any request.

## Locust, Gatling, and k6 httpbin Examples

Three more example load tests, each hitting [httpbin.org](https://httpbin.org) (`GET /get`, `GET /delay/1`, and `GET /status/200,200,200,200,500`, which returns 500 about a fifth of the time so you get real failures to look at) and writing the same `performance_http_request` schema as JMeter above.

**Locust** (`locust/locustfile.py`) writes via a `request` event listener:

```sh
pip install locust
./locust/run-locust.sh
```

**Gatling** (`gatling/src/test/java/simulations/PerformanceHttpRequestSimulation.java`) writes via a per-request session hook, since Gatling has no public per-request callback API. It's a self-contained Maven project; you need a local Gatling toolchain to run it (there's no Homebrew formula, so download the bundle and point `GATLING_HOME` at it):

```sh
curl -sL -o /tmp/gatling.zip "https://repo1.maven.org/maven2/io/gatling/highcharts/gatling-charts-highcharts-bundle/3.15.1/gatling-charts-highcharts-bundle-3.15.1-bundle.zip"
mkdir -p /tmp/gatling-home && unzip -q /tmp/gatling.zip -d /tmp/gatling-home
export GATLING_HOME=/tmp/gatling-home/gatling-charts-highcharts-bundle-3.15.1
./gatling/run-gatling.sh
```

**k6** (`k6/httpbin-smoke.js`) uses k6's own built-in metrics (not `performance_http_request` — see [docs/metric-model.md](docs/metric-model.md)) tagged with the required tags, written through k6's native InfluxDB v1 output against InfluxDB v2's v1-compatibility API:

```sh
brew install k6
./k6/run-k6.sh
```

All three accept a run id as the first argument, same as the JMeter script, and read `PROJECT`/`ENVIRONMENT`/`SCENARIO`/`USERS`/`RUN_TIME` env vars for overrides. After a run, select its `tool=locust`/`tool=gatling`/`tool=k6` run in `Performance comparison` the same way — note k6's data won't show up there, since it lives under k6's own measurement names rather than `performance_http_request`; query it directly (e.g. `http_req_duration`) via Explore instead.

## Validate a Run's Schema

InfluxDB can't validate writes against [docs/metric-model.md](docs/metric-model.md) on its own — there's no write-time hook for that in OSS InfluxDB. After any tool's run, check it actually conforms:

```sh
./scripts/validate-schema.sh <testRunID>
```

It queries InfluxDB for that run, auto-detects whether it's a `performance_http_request` run or a k6 run, and checks every required tag/field is present on every sample (and, for `performance_http_request`, that `failed` is genuinely boolean-typed). Prints `OK`/`FAIL` per check and exits non-zero if anything doesn't conform — usable as a CI gate after a test run, not just interactively.

## Reset Local Data

```sh
docker compose down -v
```
