# Load Profile + TODO Guard: Design

## Problem

The generator's purpose: the wizard takes a CI/CD tool, a perf tool,
manual/automated, and the **test parameters** — then returns a pipeline
that calls a tool-specific shell script which runs the test. Unknown
values are marked TODO so a pipeline can still be generated.

Two parts of that are missing today:

1. **No test parameters exist.** Users, ramp-up, duration, throughput and
   test type appear nowhere in the config, wizard, pipelines or scripts.
   Load shape lives only inside each tool's own artifact (`.jmx`, `.lrs`,
   BlazeMeter test).
2. **TODO values fail late and confusingly.** A TODO is baked into the
   generated script as the literal string `TODO` and handed to the tool
   (`jmeter -t TODO`, BlazeMeter test ID `TODO`), which then fails with a
   tool-specific error far from the cause.

## Decisions (from review)

- **LoadRunner Professional keeps the scenario's own settings.** `wlrun`
  has no CLI for Vusers/schedule; the generator does not edit `.lrs`
  files. The wizard asks no load questions for LoadRunner.
- **No ramp-down.**
- **Test type is a label only.** Passed through for perf scripts to use
  and recorded in `run-summary.json`; it never changes generator logic.
- **Config defaults + manual override.** Values live in `customer.yaml`;
  automated jobs use them as-is; the manual pipeline exposes them as
  trigger inputs pre-filled with those values.
- **Throughput in requests/second.**

## A. Schema

New top-level section in `base_config()`:

```yaml
load_profile:
  test_type: load          # free-text label; optional
  users: TODO              # positive int
  ramp_up_seconds: TODO    # int >= 0
  duration_minutes: TODO   # positive int (steady-state / hold time)
  throughput_rps: TODO     # int >= 0; 0 = no cap
```

Units are in the field names so YAML readers never guess. One profile per
setup — not per scenario (YAGNI; per-run override covers the "bump users
for one run" case).

## B. Validation (`validator.py`)

Only for `tool.type` in `{jmeter, blazemeter}` (LoadRunner ignores the
section entirely — no warnings about it):

- A TODO/missing `users`, `ramp_up_seconds`, `duration_minutes`,
  `throughput_rps` → **warning** (`load_profile.users is missing.`). Under
  the existing rule this blocks `generate` only when `incomplete: false`.
- A present value that isn't an int in range → **error**.
- `manual_pipeline.timeout_minutes` and each automated job's
  `timeout_minutes` ≤ `ramp_up_seconds/60 + duration_minutes` → warning
  (the CI job would be killed before the test can finish).

`test_type` is never required.

## C. Wizard

New step after "Connection" (tool-dependent, so it comes after tool
choice): **"Test parameters"**.

- All tools: `Test type label (e.g. load, stress, soak, spike)`, default
  `load`. Printed framing line: "A label passed to your test script and
  recorded in run-summary.json — it doesn't change how the test runs."
- JMeter / BlazeMeter only: users, ramp-up (seconds), duration (minutes),
  throughput (req/s, 0 = no cap). Blank answer → `TODO`.
- LoadRunner: one printed line — "Users, ramp-up, duration and
  throughput come from the LoadRunner scenario (.lrs) itself." — no
  questions.
- Resume keeps existing values as prompt defaults (same as every other
  step).
- The wizard sets `incomplete: true` whenever validation still has
  warnings (any TODO), not only when a required field is missing. Today a
  config with e.g. a TODO `test_plan_path` is saved as `incomplete:
  false`, so `generate` refuses it — contradicting "unknown values still
  produce a pipeline". With this change the draft generates, the README
  lists what's left, and the script's TODO guard stops the run with the
  exact field.

## D. Generated script (`scripts.py`)

### Load flags

`run-jmeter.sh` and `run-blazemeter.sh` accept optional overrides:

```
--users N  --ramp-up-seconds N  --duration-minutes N  --throughput-rps N  --test-type LABEL
```

The script's own defaults are the config values, baked at generation
time (via `shell_quote`). So the script is self-contained: run it with no
load flags and it uses `customer.yaml`'s profile. Numeric flags are
validated with the same `case ... *[!0-9]*` pattern `--timeout-minutes`
already uses.

`run-loadrunner_professional.sh` accepts only `--test-type`.

### How each tool receives them

- **JMeter**: appended to the existing `docker run ... jmeter` command:

  ```
  -Jusers=$users -Jramp_up_seconds=$ramp_up_seconds
  -Jduration_seconds=$((duration_minutes * 60))
  -Jthroughput_rps=$throughput_rps
  -Jthroughput_per_minute=$((throughput_rps * 60))
  -Jtest_type=$test_type
  ```

  `duration_seconds` and `throughput_per_minute` are derived because
  that's what a Thread Group's Duration field and a Constant Throughput
  Timer take. The `.jmx` must read them (`${__P(users,1)}` etc.) — the
  generated README lists the exact property names with a copy-paste
  snippet. The generator does **not** ship or modify a `.jmx`.
- **BlazeMeter**: before the existing `POST /tests/{id}/start`, one
  `PATCH /api/v4/tests/{id}` with
  `{"overrideExecutions": [{"concurrency": users, "rampUp": "<n>s",
  "holdFor": "<n>m", "throughput": rps}]}` (`throughput` omitted when 0).
  Same caveat as the rest of this script: field names are our best
  understanding of API v4 and must be verified against a live account
  before relying on it; also note this persists on the BlazeMeter test.
  `test_type` → `run-summary.json` only.
- **LoadRunner**: `test_type` → `run-summary.json` only.

### `run-summary.json`

Gains `test_type` and, for JMeter/BlazeMeter, `users`,
`ramp_up_seconds`, `duration_minutes`, `throughput_rps` — the values the
run actually used (after overrides). Additive change; existing fields
unchanged.

### TODO guard (all tools)

One shared helper, emitted into every script:

```bash
require_value() {
  if [ -z "$2" ] || [ "$2" = "TODO" ]; then
    echo "ERROR: $1 is not set (still TODO). Fill it in customer.yaml and regenerate, or pass it as a flag." >&2
    exit 1
  fi
}
```

Called right after argument parsing / resolution, before any pre-run
check or tool invocation, for every value the script actually uses:

- JMeter: `tool.connection.test_plan_path`, the resolved environment and
  scenario identifiers, the four load values.
- BlazeMeter: `base_url`, `workspace_id`, `project_id`, resolved scenario
  identifier, the four load values.
- LoadRunner: resolved scenario identifier (the `.lrs` path).

The label in the message is the config path (e.g.
`load_profile.users`), so the error points straight at the fix. No
`run-summary.json` is written — same as a pre-run-check failure today.

## E. Pipelines (renderers)

**Manual pipeline** — JMeter/BlazeMeter get five more trigger inputs,
pre-filled from config; LoadRunner gets only `test_type`:

- **GitHub Actions**: `workflow_dispatch.inputs.{users, ramp_up_seconds,
  duration_minutes, throughput_rps, test_type}`, `type: string`,
  `default:` config value (`TODO` if unknown — visibly prompts the
  tester).
- **Azure DevOps**: matching `parameters` entries, `type: string`,
  `default:` config value.
- **Jenkins**: `string(name: 'USERS', defaultValue: '...')` etc.

Delivered exactly like today's environment/scenario inputs: via `env:` /
Jenkins' parameter env vars, referenced as `--users "$USERS"` — never
spliced into the command text. The script's numeric validation is the
backstop for whatever a triggerer types.

**Automated jobs** — no change. They call the script without load flags,
so it uses the baked config defaults.

## F. README (`readme.py`)

- Lists the active load profile.
- JMeter: a "Wire your .jmx to these properties" section with the six
  property names and an example (`Number of Threads: ${__P(users,1)}`,
  `Ramp-up: ${__P(ramp_up_seconds,0)}`, `Duration: ${__P(duration_seconds,60)}`,
  Constant Throughput Timer: `${__P(throughput_per_minute,0)}`).
- LoadRunner: one line stating load shape comes from the `.lrs`.
- "Remaining TODOs" section includes unfilled `load_profile.*` fields.

## Non-goals

- Editing `.lrs` files / LoadRunner load overrides.
- Ramp-down.
- Per-scenario load profiles.
- Generating or patching a `.jmx`.
- Test-type presets.

## Testing

- Validator: TODO load values warn for JMeter/BlazeMeter, silent for
  LoadRunner; out-of-range values error; timeout-shorter-than-test
  warning.
- Wizard: load questions asked for JMeter/BlazeMeter, skipped for
  LoadRunner; blank → TODO; resume keeps values.
- Scripts (existing stub-based tests with fake `docker`/`curl`):
  - JMeter command line contains the six `-J` properties with derived
    values; flag overrides win over baked defaults; non-numeric flag
    rejected.
  - BlazeMeter stub receives the PATCH body before start; `throughput`
    omitted when 0.
  - TODO guard: each tool exits 1 with the config path in stderr, before
    the stub tool is invoked, and writes no `run-summary.json`.
  - `run-summary.json` contains `test_type` and the used load values.
- Renderers: manual pipeline has the load inputs with config defaults,
  delivered via env vars (no `${{ inputs.users }}` in run text);
  LoadRunner manual pipeline has only `test_type`; automated jobs pass no
  load flags.
- All 9 examples get a filled `load_profile` and regenerate cleanly.

## Relationship to other work

- Independent of the environment-scoped-scenarios plan (on hold). If that
  lands later, the TODO guard's identifier checks move into
  `resolve_test_case` unchanged in spirit.
- Still open after this: runner/agent targeting, BlazeMeter secret
  wiring, automated-job triggers.
