# Performance Execution

Local Jenkins setup for running performance tests in Docker, writing metrics to InfluxDB, and viewing results in Grafana.

## Flow

1. Jenkins clones the tests repository from `.env`.
2. Jenkins builds and starts the Docker runner selected in the job.
3. The performance tool writes request metrics to InfluxDB.
4. Jenkins packages raw artifacts into one archive.
5. Results are viewed in Grafana or inspected directly in the InfluxDB UI by `testRunID`.

## Configure

Create local config:

```bash
cp .env.example .env
```

Default scripts repository:

```bash
PROJECT=Forte
SCRIPT_REPO_URL=https://github.com/tuhuzbayeu/paas_tests.git
SCRIPT_REPO_USERNAME=tuhuzbayeu
SCRIPT_REPO_TOKEN=
JENKINS_RUNS_TO_KEEP=30
GRAFANA_HTTP_PORT=3000
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin
```

Jenkins always runs `git clone` for `SCRIPT_REPO_URL`.
If the tests repository is private, create a GitHub token with repository read access, put it into `SCRIPT_REPO_TOKEN`, and restart Jenkins.

The tests repository must contain scripts such as:

```text
perf_scripts/forte/k6/smoke.js
perf_scripts/forte/k6/load.js
perf_scripts/forte/k6/soak.js
perf_scripts/forte/k6/stress.js
perf_scripts/forte/jmeter/smoke.jmx
perf_scripts/forte/locust/smoke.py
perf_scripts/forte/gatling/ForteSmokeSimulation.scala
```

`.env` is ignored by git.

`JENKINS_RUNS_TO_KEEP` controls local workspace cleanup. Jenkins creates one artifact archive first, then removes older `jenkins-runs/<build-number>` directories beyond this limit.

## Start

```bash
./scripts/start.sh
```

If host port `8086` is busy:

```bash
INFLUXDB_HTTP_PORT=8087 ./scripts/start.sh
```

URLs:

| Service | URL | Login |
| --- | --- | --- |
| Jenkins | `http://localhost:8080` | `admin / admin` |
| InfluxDB | `http://localhost:8086` or overridden port | `admin / local-password` |
| Grafana | `http://localhost:3000` | `admin / admin` |

## Jenkins Job

Run:

```text
performance-test
```

Fields:

| Field | Example | Meaning |
| --- | --- | --- |
| `SCRIPT_BRANCH` | `main` | Branch of the tests repository. |
| `PROJECT` | `forte` | Project folder under `perf_scripts` with at least one supported script. |
| `TOOL` | `k6` | Detected from script files inside the selected project. |
| `SCRIPT_PATH` | `perf_scripts/forte/k6/smoke.js` | Detected script path for the selected tool. |
| `SCENARIO` | `smoke` | Choice: `smoke`, `load`, `soak`, `stress`. |
| `DESCRIPTION` | `Local smoke run` | Saved in artifacts and InfluxDB as `runDescription`. |

`PROJECT`, `TOOL`, and `SCRIPT_PATH` are dynamic Jenkins fields. Jenkins scans all files under `perf_scripts/<project>` and detects tools by file type:

- `.js` -> `k6`
- `.jmx` -> `jmeter`
- `.py` -> `locust`
- `.scala` -> `gatling`

If only one tool is found inside the selected project, the `TOOL` field contains only that option.

`testRunID` is generated automatically:

```text
PROJECT_SCENARIO_YYYYMMDDTHHMMSSZ
```

Duration, target URL, VUs, stages, and thresholds belong inside the performance script whenever the tool supports it. Locust currently uses simple runner defaults for users, spawn rate, host, and duration.

Common smoke paths:

```text
perf_scripts/forte/k6/smoke.js
perf_scripts/forte/jmeter/smoke.jmx
perf_scripts/forte/locust/smoke.py
perf_scripts/forte/gatling/ForteSmokeSimulation.scala
```

## Artifacts

Jenkins archives one file:

```text
jenkins-runs/<build-number>/performance-artifacts-<build-number>.tar.gz
```

The archive contains:

```text
artifacts/logs/execution.log
artifacts/logs/<tool>-output.log
artifacts/raw/<tool-raw-results>
artifacts/reports/<tool-html-report>
artifacts/summaries/execution-summary.json
artifacts/metadata/execution-metadata.json
artifacts/metadata/execution-runtime.json
artifacts/raw/resolved-run.env
```

## InfluxDB UI

Open InfluxDB and filter by the generated `testRunID`.

k6 streams detailed metrics continuously through the xk6 InfluxDB output. JMeter streams request samples from the JTL file, Locust writes request events from the test script, and Gatling streams request samples from `simulation.log`.

Common measurements:

- `performance_http_request`
- `performance_tool_run`

Useful tags:

- `project`
- `environment`
- `testRunID`
- `tool`
- `scenario`
- `transaction`
- `runDescription`

The shared dashboard dimensions are:

```text
testRunID / project / scenario / transaction
```

`tool` remains a technical tag used to normalize tool-specific measurements.

## Grafana

Grafana is provisioned automatically with the dark theme. Open the `Performance` folder; no datasource or dashboard import is required.

Available dashboards:

- `Performance Test Review`: one-run review with test totals, a request summary table, and live runtime charts.
- `Performance Run Comparison`: side-by-side review of one baseline run and one target run.

Use the filters in this order:

1. Select `Project` and `Scenario`. Both filters support `All`.
2. Select `Test run`, or select `Baseline run` and `Target run` on the comparison dashboard.
3. Select one or more `Transaction` values. This filter also supports `All`.
4. Select the latency statistic used by response-time panels: p50, p75, p90, p95, or p99.

`Test Review` shows total requests, average RPS, peak k6 VUs, selected response-time percentile, and error rate. `Request Summary` groups count, failures, min, average, max, and percentiles by transaction. `Runtime` shows VUs, RPS, errors per second, and response time over the run.

The comparison dashboard uses the same metric groups for exactly two runs and adds per-transaction latency drift. Runtime series are aligned to the start of each run so baseline and target can be compared even when they ran on different dates. The dashboard time range must include both execution timestamps. The default review range is one hour and the comparison range is 90 days. Filter values are loaded from the last year of metrics.

k6 native measurements and the shared `performance_http_request` measurement used by JMeter, Locust, and Gatling are normalized by the dashboard queries. The underlying metric model is documented in `docs/metric-model.md`.

## Stop

```bash
./scripts/stop.sh
```
