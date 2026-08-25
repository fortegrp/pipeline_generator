# Performance Visualisation Stack — Full Documentation

This is the deep-reference companion to the [README](../README.md): what each piece is, why it's built the way it is, and the non-obvious decisions and gotchas behind it. Read the README first for the quick start; come here when you need to understand or change how something actually works.

## 1. What this stack is for

Different teams and projects run load tests with different tools — JMeter, Locust, Gatling, k6 — and each tool has its own idea of what a "result" looks like. Without a shared schema, comparing a JMeter baseline against a Locust candidate, or building one dashboard that works regardless of which tool produced the data, is not possible.

This stack solves that with one rule: **every load-testing tool writes to the same InfluxDB measurement, with the same tags and fields** (except k6, which is a deliberate, documented exception — see [§4](#4-the-metric-schema)). Grafana then reads that one shape and renders comparison dashboards that work no matter which tool, scenario, or environment produced the data.

## 2. Architecture

```mermaid
flowchart LR
    subgraph Producers
        JM[JMeter\nJSR223Listener]
        LC[Locust\nrequest event]
        GT[Gatling\nsession hook]
        K6[k6\nnative output]
        SH[shell scripts\nsample data]
    end

    JM -->|"HTTP write API\n(line protocol)"| DB[(InfluxDB v2\nbucket: performance)]
    LC -->|"HTTP write API\n(line protocol)"| DB
    GT -->|"HTTP write API\n(line protocol)"| DB
    SH -->|"HTTP write API\n(line protocol)"| DB
    K6 -->|"v1-compat write API\n(/write?db=...)"| DB

    DB -->|Flux queries| GF[Grafana]
    GF --> D1[Performance comparison]
    GF --> D2[Single run live monitoring]
```

Two Docker Compose services (`docker-compose.yml`):

- **`influxdb`** (InfluxDB 2.7) — the time-series store. One org (`performance` by default), one bucket (`performance`), one admin token, all set on first boot from `.env` via `DOCKER_INFLUXDB_INIT_*` env vars. Healthcheck-gated so Grafana doesn't start before it's ready.
- **`grafana`** (Grafana 11.5.2) — reads `.env`-sourced credentials for its own admin login, and gets the InfluxDB org/bucket/token injected as container env vars so the provisioned datasource file can reference them.

Everything that writes metrics talks to InfluxDB's HTTP write API directly — there's no message queue, no agent, no intermediate service. Every producer POSTs [line protocol](https://docs.influxdata.com/influxdb/v2/reference/syntax/line-protocol/) text straight to `http://localhost:8086/api/v2/write` (or, for k6, the v1-compatible `/write` endpoint — see [§7.4](#74-k6--k6)).

## 3. Grafana provisioning is entirely file-based

Nothing in Grafana is configured through the UI. On container start, Grafana reads:

- `grafana/provisioning/datasources/influxdb.yml` — creates the `InfluxDB Performance` datasource (Flux query language), templated with `${INFLUXDB_ORG}`, `${INFLUXDB_BUCKET}`, `${INFLUXDB_TOKEN}` from the container environment.
- `grafana/provisioning/dashboards/performance.yml` — points Grafana at `grafana/dashboards/*.json` (mounted read-only) and loads them into a `Performance` folder, checking for changes every 30s.

`allowUiUpdates: true` is set, so someone *can* edit a dashboard in the Grafana UI and it'll persist — but only to Grafana's own internal database, not back to these JSON files. If you make a real edit in the UI, export the dashboard JSON and overwrite the file here, or the change is lost the next time the container recreates.

## 4. The metric schema

Full spec: [`docs/metric-model.md`](metric-model.md). Summary:

**Measurement:** `performance_http_request` — written by JMeter, Locust, and Gatling.

**Required tags** (all six, every point):

| Tag | Meaning |
|---|---|
| `project` | system under test, e.g. `checkout` |
| `environment` | `local` / `staging` / `ci` |
| `testRunID` | unique per benchmark execution — the tag Grafana filters/compares on |
| `tool` | `jmeter` / `locust` / `gatling` / `k6` |
| `scenario` | stable scenario name, e.g. `submit_order` |
| `transaction` | per-request/sampler name, e.g. `GET_/cart` |

**Required fields** (all three, every point): `response_time_ms` (int), `status_code` (int, `0` if there was no HTTP response), `failed` (bool).

**k6 is the one exception.** It doesn't write `performance_http_request` at all — it keeps its own native metrics (`http_req_duration`, `http_reqs`, `http_req_failed`, ...) and just makes sure the six required tags are attached to them, so they're still filterable and correlatable against the other tools even though they live under different measurement names. This is a firm constraint from k6's architecture, not a design choice — see [§7.4](#74-k6--k6).

Anything can add extra tags/fields beyond the required set. Nothing may omit or redefine the required ones — that's the one rule dashboards rely on. Nothing stops a producer from violating it automatically, though — see [§11](#11-enforcing-the-schema) for what's actually checked and how.

## 5. Why `failed` is a boolean, and the Flux bug that came with it

`failed` is a boolean field (not `0`/`1`, not baked into `error_rate`) because it's the most direct representation of "did this request succeed." That decision has one real consequence worth knowing before you touch a dashboard query: **InfluxDB's Flux engine cannot mix a boolean field with an int field under one shared table binding.**

Concretely, this pattern — which is completely natural to write, and is exactly what the original (pre-boolean) version of these dashboards did — throws a runtime `type conflict: bool != int` error:

```flux
base = from(bucket: "performance")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "performance_http_request")
  |> filter(fn: (r) => r.testRunID =~ /^${testRunID:regex}$/)

// then branching into consumers of different fields:
responseTimes = base |> filter(fn: (r) => r._field == "response_time_ms") |> ...  // int
errorRate     = base |> filter(fn: (r) => r._field == "failed") |> ...            // bool  <- breaks
```

Flux tries to infer one type for `base`'s value column across every consumer before it knows which branch filters to which field, and a bool/int mix in that inference fails at query time — not at write time, so it's easy to write a query that looks completely reasonable, compiles, and only breaks when it actually runs against real data.

**The fix, used throughout both dashboards:** never share a `from(bucket:...)` binding between a branch that reads `failed` and a branch that reads an int field. Give the boolean branch its own independent `from(bucket:...)` call, even though it duplicates the range/measurement/tag filters:

```flux
base = from(bucket: "performance")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "performance_http_request")
  |> filter(fn: (r) => r._field == "response_time_ms")
  |> filter(fn: (r) => r.testRunID =~ /^${testRunID:regex}$/)
// ... int-only consumers of base ...

errorRate = from(bucket: "performance")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "performance_http_request")
  |> filter(fn: (r) => r._field == "failed")
  |> filter(fn: (r) => r.testRunID =~ /^${testRunID:regex}$/)
  |> map(fn: (r) => ({ r with _value: if r._value then 1.0 else 0.0 }))
  // ...
```

Same rule applies to the status-code/failed `join()` panels ("Status code comparison", "Status codes by transaction") — both sides of the join are built from independent `from()` calls, never a shared binding.

If you add a new panel that touches both `failed` and any int field, follow this pattern or you'll hit the same error. It was found and fixed by actually running every panel's query against live data — see [§9](#9-how-this-was-validated).

## 6. Grafana dashboards

Both dashboards live in `grafana/dashboards/` and share the same underlying query shapes (only the scope differs).

### `performance-comparison.json` — "Performance comparison"

Multi-run overlay/comparison view. Template variables:

- **Test runs** (`testRunID`, multi-select, regex-filtered) — the primary comparison axis.
- **Transaction** (`transaction`, multi-select, regex-filtered) — narrow to specific requests.
- **Percentile** (`pct`, custom: 50/70/90/95/99) — drives every `quantile()` panel.

Panels: response-time percentile over time (by run, and by run+transaction), requests/sec over time, percentile/error-rate/sample-count bar comparisons, a side-by-side transaction comparison table, and a status-code breakdown table.

Throughput (`requests per second`) is computed as `count() / windowSeconds` using the `_start`/`_stop` window boundaries `aggregateWindow` provides — not a client-reported rate field. This is worth knowing if you're comparing against a tool's own self-reported throughput number; small differences are expected since InfluxDB is bucketing by wall-clock window, not by the tool's own sampling cadence.

### `single-run-monitoring.json` — "Single run details and live monitoring"

Scoped to exactly one `testRunID` (single-select, no regex), refreshes every 5s. Meant to be left open while a test is running — pair it with `scripts/stream-sample-metrics.sh` or a live tool run. Same panel shapes as the comparison dashboard, minus the cross-run overlay, plus overall stat tiles (avg response time, req/s, error rate, sample count) at the top.

Both dashboards' `tags: ["performance", ...]` group them under one `Performance` folder in Grafana's UI (set by the provisioning file in [§3](#3-grafana-provisioning-is-entirely-file-based), not by the dashboard JSON itself).

## 7. Producers — how each tool writes metrics

Four real, tested integrations, plus two synthetic-data shell scripts. All are described in the README's run instructions; this section is about *how* each one works internally and why.

### 7.1 JMeter — `jmeter/`

`google-search-influx.jmx` runs a handful of real Google Search requests, then a `JSR223Listener` (Groovy) fires after every sample and does a synchronous `HttpURLConnection` POST of one line-protocol point straight to InfluxDB. No JMeter plugin, no backend listener config — it's about 30 lines of Groovy doing the same tag-escaping and line-building any of the shell scripts do. `status_code` comes from `Integer.parseInt(sampleResult.getResponseCode())`, falling back to `0` if that isn't a plain integer (e.g. `"Non HTTP response code: java.net.ConnectException"`). Config is entirely through `google-search-influx.properties` (`-J` overridable, see `run-google-search.sh`) — never edit the `.jmx` directly for a config change.

### 7.2 Locust — `locust/`

`locustfile.py` registers one `@events.request.add_listener` handler, which Locust calls after *every* request regardless of which task produced it. That handler builds the line-protocol point and does a synchronous `requests.post`. This is the most natural fit of the four tools — Locust's event system is built for exactly this. `failed` is `exception is not None or status_code < 200 or status_code >= 400`.

### 7.3 Gatling — `gatling/`

The odd one out, for a structural reason: **Gatling has no public per-request callback API.** Its own reporting is either an internal binary `simulation.log` (undocumented format, not meant for external parsing — confirmed by inspecting one directly; it changed from Gatling's old tab-separated text format to a compact binary format in a recent version) or a Graphite-protocol stream that only carries pre-aggregated stats per reporting window (count/min/max/percentiles), not one point per request with an individual status code and pass/fail flag. Neither can produce our schema.

So the simulation (`src/test/java/simulations/PerformanceHttpRequestSimulation.java`) does it manually: each tracked request is wrapped in `.exec(session -> ...)` blocks that timestamp before and after the request and read the status code Gatling saved into the session via `.check(status().saveAs("statusCode"))`, then POST the point via a small `InfluxWriter` helper (`InfluxWriter.java`) — the same synchronous-HTTP-POST-per-request pattern as JMeter and Locust. This is a legitimate, working approach at demo scale; it would need decoupling onto its own thread pool (instead of running on Gatling's Netty event loop) before using it for a real high-throughput load test.

**Gatling itself is also unusual to install.** Modern Gatling OSS (3.10+) doesn't ship a standalone CLI bundle anymore — it distributes as a Maven project template (`pom.xml` + `mvnw`), run via `mvnw gatling:test`. There's no Homebrew formula either. So `gatling/` is its own self-contained Maven project, and `run-gatling.sh` needs `GATLING_HOME` pointing at a downloaded-and-extracted Gatling bundle to get `mvnw` plus its pre-warmed offline `.m2` dependency cache (see README for the download command). The bundle's `.mvn/local-settings.xml` resolves `${env.REPO_HOME}` for its local Maven repo path — `run-gatling.sh` sets that env var when invoking `mvnw`, pointing it at `$GATLING_HOME/.m2/repository` so builds work fully offline.

### 7.4 k6 — `k6/`

`httpbin-smoke.js` doesn't write `performance_http_request` — see [§4](#4-the-metric-schema) for why that's a deliberate exception, not a gap. Instead:

- `options.tags` sets `project`/`environment`/`testRunID`/`tool=k6`/`scenario` as **global tags**, applied to every metric k6 produces for the whole run.
- Each `http.get(url, { tags: { transaction: '...' } })` call adds `transaction` as a **per-request tag** on top of the global ones.
- k6's built-in `--out influxdb=...` output (the InfluxDB **v1** wire protocol — OSS k6 has never had a native v2 output; that requires the separate `xk6-output-influxdb` extension) writes each of k6's own metrics (`http_req_duration`, `http_reqs`, `http_req_failed`, `iterations`, ...) as its own InfluxDB measurement, tags and all.

This only works against InfluxDB v2 because v2 ships a **v1-compatibility write API** (`/write?db=...`), and because InfluxDB auto-creates a DBRP mapping (the v1 "database" → v2 bucket link) for any bucket created the normal way — which our `performance` bucket is, via `DOCKER_INFLUXDB_INIT_BUCKET`. `run-k6.sh` authenticates to that endpoint with HTTP Basic Auth where the password is the InfluxDB token and the username is ignored (`http://any:$TOKEN@host:8086/performance`). If you ever point this at a bucket that *wasn't* auto-mapped, you'll need to create the DBRP mapping yourself first (`influx v1 dbrp create ...` — see the comment in `run-k6.sh`).

One practical consequence: **k6's data does not show up in the `performance-comparison` dashboard.** It lives under `http_req_duration` and friends, not `performance_http_request`. Query it directly via Grafana Explore, or build a k6-specific panel if you need one.

### 7.5 Synthetic sample data — `scripts/`

`write-sample-metrics.sh` and `stream-sample-metrics.sh` don't run a real load test at all — they fabricate `performance_http_request` points directly via `curl`, for exercising the dashboards without needing any tool installed. `write-sample-metrics.sh` backfills a fixed 60-point-per-transaction `baseline`/`candidate` pair (for the comparison dashboard); `stream-sample-metrics.sh` writes one point per second in a loop (for the live-monitoring dashboard). Both inject occasional `failed=true`/`status_code=500` points via a modulus check on a point counter — tuned so the failures land spread across the whole run rather than clustering at the very first point (a real bug that existed here briefly; the fix is why the counter is explicitly a linear index across all `(iteration, transaction)` pairs rather than the iteration index alone).

### 7.6 Why httpbin.org for Locust/Gatling/k6, but Google for JMeter

JMeter's example predates the other three and targets `google.com` directly. Locust, Gatling, and k6 were added later, deliberately targeting [httpbin.org](https://httpbin.org) instead — it's built for exactly this (testing HTTP clients), and its `/status/200,200,200,200,500` endpoint returns a random code from the given list, which is a clean way to get a real, non-synthetic ~20% failure rate without needing an unreliable or rate-limited third party. (Google *does* rate-limit a two-thread JMeter run within a few minutes — you'll see this yourself if you run `run-google-search.sh` for long enough; it's realistic but not something worth deliberately reproducing three more times.)

## 8. CI usage

Any CI job can write directly with `curl` — no tool required:

```sh
curl --request POST "http://localhost:8086/api/v2/write?org=performance&bucket=performance&precision=ns" \
  --header "Authorization: Token ${INFLUXDB_TOKEN}" \
  --data-binary "performance_http_request,project=checkout,environment=ci,testRunID=${CI_COMMIT_SHA},tool=jmeter,scenario=submit_order,transaction=POST_/orders response_time_ms=118i,status_code=200i,failed=false"
```

Use a meaningful, unique `testRunID` per CI execution — commit SHA, build number, or branch name are the usual choices. Store the InfluxDB token as a CI secret, never inline.

## 9. How this was validated

Every claim above was checked against the running stack, not just written and assumed correct:

- All four tool integrations were actually run (JMeter and the shell scripts against the schema's original design; Locust, Gatling, and k6 against real httpbin.org traffic), and their InfluxDB points were queried directly to confirm the exact tag set, field types, and that `failed`/`status_code` correlate correctly with real successes and failures.
- Every panel query in both dashboards was executed against live data via Grafana's `/api/ds/query` endpoint (not just visual inspection of the JSON), which is how the Flux type-conflict bug in [§5](#5-why-failed-is-a-boolean-and-the-flux-bug-that-came-with-it) was actually found.
- Gatling's `simulation.log` format was inspected directly (not assumed from memory/docs) before deciding it wasn't a viable integration path.
- k6's InfluxDB v1-compat write path was tested against a raw `curl` write first, then against `k6 run --out influxdb=...`, confirming the DBRP auto-mapping assumption in [§7.4](#74-k6--k6) before relying on it in the script.

## 10. Known limitations

- **Gatling's write mechanism doesn't scale.** The per-request synchronous HTTP POST (see [§7.3](#73-gatling--gatling)) runs on Gatling's own event loop; fine for a smoke test, wrong for a real high-VU load test.
- **k6 data is siloed from the comparison dashboard** by design of the schema exception ([§7.4](#74-k6--k6)) — there's no cross-tool dashboard view that includes k6 today.
- **The Gatling toolchain isn't fully self-installing.** `GATLING_HOME` has to point at a manually downloaded bundle; there's no package manager formula to lean on.
- **Locust, Gatling, and k6 all depend on httpbin.org being reachable.** If it's down or rate-limits you, those three examples will show connection failures rather than a clean demo — that's expected, not a bug in the schema.
- **`validate-schema.sh` isn't wired into anything automatically** — there's no CI in this repo to run it. It's a manual (or manually-CI-wired) gate, not an always-on one. See [§11](#11-enforcing-the-schema).

## 11. Enforcing the schema

[§4](#4-the-metric-schema) defines the contract; nothing makes a producer honor it automatically. OSS InfluxDB has no write-time validation hooks — there's no way to reject a non-conforming line-protocol write before it lands, the way a relational database would reject a row that violates a `NOT NULL` constraint.

InfluxDB does give you one guarantee for free, though, and it's worth knowing precisely what it covers: **field type is enforced per `(measurement, field)`, globally, from the first write.** Once `failed` has been written as boolean for `performance_http_request` anywhere in the bucket, a later write with `failed=0i` (integer) is rejected outright:

```json
{"code":"unprocessable entity","message":"failure writing points to database: partial write: field type conflict: input field \"failed\" on measurement \"performance_http_request\" is type integer, already exists as type boolean dropped=1"}
```

(HTTP `422` — confirmed by writing a conflicting point directly, not assumed from documentation.) That's real protection against a whole category of mistake, but it only fires once the "correct" type is already established — a fresh bucket's very first write decides the type for good (until that data is deleted), so a producer with a type bug that runs *first* against an empty bucket would silently lock in the wrong type instead of getting rejected.

**What InfluxDB does *not* enforce:** whether a required tag or field is present at all. A point missing `scenario`, or missing the `failed` field entirely, is accepted without complaint — it just becomes a differently-shaped series that dashboard queries scoped to the full tag/field set will silently exclude.

`scripts/validate-schema.sh <testRunID>` closes that gap as a **post-write check**, run after the fact rather than at write time:

1. Queries InfluxDB for that `testRunID` and auto-detects whether it's a `performance_http_request` run or a k6 run (by checking which measurement actually has data for it).
2. For `performance_http_request`: counts samples per required field and per required tag (via Flux's `exists r["tag"]`, the same idiom the dashboards use for optional-field handling) and compares each count against the total sample count — a partial omission (present on some points, missing on others within the same run) is caught, not just a total absence.
3. Also re-confirms `failed` is genuinely boolean by attempting the same `if r._value then ... else ...` coercion the dashboards rely on — this mostly reconfirms the write-time guarantee above rather than catching something new, but it's a direct check against the data actually stored rather than trusting that guarantee blindly.
4. For k6: same tag-presence check, applied to `http_req_duration` instead (k6's exception from [§4](#4-the-metric-schema) means there's no fixed required-field check to run here — k6's fields are whatever the native metric uses).

Exit codes: `0` conforms, `1` one or more violations (printed individually as `FAIL: ...`), `2` no data found for that `testRunID` at all (setup/typo, not a schema violation). That makes it usable as a CI step after any tool's run — see [§10](#10-known-limitations) for the caveat that nothing currently wires it in automatically.
