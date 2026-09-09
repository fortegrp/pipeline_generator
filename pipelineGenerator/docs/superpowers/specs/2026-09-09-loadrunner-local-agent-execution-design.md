# LoadRunner Professional Local-Agent Execution Design

## Purpose

`generate` currently writes `scripts/run-loadrunner_professional.sh` as a
template: real, syntactically valid bash with connection details filled in
as variables, but it always ends in
`echo "ERROR: LoadRunner Professional execution is not implemented in this
generated script yet." >&2; exit 1`. This is roadmap item 12 ("Define
LoadRunner Execution Strategy") — making that script real, the same way
JMeter's already is.

This design targets the deployment model where the CI/CD job itself runs on
a dedicated, self-hosted agent (a Jenkins agent or an Azure DevOps
self-hosted agent) that is co-located with the LoadRunner Controller —
i.e., LoadRunner's `wlrun.exe` command-line tool is already on that
machine's `PATH` (or at a known path). The generated script does not
remote into anything; it calls `wlrun` directly, the same shape as
JMeter's script calling `jmeter` directly.

Two other execution strategies (an SSH/WinRM-based "remote wrapper script"
model, and driving the LoadRunner Enterprise REST API) were explored and
rejected for this iteration in favor of this simpler, no-remoting design —
see "Rejected Alternatives" below.

## Non-Goals

- Remote execution over SSH or WinRM. Not needed once the agent is assumed
  to be co-located with the controller.
- LoadRunner Enterprise (Performance Center) REST API integration. A real
  possibility for a future iteration if a customer needs it, but out of
  scope here.
- `verify_load_generators_connected` as a real check. This needs
  Controller-side load-generator host-status querying with no local CLI
  equivalent; it remains a `# TODO precheck: ...` comment, same as today.
- Changing what `collect_results` means (a pre-existing open question
  noted in the readiness plan, unrelated to this work).
- Tests that exercise a real `wlrun` binary or a real LoadRunner
  installation. That's roadmap item 14 ("mocked/fake remote systems"),
  explicitly future work.

## Config Shape Changes

### `tool.connection` for `loadrunner_professional`

Before (current, unused fields being removed):

```yaml
tool:
  type: loadrunner_professional
  connection:
    controller_host: lr.acme.local
    controller_results_path: C:\Results
    domain: DEFAULT
    project: ACME
```

After:

```yaml
tool:
  type: loadrunner_professional
  connection:
    wlrun_path: wlrun # optional; defaults to "wlrun" if omitted, same pattern as JMeter's jmeter_bin
```

`controller_host`, `controller_results_path`, `domain`, and `project` are
dropped entirely — they were placeholders from before an execution model
was decided, and none of them apply to local `wlrun` invocation.

### Catalog shape

LoadRunner's `wlrun` takes a single scenario file (`-TestPath <file.lrs>`)
per invocation and has no built-in "environment" parameter — a scenario
file's target environment is normally baked into the file itself, not
switched at runtime. To fit the project's existing two-axis
(`environment_ref` + `scenario_ref`) model without inventing a new concept,
customers author one catalog **scenario** entry per (environment, scenario)
combination they have a `.lrs` file for:

```yaml
catalog:
  environments:
    - key: qa
      name: QA
      identifier: QA # display/labeling only for LoadRunner; not fed into wlrun
    - key: staging
      name: Staging
      identifier: Staging
  scenarios:
    - key: checkout_smoke_qa
      name: Checkout Smoke (QA)
      identifier: C:\Scenarios\checkout_smoke_qa.lrs
    - key: checkout_smoke_staging
      name: Checkout Smoke (Staging)
      identifier: C:\Scenarios\checkout_smoke_staging.lrs
```

An automated job or manual-pipeline invocation still supplies both
`--environment <env_key>` and `--scenario <scenario_key>` as today (the CLI
contract of `scripts/run-loadrunner_professional.sh` is unchanged from the
other tools' scripts) — the environment key is used only to name the
results folder (see below), while the scenario key resolves to the actual
`.lrs` path that gets run. This means a customer's catalog does the work of
mapping (environment, scenario) pairs to files; the generated script itself
has no per-environment branching logic.

This is a deliberate trade-off: it pushes the combinatorial (environment ×
scenario) mapping onto the customer's catalog rather than the generated
script, but matches how LoadRunner customers already tend to organize
scenario files in practice (one file per environment they test against).

## Generated Script Behavior

`_render_loadrunner_script` in `renderers/scripts.py` becomes a real
renderer (parallel to `_render_jmeter_script`), replacing its current use
of the generic `_render_template_script` template-stub helper.

```bash
#!/usr/bin/env bash
set -euo pipefail

<resolvers: resolve_environment_identifier / resolve_scenario_identifier>

main() {
  <arg parsing: --environment/--scenario -> environment_key/scenario_key,
   then environment_identifier/scenario_identifier via the resolvers>

  local wlrun_path=<shell_quote(wlrun_path)>

  <if verify_controller_access in pre_run_checks:>
  if ! command -v "$wlrun_path" >/dev/null 2>&1; then
    echo "ERROR: wlrun not found: $wlrun_path" >&2
    exit 1
  fi

  <if verify_scenario_exists in pre_run_checks:>
  if [ ! -f "$scenario_identifier" ]; then
    echo "Scenario file not found: $scenario_identifier" >&2
    exit 1
  fi

  local results_dir="run-output/${environment_key}_${scenario_key}"
  mkdir -p "$results_dir"

  # Note: wlrun's exit code is known to be unreliable on some LoadRunner
  # versions/configurations (it can return 0 even when a scenario had
  # errors). We treat nonzero as failure since it is the best signal
  # available locally; check the results directory's own reports for the
  # authoritative pass/fail status.
  "$wlrun_path" -Run -TestPath "$scenario_identifier" -ResultName "$results_dir"
}

if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
  main "$@"
fi
```

Notes:

- `wlrun_path` is rendered via `shell_quote` exactly like every other
  config-derived value in this file, consistent with the rest of
  `renderers/scripts.py`.
- `environment_key`/`scenario_key` (the raw `--environment`/`--scenario`
  argument values, i.e. the catalog keys, not the resolved identifiers) are
  used to build `results_dir`. These are the same trusted, config-defined
  catalog keys the exact-match resolvers already compare against — no new
  trust boundary is introduced by using them in a path segment.
- `verify_controller_access` (an existing `PRE_RUN_CHECKS` enum value) is
  reinterpreted for this tool as "is `wlrun_path` a runnable command" —
  the closest local analog to "can we reach the controller" now that there
  is no remote hop. Like every other check in `PRE_RUN_CHECKS`, it only
  runs when configured in `pre_run_checks` — there is no unconditional
  "always on" check anywhere in this script, consistent with how
  `verify_scenario_exists` already gates the JMeter and (now) LoadRunner
  scenario-file checks. If `wlrun_path` is wrong and this check isn't
  configured, `wlrun` still fails naturally with its own "command not
  found" error when invoked — the check just makes that failure message
  clearer and catches it before a scenario-file check or run attempt, for
  customers who opt in.

## Error Handling

- **`wlrun` not found**: `"ERROR: wlrun not found: $wlrun_path"`, exit 1.
  Checked first among the configured prechecks, only when
  `verify_controller_access` is in `pre_run_checks`; otherwise `wlrun`'s
  own "command not found" failure surfaces when the run attempt reaches
  it.
- **Scenario file missing** (only if `verify_scenario_exists` is
  configured): `"Scenario file not found: $scenario_identifier"`, exit 1.
  Same shape as JMeter's existing test-plan-path check.
- **`wlrun` run failure**: `set -euo pipefail` propagates `wlrun`'s own
  nonzero exit code, causing the script to exit with that same code — no
  extra wrapping needed, since there's no remote hop whose failure mode
  needs disambiguating from the tool's own failure (unlike the
  SSH/WinRM design that was rejected, this has only one thing that can
  fail: `wlrun` itself).
- **Unrecognized `--environment`/`--scenario` key**: unchanged, already
  handled by the shared resolver functions (`Unknown environment key: ...`
  / `Unknown scenario key: ...`, exit 1).

## Testing Strategy

Mirrors the existing JMeter script tests in `tests/test_tool_scripts.py`
(`test_render_jmeter_script_with_precheck`,
`test_render_jmeter_script_without_precheck_flag`) — no live `wlrun`
binary involved, consistent with the "no live remote calls in tests"
approach already used everywhere else in this file:

- `test_render_loadrunner_script_runs_wlrun_for_real` — asserts the
  rendered script contains
  `"$wlrun_path" -Run -TestPath "$scenario_identifier" -ResultName "$results_dir"`
  in the right shape, that `outputs == [script_path]`, that the file is
  executable, and that `bash -n` accepts it. Replaces the current
  `test_render_loadrunner_professional_script_is_a_template` (which
  asserted the old `# TODO precheck: ...` / `"... not implemented ..."`
  template shape — that assertion becomes wrong once this ships and must
  be replaced, not kept alongside the new test).
- `test_render_loadrunner_script_checks_wlrun_availability` — asserts the
  `command -v "$wlrun_path"` guard and its error message are present only
  when `verify_controller_access` is configured, and absent otherwise
  (same "gated, not unconditional" shape as the scenario-exists check
  below).
- `test_render_loadrunner_script_with_scenario_exists_precheck` — asserts
  the `[ ! -f "$scenario_identifier" ]` guard appears only when
  `verify_scenario_exists` is configured (mirrors
  `test_render_jmeter_script_without_precheck_flag`'s "absent when not
  configured" shape).
- Adversarial coverage for `wlrun_path` values containing spaces (e.g. a
  Windows path like `C:\Program Files\LoadRunner\bin\wlrun.exe`) — asserts
  `shell_quote` produces a properly quoted `local wlrun_path=...` line and
  `bash -n` still accepts the script. This is the same style of adversarial
  test already used for connection variables elsewhere in this file (e.g.
  the BlazeMeter test's backslash-containing value assertions), just
  applied to the new field.

## Example Config Migration

`examples/github-loadrunner/customer.yaml`,
`examples/azure-loadrunner/customer.yaml`, and
`examples/jenkins-loadrunner/customer.yaml` each need:

- `tool.connection` reduced to just `wlrun_path: wlrun`.
- `catalog.scenarios` reshaped into per-(environment, scenario) `.lrs`
  entries, e.g. `checkout_smoke_qa` → `C:\Scenarios\checkout_smoke_qa.lrs`
  and `checkout_smoke_staging` → `C:\Scenarios\checkout_smoke_staging.lrs`
  (each example can keep its existing single environment/scenario pairing
  extended to two environments, so the reshaped catalog is exercised by at
  least one example without needing to touch `automated_jobs`/
  `manual_pipeline` shape).
- `catalog.environments`' `identifier` values become plain display labels
  (e.g. `QA`, `Staging`) rather than anything wlrun-facing, since
  environment identifiers are no longer passed to `wlrun` at all.

No other example configs (JMeter, BlazeMeter) are affected.

## Generated README Changes

`renderers/readme.py`'s `render_setup_readme` currently branches on
`tool_type in {"blazemeter", "loadrunner_professional"}` to print "Fill in
the actual API/controller call in `{script_name}` (marked with `# TODO`)."
as a remaining-TODO line, falling back to a generic "Implement remote tool
connectivity details required by the target customer." line for any other
tool (today, only `jmeter`). Once LoadRunner Professional is real, it must
move out of that set — leaving it in would print a misleading TODO in
every generated LoadRunner setup's README even though nothing is left to
fill in. `loadrunner_professional` joins `jmeter` on the generic-message
side of that branch (`{"blazemeter"}` becomes the only tool_type left in
the TODO-API-call set), covered by a test asserting the generated README
for a `loadrunner_professional` config no longer contains "actual
API/controller call".

## Documentation Updates

- `docs/pipeline-generator-user-guide.md`: the "Step 4 is where the three
  tools currently differ" section gains a LoadRunner Professional bullet
  matching JMeter's ("real, working execution") in place of its current
  "a template" wording, describing the `wlrun_path` field, the
  per-environment-`.lrs`-file catalog convention, and the `wlrun` exit-code
  reliability caveat.
- `docs/current-state-and-readiness-plan.md`: update the "BlazeMeter and
  LoadRunner Professional Scripts Are Templates, Not Adapters" section to
  reflect LoadRunner Professional moving from "template" to "real,
  working execution" (mirroring how JMeter's entry already reads), and
  check off the relevant items this closes: "Recommended Implementation
  Order" item 12 (the controller-call portion), and Milestone 2's own
  sub-list item 3 ("Implement Real Pre-Run Checks")'s
  `verify_scenario_exists`-for-LoadRunner line — `verify_controller_access`
  is also effectively real now, though its LoadRunner meaning has shifted
  to "is wlrun runnable" rather than "can we reach the controller".
- `README.md`: "Recommended Next Work" drops its LoadRunner Professional
  bullet once this ships (BlazeMeter's stays).

## Rejected Alternatives

**SSH/WinRM remote wrapper script.** An earlier iteration of this design
had the generated script remoting into the controller over SSH or WinRM to
invoke a customer-provided wrapper script, with an `execution_mode` field
choosing between the two transports. This was rejected in favor of the
local-agent model once it was clarified that the intended deployment
already runs the CI/CD job on an agent co-located with the controller,
making all the remoting — and its non-trivial safe-quoting requirements
for values re-parsed by a remote shell — unnecessary complexity for the
target use case.

**LoadRunner Enterprise REST API.** Considered as the "flexible/API-driven"
option analogous to BlazeMeter's REST API. Rejected for this iteration
because it only applies to customers on LoadRunner Enterprise (formerly
Performance Center) specifically, not classic LoadRunner Professional
Controller-only deployments, which is the tool type this config models.
Could be revisited as a distinct addition later if a customer's deployment
calls for it.
