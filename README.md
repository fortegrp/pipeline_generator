# PAAS Performance Tests

Performance test scripts for the local Performance as a Service execution platform.

## Structure

```text
perf_scripts/
  forte/
    k6/
      smoke.js
      load.js
      soak.js
      stress.js
    jmeter/
      smoke.jmx
    locust/
      smoke.py
    gatling/
      ForteSmokeSimulation.scala
```

Jenkins clones this repository and runs the script selected by `SCRIPT_PATH`.

## Jenkins Parameters

Typical values:

```text
SCRIPT_BRANCH=main
SCRIPT_PATH=perf_scripts/forte/k6/smoke.js
SCENARIO=smoke
```

Smoke script paths by tool:

```text
perf_scripts/forte/k6/smoke.js
perf_scripts/forte/jmeter/smoke.jmx
perf_scripts/forte/locust/smoke.py
perf_scripts/forte/gatling/ForteSmokeSimulation.scala
```

The execution platform injects these environment variables:

- `PROJECT`
- `ENVIRONMENT`
- `TEST_RUN_ID`
- `SCENARIO`
- `RUN_DESCRIPTION`

Each script is responsible for its own target URL, duration, VUs, stages, and thresholds.
