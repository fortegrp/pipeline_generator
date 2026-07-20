# Performance Metrics Stack

Docker Compose stack for storing performance metrics in InfluxDB and comparing different benchmark runs in Grafana.

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

Metrics should use this shape:

```text
performance,run=run-2026-06-10-baseline,suite=checkout,test=submit_order,request=POST_/orders latency_ms=118,throughput_ops_s=820,error_rate=0.01,cpu_percent=64
```

The important comparison tag is `run`. Use a unique value per benchmark execution, release, branch, commit, environment, or experiment. Keep `suite` and `test` stable so Grafana can compare like-for-like results.

See [docs/metric-model.md](docs/metric-model.md) for the recommended tags and fields.

## Smoke Test With Sample Data

After the stack is running:

```sh
chmod +x scripts/write-sample-metrics.sh
./scripts/write-sample-metrics.sh demo
```

Then open Grafana and go to `Dashboards` -> `Performance` -> `Performance comparison`. Select multiple values in the `Runs` variable to overlay and compare results.

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
  --data-binary "performance,run=${CI_COMMIT_SHA},suite=checkout,test=submit_order,request=POST_/orders latency_ms=118,throughput_ops_s=820,error_rate=0.01"
```

For real CI, store `INFLUXDB_TOKEN` as a secret and pass a meaningful `run` tag such as a commit SHA, build number, branch name, or release version.

## JMeter Google Search Example

The sample JMeter plan at `jmeter/google-search-influx.jmx` runs several Google Search requests and writes per-sample metrics to InfluxDB v2. Each sampler is stored as a `request` tag, so the comparison dashboard can show per-request graphs and summary rows.

```sh
./jmeter/run-google-search.sh
```

Pass a run id as the first argument to override the generated one.

After it finishes, open `Performance comparison`, select the new `google-search-*` run, set `Suite regex` to `google`, `Test regex` to `search`, and use `Request regex` to focus on any request.

## Reset Local Data

```sh
docker compose down -v
```
