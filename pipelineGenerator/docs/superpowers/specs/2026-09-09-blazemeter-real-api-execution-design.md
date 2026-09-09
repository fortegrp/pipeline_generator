# BlazeMeter Real API Execution Design

## Purpose

`generate` currently writes `scripts/run-blazemeter.sh` as a template: real,
syntactically valid bash with connection details filled in as variables,
but it always ends in `echo "ERROR: BlazeMeter execution is not
implemented in this generated script yet." >&2; exit 1`. This is roadmap
item 11 ("Fill in the real BlazeMeter API call") — making that script
real, the same way JMeter's and LoadRunner Professional's already are.

Unlike LoadRunner, BlazeMeter is a hosted SaaS with a documented REST API
(v4), so there is no execution-strategy decision to make first — the
generated script talks to BlazeMeter's API directly via `curl`/`jq`, with
no assumption about where the CI job runs.

## Non-Goals

- `verify_load_generators_connected` as a real check for BlazeMeter. This
  concept doesn't map onto BlazeMeter's model (it manages its own cloud
  load generators internally as part of starting a run, with no separate
  API call to check generator connectivity ahead of time); it remains a
  `# TODO precheck: ...` comment, same as today, and the same as
  LoadRunner's treatment of the same check.
- Changing what `collect_results` means (a pre-existing open question
  noted in the readiness plan, unrelated to this work — kept as a
  configurable, currently-inert `pre_run_checks` value for BlazeMeter,
  same as it already is for the other two tools).
- Tests that exercise BlazeMeter's real API. That's roadmap item 14
  ("mocked/fake remote systems"), explicitly future work — consistent
  with how LoadRunner's `wlrun` and JMeter's `jmeter` are also untested
  against the real binary/API.
- Verifying the exact BlazeMeter API v4 endpoint paths and response shapes
  against current, live documentation. Their full API reference sits
  behind a login-gated explorer; this design proceeds on well-established
  knowledge of the core run lifecycle (test start, status polling) with
  explicit flags on the parts that are less certain (see "Known
  Verification Gaps" below) rather than blocking on documentation access.

## Config Shape Changes

### `tool.connection` for `blazemeter`

Unchanged shape: `base_url`, `workspace_id`, `project_id` remain exactly
the fields they are today — but `workspace_id` moves from unused to
actually consumed: `verify_project_exists` becomes a workspace-scoped
lookup (`GET /api/v4/projects/$project_id?workspaceId=$workspace_id`),
catching a misconfigured `project_id` that exists but belongs to a
*different* workspace than the one configured, not just "does this
project ID exist at all." See "Known Verification Gaps" for the caveat on
this specific query-parameter shape.

### Secrets

`BLAZEMETER_API_KEY_ID` and `BLAZEMETER_API_KEY_SECRET` are fixed
environment variable names the generated script reads at runtime,
delivered via HTTP Basic Auth (`curl -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET"`).
`customer.yaml` never contains the secret itself — same pattern as
LoadRunner's `LR_SSH_PRIVATE_KEY_PATH`/`LR_WINRM_PASSWORD`. `tool.auth.type`
stays `api_token` (unlike JMeter/LoadRunner's `none` — BlazeMeter is the
one tool here that genuinely manages a remote credential).

### `PRE_RUN_CHECKS` enum

BlazeMeter's real failure modes (host reachability, project existence,
test existence) don't map cleanly onto the existing LoadRunner/on-prem-
flavored vocabulary (`verify_controller_access`, `verify_load_generators_connected`).
`config/schema.py`'s `PRE_RUN_CHECKS` gains two new values:

- `verify_host_reachable` — a plain network-level reachability check
  against `base_url`, no auth involved.
- `verify_project_exists` — an authenticated check that the configured
  `project_id` exists and is accessible.

`verify_scenario_exists` (already existing) is reused as-is for "the
configured test ID exists" — no new value needed there, since that
concept already fits.

### Tool-aware wizard precheck menu

`wizard/flow.py`'s `_prompt_checks` currently shows all of
`PRE_RUN_CHECKS` regardless of which tool was selected — a customer
building a JMeter or LoadRunner setup could select `verify_host_reachable`/
`verify_project_exists` (meaningless for those tools) or a BlazeMeter setup
could select `verify_controller_access`/`verify_load_generators_connected`
(meaningless for BlazeMeter). A new `config/schema.py` mapping,
`PRE_RUN_CHECKS_BY_TOOL`, gives each tool its own applicable subset, and
`_prompt_checks` becomes tool-aware:

```python
PRE_RUN_CHECKS_BY_TOOL = {
    "jmeter": ["verify_scenario_exists", "collect_results"],
    "loadrunner_professional": [
        "verify_controller_access",
        "verify_scenario_exists",
        "verify_load_generators_connected",
        "collect_results",
    ],
    "blazemeter": [
        "verify_host_reachable",
        "verify_project_exists",
        "verify_scenario_exists",
        "collect_results",
    ],
}
```

This is additive to the wizard only — hand-edited YAML can still combine
any `pre_run_checks` value with any tool (same as today), and
`_allowed_pre_run_checks()` in `renderers/scripts.py` continues to filter
against the full `PRE_RUN_CHECKS` enum, not the per-tool subset, so a
hand-authored config isn't newly restricted. `PRE_RUN_CHECKS_BY_TOOL` only
changes which checkboxes the wizard *offers*.

## Generated Script Behavior

`_render_blazemeter_script` in `renderers/scripts.py` becomes a real
renderer (parallel to `_render_jmeter_script`/`_render_loadrunner_script`),
replacing its current use of the generic `_render_template_script`
template-stub helper — which becomes dead code once BlazeMeter is the
last caller removed, and is deleted (matching this project's established
no-dead-code discipline; see `CLAUDE.md`'s prior treatment of
`run_command`/`fixed_arguments`).

### Shared helper changes

**`_render_arg_parsing` gains an `include_timeout: bool = False` parameter.**
BlazeMeter's poll loop needs to know which `timeout_minutes` applies to
*this* invocation (the manual pipeline and each automated job can each
have a different configured value, and the script is shared across all of
them) — addressed by a new `--timeout-minutes` CLI flag, parsed and
required only when `include_timeout=True`. JMeter's and LoadRunner's
existing calls (`_render_arg_parsing()`, no argument) produce byte-for-byte
identical output to today — verified by construction: every new piece
individually defaults to an empty string when `include_timeout=False`, so
each templated line collapses to exactly its current text.

```python
def _render_arg_parsing(include_timeout: bool = False) -> str:
    timeout_local = ""
    timeout_case = ""
    timeout_required_check = ""
    timeout_usage = ""
    if include_timeout:
        timeout_local = '  local timeout_minutes=""\n'
        timeout_case = '      --timeout-minutes) timeout_minutes="$2"; shift 2 ;;\n'
        timeout_required_check = ' || [ -z "$timeout_minutes" ]'
        timeout_usage = ' --timeout-minutes <minutes>'

    return f"""  local environment_key=""
  local scenario_key=""
{timeout_local}  while [ $# -gt 0 ]; do
    case "$1" in
      --environment) environment_key="$2"; shift 2 ;;
      --scenario) scenario_key="$2"; shift 2 ;;
{timeout_case}      *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
  done

  if [ -z "$environment_key" ] || [ -z "$scenario_key" ]{timeout_required_check}; then
    echo "Usage: $0 --environment <key> --scenario <key>{timeout_usage}" >&2
    exit 1
  fi

  local environment_identifier
  local scenario_identifier
  environment_identifier="$(resolve_environment_identifier "$environment_key")"
  scenario_identifier="$(resolve_scenario_identifier "$scenario_key")"
"""
```

**`_render_loadrunner_slug_resolvers` is renamed `_render_slug_resolvers`**
and becomes shared between LoadRunner and BlazeMeter (both need a
path-traversal-safe `results_dir` built from catalog keys — see
"`results_dir` sanitization applies to BlazeMeter too" in the script body
above). Its implementation is unchanged — only its name, and the fact that
`_render_blazemeter_script` calls it too. This rename has one required
consequential edit: `_render_loadrunner_script`'s existing call site
(currently `{_render_loadrunner_slug_resolvers(package)}`) must be updated
to call `_render_slug_resolvers(package)` under the new name, or the
rename leaves a dangling reference and LoadRunner's script generation
breaks with a `NameError` at import/call time. Any implementer of this
spec touches that call site as part of the same commit that does the
rename — it is not optional cleanup.

### `_render_blazemeter_script`

```python
def _render_blazemeter_script(config: dict, package: GenericPipelinePackage) -> str:
    connection = config.get("tool", {}).get("connection", {})
    base_url = connection.get("base_url") or TODO_VALUE
    workspace_id = connection.get("workspace_id") or TODO_VALUE
    project_id = connection.get("project_id") or TODO_VALUE
    checks = _allowed_pre_run_checks(config)

    host_check = ""
    if "verify_host_reachable" in checks:
        host_check = """
  if ! curl -s -o /dev/null "$base_url"; then
    echo "ERROR: cannot reach BlazeMeter host: $base_url" >&2
    exit 1
  fi
"""

    project_check = ""
    if "verify_project_exists" in checks:
        project_check = """
  project_status=$(curl -s -o /dev/null -w "%{http_code}" -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
    "$base_url/api/v4/projects/$project_id?workspaceId=$workspace_id")
  if [ "$project_status" != "200" ]; then
    echo "ERROR: BlazeMeter project not found in workspace, or inaccessible: project $project_id, workspace $workspace_id (HTTP $project_status)" >&2
    exit 1
  fi
"""

    scenario_check = ""
    if "verify_scenario_exists" in checks:
        scenario_check = """
  test_status=$(curl -s -o /dev/null -w "%{http_code}" -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
    "$base_url/api/v4/tests/$scenario_identifier")
  if [ "$test_status" != "200" ]; then
    echo "ERROR: BlazeMeter test not found or inaccessible: $scenario_identifier (HTTP $test_status)" >&2
    exit 1
  fi
"""

    remaining_checks = [
        check for check in checks
        if check not in {"verify_host_reachable", "verify_project_exists", "verify_scenario_exists"}
    ]
    precheck_comments = "\n".join(f"  # TODO precheck: {check}" for check in remaining_checks)
    if precheck_comments:
        precheck_comments = f"\n{precheck_comments}\n"

    return f"""#!/usr/bin/env bash
set -euo pipefail

{_render_resolvers(package)}

{_render_slug_resolvers(package)}

main() {{
{_render_arg_parsing(include_timeout=True)}
  mkdir -p run-output

  if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq is required to parse BlazeMeter API responses but was not found." >&2
    exit 1
  fi
  : "${{BLAZEMETER_API_KEY_ID:?BLAZEMETER_API_KEY_ID must be set}}"
  : "${{BLAZEMETER_API_KEY_SECRET:?BLAZEMETER_API_KEY_SECRET must be set}}"

  local base_url={shell_quote(base_url)}
  local workspace_id={shell_quote(workspace_id)}
  local project_id={shell_quote(project_id)}
{host_check}{project_check}{scenario_check}{precheck_comments}
  local environment_slug
  local scenario_slug
  environment_slug="$(resolve_environment_slug "$environment_key")"
  scenario_slug="$(resolve_scenario_slug "$scenario_key")"
  local results_dir="run-output/${{environment_slug}}_${{scenario_slug}}"
  mkdir -p "$results_dir"

  local start_response
  start_response="$(curl -s -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
    -X POST "$base_url/api/v4/tests/$scenario_identifier/start")"
  local master_id
  master_id="$(echo "$start_response" | jq -r '.result.id')"
  if [ -z "$master_id" ] || [ "$master_id" = "null" ]; then
    echo "ERROR: BlazeMeter did not return a master id when starting the test. Response: $start_response" >&2
    exit 1
  fi

  # NOTE: the exact status-string vocabulary below (ENDED/ERROR/ABORTED)
  # and the reports/main/summary endpoint used after the loop are our best
  # understanding of the BlazeMeter API v4 as of this writing -- verify
  # both against a live BlazeMeter account before relying on this in
  # production (see the design spec's "Known Verification Gaps").
  local deadline=$(( $(date +%s) + timeout_minutes * 60 ))
  local status="UNKNOWN"
  while [ "$(date +%s)" -lt "$deadline" ]; do
    status="$(curl -s -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
      "$base_url/api/v4/masters/$master_id/status" | jq -r '.result.status')"
    case "$status" in
      ENDED) break ;;
      ERROR|ABORTED)
        echo "ERROR: BlazeMeter test ended with status $status (master $master_id)" >&2
        exit 1
        ;;
    esac
    sleep 15
  done
  if [ "$status" != "ENDED" ]; then
    echo "ERROR: Timed out after $timeout_minutes minutes waiting for BlazeMeter test to finish (master $master_id, last status: $status)" >&2
    exit 1
  fi

  curl -s -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
    "$base_url/api/v4/masters/$master_id/reports/main/summary" > "$results_dir/summary.json"
  printf '{{"master_id": "%s", "report_url": "%s/app/#/masters/%s/summary"}}' \\
    "$master_id" "$base_url" "$master_id" > "$results_dir/report_link.json"
}}

if [ "${{BASH_SOURCE[0]:-$0}}" = "$0" ]; then
  main "$@"
fi
"""
```

Notes:

- `base_url`/`workspace_id`/`project_id` are rendered via `shell_quote`
  exactly like every other config-derived value in this file.
- Each of the three prechecks (`verify_host_reachable`,
  `verify_project_exists`, `verify_scenario_exists`) only runs when
  configured in `pre_run_checks` — same "gated, not unconditional" rule
  the LoadRunner work established and the final review verified.
  `verify_project_exists` is workspace-scoped (`?workspaceId=$workspace_id`
  on the projects lookup), so it validates that `project_id` exists *and*
  belongs to the configured `workspace_id`, not just that the ID exists
  under any workspace the API key can see.
- Any other configured-but-unhandled check (currently only
  `verify_controller_access`/`verify_load_generators_connected`, which
  don't apply to BlazeMeter, plus `collect_results`) renders a
  `# TODO precheck: ...` comment rather than silently vanishing — this is
  the exact fix the LoadRunner final review required, applied here from
  the start rather than needing a follow-up fix wave.
- `results_dir` is built from `environment_slug`/`scenario_slug` (resolved
  via the shared, sanitizing slug resolvers), not raw catalog keys — same
  path-traversal protection the LoadRunner final review required.

## CI/CD Renderer Changes

`--timeout-minutes` is inert unless something actually passes it — none of
the three CI/CD renderers know about it today. Each renderer builds its
`./scripts/run-<tool_type>.sh --environment ... --scenario ...` invocation
in exactly two places (the manual pipeline and the automated-job template),
six call sites total across `github_actions.py`, `azure_devops.py`, and
`jenkins.py`. Each of those six gains a conditional append, only for
`blazemeter`, using whichever `timeout_minutes` value is already in scope
at that call site (the manual pipeline's `package.manual_pipeline.timeout_minutes`,
or the automated job's own `job.timeout_minutes` — both already local
variables/attributes at every one of the six sites, so no new data needs
to be threaded through).

Illustrating the pattern on `github_actions.py`'s automated-job renderer
(the other five sites follow the identical shape — an `if package.tool_type
== "blazemeter":` appending ` --timeout-minutes <value>` to the same line
that already builds the invocation string):

Before:

```python
def _render_automated_workflow(job, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    return f"""name: {yaml_dquote(f"Performance Automated Job - {job.name}")}

on:
  workflow_call:

jobs:
  {job_id}:
    runs-on: ubuntu-latest
    timeout-minutes: {job.timeout_minutes}
    steps:
      - uses: actions/checkout@v4
      - name: Run performance wrapper
        run: >
          ./scripts/run-{tool_type}.sh
          --environment {shell_quote(job.environment_ref)}
          --scenario {shell_quote(job.scenario_ref)}
```

After:

```python
def _render_automated_workflow(job, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    timeout_flag = f"\n          --timeout-minutes {job.timeout_minutes}" if tool_type == "blazemeter" else ""
    return f"""name: {yaml_dquote(f"Performance Automated Job - {job.name}")}

on:
  workflow_call:

jobs:
  {job_id}:
    runs-on: ubuntu-latest
    timeout-minutes: {job.timeout_minutes}
    steps:
      - uses: actions/checkout@v4
      - name: Run performance wrapper
        run: >
          ./scripts/run-{tool_type}.sh
          --environment {shell_quote(job.environment_ref)}
          --scenario {shell_quote(job.scenario_ref)}{timeout_flag}
```

`_render_automated_workflow` already receives `tool_type` as a parameter
(both GitHub Actions functions do; Azure DevOps's and Jenkins's equivalent
functions do too), so this needs no new parameter threading anywhere — the
same `if tool_type == "blazemeter":`/`if package.tool_type == "blazemeter":`
conditional (whichever the surrounding function already has in scope)
applies at each of the other five sites, appending `--timeout-minutes
{value}` (or the platform's own env-var-indirection equivalent, for the two
manual-pipeline sites, which already deliver `--environment`/`--scenario`
via `$ENVIRONMENT`/`$SCENARIO` rather than splicing the value directly —
`timeout_minutes` is not a build-trigger-controlled value the way
environment/scenario are, since it comes from `customer.yaml` at generation
time, not from a workflow-dispatch input, so splicing it directly via
Python f-string interpolation at generation time carries none of the
injection risk that motivated `env:`-indirection for `--environment`/
`--scenario` — it's a plain positive integer already validated at wizard/
config-load time, not user-input reachable through a build trigger).

Existing renderer tests for JMeter/LoadRunner Professional configs are
unaffected (their `tool_type` is never `"blazemeter"`, so `timeout_flag`
is always `""` for them). New renderer tests confirm a BlazeMeter config's
generated manual-pipeline and automated-job files each contain
`--timeout-minutes <value>` with the correct value for their respective
timeout source.

## Related Fix: `_render_jmeter_script` gains the same TODO-comment behavior

While implementing the per-tool precheck vocabulary, a pre-existing,
previously-undiscovered instance of the same "silently dropped check" bug
was found in `_render_jmeter_script`: today, a hand-authored config with
`tool.type: jmeter` and `verify_controller_access` (or
`verify_load_generators_connected`) in `pre_run_checks` produces a
generated script that silently ignores that check entirely — no guard, no
comment, nothing. This predates this task and wasn't caught by the
LoadRunner final review (out of its diff's scope at the time). Given this
task already touches `_allowed_pre_run_checks`'s call sites and is
establishing the "render a TODO comment for anything configured-but-
unhandled" pattern for BlazeMeter, `_render_jmeter_script` gets the same
treatment for consistency: any check other than `verify_scenario_exists`
that's configured renders a `# TODO precheck: ...` comment.

```python
def _render_jmeter_script(config: dict, package: GenericPipelinePackage) -> str:
    connection = config.get("tool", {}).get("connection", {})
    test_plan_path = connection.get("test_plan_path") or TODO_VALUE
    jmeter_bin = connection.get("jmeter_bin") or "jmeter"
    checks = _allowed_pre_run_checks(config)

    precheck = ""
    if "verify_scenario_exists" in checks:
        precheck = """
  if [ ! -f "$test_plan_path" ]; then
    echo "Test plan not found: $test_plan_path" >&2
    exit 1
  fi
"""

    remaining_checks = [check for check in checks if check != "verify_scenario_exists"]
    precheck_comments = "\n".join(f"  # TODO precheck: {check}" for check in remaining_checks)
    if precheck_comments:
        precheck_comments = f"\n{precheck_comments}\n"

    return f"""#!/usr/bin/env bash
set -euo pipefail

{_render_resolvers(package)}

main() {{
{_render_arg_parsing()}
  mkdir -p run-output

  local test_plan_path={shell_quote(test_plan_path)}
  local jmeter_bin={shell_quote(jmeter_bin)}
{precheck}{precheck_comments}
  "$jmeter_bin" -n -t "$test_plan_path" -l run-output/results.jtl -e -o run-output/report \\
    -Jenvironment="$environment_identifier" -Jscenario="$scenario_identifier"
}}

if [ "${{BASH_SOURCE[0]:-$0}}" = "$0" ]; then
  main "$@"
fi
"""
```

Only the two lines around `{precheck}{precheck_comments}` and the new
`remaining_checks`/`precheck_comments` computation change; everything else
in this function is identical to today. This is a small, self-contained
consistency fix, not a redesign of JMeter's script.

## Error Handling

- **`jq` not found**: `"ERROR: jq is required to parse BlazeMeter API
  responses but was not found."`, exit 1. This is the one check in the
  script that is *not* gated behind a `pre_run_checks` value, and
  deliberately so: every other gated check (host reachable, project
  exists, test exists) validates something about the *target environment*
  that a customer might reasonably already know is fine and choose to
  skip — that's what `pre_run_checks` is for. `jq` availability isn't a
  property of the target environment being validated; it's a hard
  prerequisite for this script's own operation, in the same category as
  the shebang line or `set -euo pipefail` itself — there is no scenario
  where skipping this check is a meaningful customer choice, since every
  subsequent step in the script pipes a response through `jq`.
- **Missing secrets**: `: "${VAR:?message}"` bash idiom gives a clear error
  immediately if `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET` aren't
  set, before any network call.
- **Host unreachable** (only if `verify_host_reachable` configured):
  `"ERROR: cannot reach BlazeMeter host: $base_url"`, exit 1.
- **Project/test not found** (only if the respective check configured):
  `"ERROR: BlazeMeter project/test not found or inaccessible: ... (HTTP
  ...)"`, exit 1.
- **Start failure**: if the start response has no usable `master_id`,
  `"ERROR: BlazeMeter did not return a master id ..."` with the raw
  response included, exit 1.
- **Run failure**: `ERROR`/`ABORTED` status during polling exits
  immediately with that status named, rather than waiting out the full
  timeout for a run that has already failed.
- **Timeout**: exceeding `--timeout-minutes` without reaching `ENDED`
  reports the last known status and exits 1, distinguishing "still
  running when we gave up" from "failed."
- **Unrecognized `--environment`/`--scenario` key**: unchanged, handled by
  the shared resolver functions.

## Testing Strategy

Same "no live network calls in tests" approach already used for JMeter and
LoadRunner:

- Content assertions on the rendered script (correct `curl`/`jq` command
  shapes, correct env var guard lines, correct gating of each of the three
  prechecks) plus `bash -n` syntax checks. Specifically confirms
  `verify_project_exists`'s query includes `?workspaceId=$workspace_id`,
  not just `project_id` alone.
- A test proving `--timeout-minutes` is required and parsed correctly at
  the script-rendering level, and that JMeter's and LoadRunner's existing
  arg-parsing-related test assertions are completely unaffected (the
  shared `_render_arg_parsing` change is additive-only for those two
  tools).
- Renderer-level tests (one per CI/CD platform) confirming a BlazeMeter
  config's generated manual-pipeline and automated-job files each contain
  `--timeout-minutes <value>` with the correct value, and that existing
  JMeter/LoadRunner renderer tests (whose fixtures never use
  `tool_type: blazemeter`) still pass unmodified.
- A test proving `results_dir` sanitization applies to BlazeMeter too,
  reusing the same hostile-catalog-key technique the LoadRunner final
  review's fix introduced.
- A test proving unhandled checks (any value outside
  `{verify_host_reachable, verify_project_exists, verify_scenario_exists}`)
  render as `# TODO precheck: ...` comments rather than vanishing, and an
  equivalent test for the `_render_jmeter_script` fix.
- No test executes against a real BlazeMeter API — that's roadmap item 14.

## Example Config Migration

The three `examples/*-blazemeter/customer.yaml` files need:

- `catalog.scenarios` reshaped into per-(environment, scenario) entries
  whose `identifier` looks like a real BlazeMeter numeric Test ID (e.g.
  `qa_smoke_qa` → `"1234567"`), matching the convention already established
  for LoadRunner rather than the current slug-like placeholders (e.g.
  `bm-qa-smoke`).
- `pre_run_checks` updated to include `verify_host_reachable` and
  `verify_project_exists` alongside the already-present
  `verify_scenario_exists`/`collect_results`, so the examples exercise the
  new checks.
- `tool.connection` (`base_url`/`workspace_id`/`project_id`) and
  `tool.auth.type: api_token` stay unchanged.

## Documentation Updates

- `renderers/readme.py`: the `if tool_type == "blazemeter":` branch that
  currently prints "Fill in the actual API/controller call ..." is
  replaced with a caveat about setting the two secret env vars and a note
  that the status-vocabulary/report-endpoint are best-understanding,
  needing verification against a live account — mirroring exactly how
  LoadRunner's README branch was replaced with its agent-targeting caveat.
- `docs/pipeline-generator-user-guide.md`: section 10's BlazeMeter bullet
  moves from "a template" to "real, working execution," with the same
  verification caveat as above. The wizard's Step 4 connection-fields
  table gains a note about the tool-aware precheck menu. The
  troubleshooting section's "not implemented yet" entries for BlazeMeter
  are removed (only pointing at genuinely-possible errors now: `jq`
  missing, secrets missing, host/project/test-not-found, timeout).
- `docs/current-state-and-readiness-plan.md`: BlazeMeter moves out of every
  "still a template" list (this project now has zero template-only tools);
  "Recommended Implementation Order" items 11 and 13 get checked off
  (13's remaining part — `verify_load_generators_connected` staying a TODO
  comment — was already true for LoadRunner and stays true for BlazeMeter,
  so nothing contradicts it).
- `README.md`: "Recommended Next Work" drops its BlazeMeter bullet.

## Known Verification Gaps

Documented explicitly, in both code comments and the generated setup
README, rather than silently assumed correct:

- The exact BlazeMeter API v4 status-string vocabulary during polling
  (`ENDED`/`ERROR`/`ABORTED`) is this design's best understanding, not
  independently verified against current live documentation (which sits
  behind a login-gated API explorer this design couldn't access).
- The `reports/main/summary` endpoint used for the final artifact is
  likewise best-understanding, not independently verified.
- The workspace-scoped project lookup's exact query-parameter shape
  (`?workspaceId=$workspace_id` on `GET /api/v4/projects/$project_id`) is
  also best-understanding rather than confirmed against current API
  documentation — if the real parameter name or semantics differ,
  `verify_project_exists` would need adjusting, but the failure mode is
  contained (a wrong parameter name most likely means BlazeMeter ignores
  it and the check silently stops being workspace-scoped, still correctly
  validating "project exists," rather than the script misbehaving or
  reaching the wrong project).
- All three should be confirmed against a real BlazeMeter account (or
  updated API documentation) before this script is relied on for a
  production test run, the same "honest not-done-yet" stance already
  applied to `wlrun`'s documented exit-code unreliability.

## Rejected Alternatives

**Hand-rolled JSON parsing (grep/sed) instead of `jq`.** Would keep the
script's dependency footprint at zero beyond the tool itself, but JSON
extraction via regex is fragile and error-prone to get fully correct.
`jq` is small, extremely common, and preinstalled on GitHub-hosted and
Azure-hosted runners — the same reasoning that led to accepting `pwsh` as
a dependency for LoadRunner's (ultimately rejected) WinRM path.

**Environment as a runtime BlazeMeter test property instead of a per-
environment Test ID.** BlazeMeter's start API does accept property
overrides, which could parameterize a single Test the way JMeter's `-J`
properties do — but only if the customer's underlying test script is
written to honor that property, an assumption this design can't verify
generically. The per-environment-Test-ID convention (identical to
LoadRunner's per-environment `.lrs` convention) needs no such assumption.

**Status + summary JSON only, no downloadable report artifacts.**
Simpler and needs less certainty about exact endpoints, but was explicitly
not what was asked for — full report-artifact collection was the chosen
option, accepting the endpoint-verification risk documented above as the
cost of that choice.
