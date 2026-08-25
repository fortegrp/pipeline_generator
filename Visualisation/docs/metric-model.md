# Metric Model

This is the standardized schema every load-testing tool in this stack must write to. It exists so Grafana can compare runs across tools, scenarios, and transactions without per-tool dashboards.

## HTTP request measurement

JMeter, Locust, and Gatling all write one measurement:

```text
performance_http_request
```

Required tags (every point must set all six, using these exact keys):

- `project`: the system under test, for example `checkout`.
- `environment`: target environment, for example `local`, `staging`, or `ci`.
- `testRunID`: unique identifier for this benchmark execution. Use this to compare baseline, candidate, branch, commit, release, or environment results. If you need branch/commit/build info for a run, encode it into this value (for example `checkout-abc1234-ci`) rather than adding separate tags.
- `tool`: the load-testing tool that produced the point, for example `jmeter`, `locust`, or `gatling`.
- `scenario`: stable benchmark scenario name, for example `submit_order`. Keep this stable across runs so comparisons are apples-to-apples.
- `transaction`: unique request, endpoint, or sampler name inside a scenario, for example `GET_/cart` or `POST_/orders`.

Required fields (every point must set all three):

- `response_time_ms` (integer): response time in milliseconds.
- `status_code` (integer): HTTP status code. Use `0` if the sampler didn't get an HTTP response (connection error, timeout).
- `failed` (boolean): whether the request should count as failed.

Tools may add extra tags or fields beyond this set, but must not omit or redefine the required ones.

Example line protocol:

```text
performance_http_request,project=checkout,environment=ci,testRunID=build-1042-candidate,tool=jmeter,scenario=submit_order,transaction=POST_/orders response_time_ms=95i,status_code=200i,failed=false
```

## k6

k6 does not write to `performance_http_request`. Use k6's native metrics (`http_req_duration`, `http_reqs`, `checks`, etc.) and tag every one of those metrics with the same required tags above (`project`, `environment`, `testRunID`, `tool=k6`, `scenario`, `transaction`) so it can still be filtered and correlated against the other tools in Grafana, even though it lives under different measurement/field names. In practice this means setting `project`/`environment`/`testRunID`/`tool`/`scenario` as global tags in `options.tags` and `transaction` as a per-request tag — see `k6/httpbin-smoke.js`.

## Implementations in this repo

Each tool has a working example that writes real, schema-conformant metrics: `jmeter/google-search-influx.jmx`, `locust/locustfile.py`, `gatling/src/test/java/simulations/PerformanceHttpRequestSimulation.java`, and `k6/httpbin-smoke.js`. See the README for how to run each one.

## Enforcing this schema

InfluxDB itself can't validate writes against this document - OSS InfluxDB has no write-time hooks, so any producer could drift from this spec and InfluxDB would still accept it. What InfluxDB *does* enforce on its own: once a field (e.g. `failed`) is first written as a given type for a measurement, it rejects (`422`) any later write where that field has a different type - so a `failed=0i` mistake gets rejected outright rather than silently corrupting the schema, but a missing tag or missing field is not caught at write time.

To actually check a run conforms, run `./scripts/validate-schema.sh <testRunID>` after any tool's run (or as a CI step). It queries InfluxDB for that run, auto-detects whether it's a `performance_http_request` run or a k6 run, and asserts every required tag/field is present on every sample - exiting non-zero if anything doesn't conform. See the README for details.
