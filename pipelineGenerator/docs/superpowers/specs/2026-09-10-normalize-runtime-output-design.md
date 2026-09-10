# Normalize Runtime Output Design

## Purpose

All three generated scripts (`run-jmeter.sh`, `run-loadrunner_professional.sh`,
`run-blazemeter.sh`) now really run a test (roadmap items 10-13), but they
give a calling CI/CD pipeline no consistent, structured way to know what
happened. JMeter writes nothing beyond its own `results.jtl`/`report/`.
LoadRunner writes nothing beyond whatever `wlrun` puts in its results
folder. BlazeMeter writes `summary.json`/`report_link.json`, but
`summary.json` there is a raw passthrough of BlazeMeter's own
`reports/main/summary` API response — a BlazeMeter-specific shape, not
something a pipeline step could treat the same way across all three tools.

This is roadmap Milestone 2, item 4 ("Normalize Runtime Output"): define
one `run-summary.json` schema, written by all three generated scripts,
so a CI/CD step downstream of `scripts/run-<tool_type>.sh` can read one
consistent file regardless of which tool ran.

## Non-Goals

- Changing or removing BlazeMeter's existing `summary.json`/
  `report_link.json`. Those keep writing exactly what they write today,
  unmodified, on the same `ENDED`-only path. `run-summary.json` is an
  additional, separate file with its own schema, written by all three
  tools including BlazeMeter.
- Making `status` reflect actual test-assertion outcomes (e.g. parsing
  JMeter's `.jtl` for failed samples, or BlazeMeter's summary report for
  failed requests). `status` is derived purely from each tool's own
  exit code or terminal API status, matching the existing, documented
  precedent for `wlrun`'s exit code ("best local signal available,
  known to be unreliable on some versions") — not a new correctness
  guarantee.
- Producing `run-summary.json` for precheck failures (missing test plan,
  unreachable host, `wlrun` not found, scenario file missing, etc.).
  Those already exit immediately with a clear one-line stderr message
  and a nonzero exit code; that behavior is unchanged. `run-summary.json`
  is written only once the tool itself is actually invoked (JMeter/wlrun
  subprocess call, or BlazeMeter's start-test API call) and something is
  known about how it concluded.
- Tests exercising real `jmeter`/`wlrun`/BlazeMeter API behavior — that's
  roadmap item 14 (mocked/fake remote systems), separate follow-up work.
  This design does add functional tests of the summary-writing logic
  itself using the existing stub-executable technique from the
  BlazeMeter final review (see Testing below).
- Any change to `collect_results`'s meaning — remains a configurable,
  currently-inert `pre_run_checks` value across all three tools, as it
  already is today.

## Schema

`run-summary.json`, written into each run's `results_dir`
(`run-output/<environment_slug>_<scenario_slug>/`):

```json
{
  "tool": "jmeter",
  "run_id": "staging_smoke-test_20260910T143000Z",
  "environment": "staging",
  "scenario": "smoke-test",
  "status": "passed",
  "started_at": "2026-09-10T14:30:00Z",
  "ended_at": "2026-09-10T14:34:12Z",
  "duration_seconds": 252,
  "report_link": "run-output/staging_smoke-test/report/index.html",
  "results_dir": "run-output/staging_smoke-test",
  "artifact_status": "complete"
}
```

Field notes:

- `tool` — the literal `tool_type` value (`jmeter`, `loadrunner_professional`,
  `blazemeter`), so a consumer aggregating summaries across setups can tell
  them apart without parsing the `run_id`.
- `run_id` — for BlazeMeter, its own `master_id` (already a stable,
  meaningful identifier from the API). For JMeter/LoadRunner, which have
  no equivalent, a generated
  `<environment_slug>_<scenario_slug>_<UTC timestamp>` string, where the
  timestamp is captured once at the start of `main()` via
  `date -u +%Y%m%dT%H%M%SZ`.
- `environment` / `scenario` — the raw catalog keys as passed via
  `--environment`/`--scenario` (not the resolved tool identifiers, which
  may be sensitive paths or IDs; not the filesystem slugs, which are
  already visible in `results_dir`).
- `status` — one of `passed` / `failed` / `error`. `failed` means the tool
  ran and reported a failure (JMeter/wlrun nonzero exit, or BlazeMeter
  `ERROR`/`ABORTED` status). `error` is reserved for BlazeMeter's
  timeout-without-a-terminal-status case, where the script never learned
  what happened. `passed` is a clean run (zero exit code, or BlazeMeter
  `ENDED`).
- `started_at` / `ended_at` — ISO 8601 UTC (`date -u +%Y-%m-%dT%H:%M:%SZ`),
  captured immediately before and after the tool invocation (JMeter's
  `jmeter` call, LoadRunner's `wlrun` call, or BlazeMeter's full
  start-and-poll cycle).
- `duration_seconds` — integer difference between the two timestamps'
  epoch seconds (`date -u +%s`, captured alongside the ISO timestamps).
- `report_link` — a path or URL a human would open to see results:
  relative filesystem path for JMeter (`.../report/index.html`) and
  LoadRunner (`.../<results_dir>`, since `wlrun` has no separate report
  file — the results dir itself is what to open), and BlazeMeter's
  existing web UI URL (`$base_url/app/#/masters/$master_id/summary`,
  the same value already written to `report_link.json` today). Callers
  must not assume this is always a URL.
- `results_dir` — the same relative path already used to `mkdir -p` this
  run's output folder, repeated here for convenience so a consumer with
  only the JSON in hand doesn't have to reconstruct it.
- `artifact_status` — `complete` if the tool's expected output exists on
  disk after the run, else `incomplete`:
  - JMeter: `results.jtl` and `report/index.html` both exist.
  - LoadRunner: `results_dir` is non-empty (has at least one entry).
  - BlazeMeter: `summary.json` and `report_link.json` (its existing
    files) both exist — i.e. the `ENDED` path completed its writes. On
    the `ERROR`/`ABORTED`/timeout paths, `artifact_status` is always
    `incomplete` (those files are never written on non-`ENDED` paths).

## Per-Tool Control Flow Changes

### JMeter

JMeter currently writes flat into `run-output/` with no per-run
subfolder — a second invocation (different environment/scenario, or a
rerun) silently overwrites the first run's `results.jtl`/`report/`. This
design gives JMeter the same `results_dir` structure BlazeMeter/LoadRunner
already have, using the shared `_render_slug_resolvers` helper (already
shared by the other two): `run-output/<environment_slug>_<scenario_slug>/`,
containing `results.jtl`, `report/`, and now `run-summary.json`. This is a
side effect that also fixes the overwrite-on-rerun gap, not a separate
task.

Control flow: capture the `jmeter` invocation's exit code without
tripping `set -e`:

```bash
local run_status=0
if ! "$jmeter_bin" -n -t "$test_plan_path" -l "$results_dir/results.jtl" -e -o "$results_dir/report" \
  -Jenvironment="$environment_identifier" -Jscenario="$scenario_identifier"; then
  run_status=1
fi
```

then write `run-summary.json`, then `exit "$run_status"` at the very end
of `main()` — preserving today's behavior where a JMeter failure fails
the CI step, just after the summary is written instead of via an
immediate `set -e` abort.

### LoadRunner Professional

Same pattern, applied to the existing `wlrun` invocation:

```bash
local run_status=0
if ! "$wlrun_path" -Run -TestPath "$scenario_identifier" -ResultName "$results_dir"; then
  run_status=1
fi
```

then write `run-summary.json`, then `exit "$run_status"`. The existing
code comment documenting `wlrun`'s exit-code unreliability is unchanged
and still applies to `run_status`/`status` here.

### BlazeMeter

Currently, the polling loop calls `exit 1` immediately on `ERROR`/
`ABORTED` status or on timeout, before anything is written. This design
replaces those inline exits with setting `status` and `break`ing out of
the loop (timeout already falls out of the loop naturally today), so
every path reaches a shared epilogue:

- `ENDED`: existing `summary.json`/`report_link.json` writes happen
  exactly as today, `status` = `passed`.
- `ERROR`/`ABORTED`: `status` = `failed`, no change to the existing
  stderr message, still exits nonzero — just after `run-summary.json` is
  written instead of before.
- Timeout (loop exits without reaching `ENDED`): `status` = `error`, same
  stderr message as today, still exits nonzero — same timing change.

`run-summary.json` is written in all three cases; `summary.json`/
`report_link.json` remain `ENDED`-only, unchanged.

## Testing

Extend `tests/test_tool_scripts.py` (following the stub-executable
pattern introduced for BlazeMeter's transient-poll-failure test) with,
per tool:

- A successful run produces `run-summary.json` with `status: "passed"`
  and `artifact_status: "complete"`, containing all required keys.
- A failing tool run (nonzero `jmeter`/`wlrun` stub exit, or a stubbed
  BlazeMeter `ERROR` status) produces `run-summary.json` with
  `status: "failed"`, and the script itself still exits nonzero.
- BlazeMeter's timeout path produces `status: "error"`.
- A precheck failure (e.g. missing JMeter test plan) does NOT produce
  `run-summary.json` at all.
- JMeter's rerun-no-longer-overwrites behavior: two invocations with
  different `--scenario` values produce two distinct `results_dir`
  folders.

Existing tests asserting JMeter's current flat `run-output/results.jtl`
path get updated to the new `results_dir`-nested path as part of this
work, alongside the renderer/README/CI-platform tests already covering
per-tool script content.

## Implementation Note

`scripts.py` already has a precedent for sharing bash-generation logic
across tools (`_render_resolvers`, `_render_slug_resolvers`). The
JSON-construction snippet for `run-summary.json` (same field set, same
`printf`/`jq` shape) should be a single shared helper — e.g.
`_render_summary_write(tool_type)` — parameterized only by the pieces
that differ per tool (the `status`/`run_id`/`report_link` bash variable
names already in scope at the call site), rather than duplicated inline
three times.

## Documentation Updates

- `CLAUDE.md`'s `scripts.py` bullet: mention `run-summary.json` and
  JMeter's new `results_dir`.
- `docs/current-state-and-readiness-plan.md`: check off Milestone 2 item
  4, update the "Generated Script Execution Flow" section's JMeter
  description to mention `results_dir`, and update the "Definition of
  Ready" bullet about summary output.
- `docs/pipeline-generator-user-guide.md`: document `run-summary.json`'s
  location and fields for anyone consuming generated setups.
- Generated setup README (`renderers/readme.py`): mention
  `run-output/<environment_slug>_<scenario_slug>/run-summary.json` as
  where to find machine-readable run status, for all three tool
  branches.
