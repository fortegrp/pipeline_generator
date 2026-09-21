# Environment-Scoped Scenarios: Design

## Problem

`catalog.environments` and `catalog.scenarios` are two flat, independent
lists. The manual pipeline's generated trigger UI (GitHub Actions
`workflow_dispatch`, Azure `parameters`, Jenkins `choice` parameters)
exposes them as two separate dropdowns, freely combinable. Nothing —
not the wizard, not `validate`, not the generated pipeline's own UI, not
`verify_scenario_exists` (which only checks the identifier's target
exists, not that it's the right target for the chosen environment) —
prevents selecting an invalid pair.

This isn't hypothetical: every multi-environment example config in this
repo already encodes the real relationship through naming convention,
because there's no structural way to express it. `examples/github-
loadrunner/customer.yaml` has `checkout_smoke_qa` and
`checkout_smoke_staging` as two unrelated top-level scenario entries —
the `_qa`/`_staging` suffix is the customer doing the tool's job by hand.
A LoadRunner scenario identifier is a specific `.lrs` file path; running
`checkout_smoke_qa`'s file while labeling the results "staging" produces
a real, misleading result with no error anywhere in the pipeline.

Automated jobs (`environment_ref` + `scenario_ref`) already sidestep this
by hard-pinning one pair per job at generation time — which is *why* that
step also feels awkward: covering N environments × M scenarios needs
N×M job entries, one wizard pass each.

## Goal

Make an invalid environment+scenario combination structurally
unselectable in the manual pipeline's trigger UI, not just documented as
a footgun. Scoped explicitly to the catalog model in this pass — runner/
agent targeting and BlazeMeter secret wiring are separate, already-flagged
issues, deliberately out of scope here.

## Non-goals

- No migration shim / dual-schema support for old `catalog.scenarios`
  configs. This is a breaking schema change, consistent with every other
  schema change made this cycle — old configs are rewritten, not
  auto-upgraded.
- No surgical "add one scenario to an existing environment without
  touching the rest" wizard flow. Same as today's model: hand-editing the
  YAML afterward is an established, supported way to make small changes.
- No change to `run-summary.json`'s schema (`environment`/`scenario`
  stay separate fields) — this file is a documented, stable contract for
  whatever runs downstream of `scripts/run-<tool_type>.sh`.

## A. Schema

`catalog.scenarios` (top-level) is removed. Scenarios nest under their
owning environment:

```yaml
catalog:
  environments:
    - key: qa
      identifier: QA
      scenarios:
        - key: checkout_smoke
          identifier: C:\Scenarios\checkout_smoke_qa.lrs
        - key: browse_baseline
          identifier: C:\Scenarios\browse_baseline_qa.lrs
    - key: staging
      identifier: Staging
      scenarios:
        - key: checkout_smoke
          identifier: C:\Scenarios\checkout_smoke_staging.lrs
```

A scenario `key` only needs to be unique *within* its environment —
`checkout_smoke` can exist under both `qa` and `staging` with different
identifiers, which is what retires the `_qa`/`_staging` suffix
convention.

`automated_jobs[].environment_ref`/`scenario_ref` keep their field names
and meaning; `scenario_ref` is now validated against that specific
environment's scenario list rather than a global one.

`base_config()`'s `catalog` becomes `{"environments": []}` — no top-level
`scenarios` key.

## B. Wizard flow

**Step 5 (`_step_catalog`)**: collecting a *new* environment immediately
continues into collecting its scenarios (key + tool-specific identifier,
same loop shape used today) before moving to the next environment —
one nested loop instead of two flat passes. Resuming still uses the
existing keep-as-is/add-more/start-over pattern over the whole
environment list (each environment carries its scenario list along).

**Step 6 (automated jobs)**: `environment_ref` is picked first (as
today); `scenario_ref` is then offered only from *that environment's*
scenarios via `prompt_choice`, not a global list — the wizard already has
the data to filter correctly, so this is a strict UX improvement, not
just a correctness fix.

The `CATALOG_IDENTIFIER_PROMPTS` tool-specific wording added last cycle
carries forward unchanged; the fact that environment `identifier` is
real only for JMeter (not consumed by the LoadRunner/BlazeMeter scripts)
is orthogonal to this redesign and stays as-is per the earlier explicit
decision to keep asking it anyway.

## C. Generic model + generator (`generic_model.py`, `context.py`)

`InputOption` (`value: str`, `identifier: str`) is unchanged. What
changes is what populates it: `context.py` walks
`catalog.environments[].scenarios[]` and builds one `InputOption` per
valid **pair**, all sharing the same combined `value` —

```python
def _test_case_value(environment_key: str, scenario_key: str) -> str:
    return f"{environment_key}: {scenario_key}"
```

Two parallel `InputOption` lists come out of this walk (mirroring
today's `environments`/`scenarios` lists on `GenericPipelinePackage`,
so `scripts.py`'s existing `_render_resolvers`/`_render_slug_resolvers`
machinery needs no changes at all):

- one list where `.value` = combined pair string, `.identifier` =
  environment identifier for that pair
- one list where `.value` = the **same** combined pair string,
  `.identifier` = scenario identifier for that pair

Plus two more parallel lists, same `.value`, `.identifier` = the plain
raw environment/scenario key (not slug, not remote identifier) — feeding
two new resolver functions purely so `run-summary.json`'s
`environment`/`scenario` fields keep showing the real keys, unchanged
from today, even though only one combined value crosses the CLI boundary.

`ManualPipelineSpec.inputs` goes from two `PipelineInput`s
(`"environment"`, `"scenario"`) to one: `PipelineInput("test_case", "Test
case", "dropdown", options)`.

`AutomatedJobSpec` is unchanged (`environment_ref`/`scenario_ref` stay as
plain strings) — renderers format the same combined-value string from
those two fields directly at render time; no new field needed.

## D. Generated script (`scripts.py`)

Six resolver functions instead of four, **all keyed by the same combined
test-case value**, generated via the existing generic
`_render_resolver_function` helper (exact-match `if [ "$1" = ... ]`
chains — deliberately not a `case` statement, same reasoning as today:
`case` patterns are shell globs and a hostile catalog key could otherwise
glob-match a pair it wasn't meant to):

- `resolve_environment_identifier` / `resolve_scenario_identifier`
  (existing two, re-keyed)
- `resolve_environment_slug` / `resolve_scenario_slug` (existing two,
  re-keyed)
- `resolve_environment_key` / `resolve_scenario_key` (new — recover the
  plain raw keys for `run-summary.json`)

CLI changes from `--environment <key> --scenario <key>` to `--test-case
"<environment key>: <scenario key>"`. Usage message, arg-parsing block,
and all three tool-specific script bodies (`_render_jmeter_script`,
`_render_loadrunner_script`, `_render_blazemeter_script`) update to
resolve everything from the one parsed value. Results folder naming
(`run-output/<environment_slug>_<scenario_slug>/`) is unchanged — both
slugs are still resolved separately, just from the one input.

Automated jobs' baked command uses the same `--test-case` flag with a
literal value (`shell_quote(f"{job.environment_ref}: {job.scenario_ref}")`)
— one script CLI interface for both trigger paths, not two.

## E. Renderers

All three (`github_actions.py`, `azure_devops.py`, `jenkins.py`)
currently hardcode `inputs[0]`/`inputs[1]` to build two separate
dropdown/parameter/choice blocks. Each becomes a single block built from
`inputs[0]` only:

- **GitHub Actions**: one `workflow_dispatch.inputs.test_case` (`type:
  choice`, `options:` = every valid pair string).
- **Azure DevOps**: one `parameters` entry (`type: string`, `values:` =
  every valid pair string).
- **Jenkins**: one `choice(name: 'TEST_CASE', choices: [...])`.

The shell/script invocation line changes from `--environment
"$ENVIRONMENT" --scenario "$SCENARIO"` to `--test-case "$TEST_CASE"` (or
platform equivalent variable name), sourced from the platform's single
trigger input.

## F. Validation (`validator.py`)

- `catalog.environments[].scenarios` validated as a nested list of dicts
  per environment (reusing `_as_list_of_dicts`).
- Duplicate-key check for scenarios becomes **per-environment** (the
  same scenario key repeated *within one environment* is the problem;
  reuse *across* environments is the whole point now).
- New warning: an environment with zero scenarios — it can never appear
  in the manual pipeline's pair list, which wasn't a distinct concept
  before nesting existed.
- "No scenarios defined" warning now means zero scenarios across *all*
  environments combined.
- Automated job validation: `scenario_ref` must exist within
  `environment_ref`'s specific scenario list, not a global one.
- "Manual pipeline enabled but environments/scenarios missing" becomes
  "enabled but there are zero valid environment/scenario pairs."

## Known limitation

The combined value is `f"{environment_key}: {scenario_key}"`. Two
different pairs could theoretically produce the same combined string if
a key itself contains `": "` in exactly the right place (e.g. env `"a:
b"` + scenario `"c"` vs. env `"a"` + scenario `"b: c"`). This requires a
deliberately crafted colliding key and produces a wrong-test-runs
outcome, not a security issue beyond what an adversarial catalog already
implies elsewhere in this codebase. Accepted as a known edge case for
this pass, not solved.

## Migration

All 9 example configs get rewritten to the nested shape. 7 of 9 are
single-environment / single-scenario today — trivial nesting, no rename
needed. `github-loadrunner` and `jenkins-loadrunner` are the two with the
2×2 matrix using the `_qa`/`_staging` suffix convention; both get
consolidated to two shared scenario keys (`checkout_smoke`,
`browse_baseline`) nested under `qa` and `staging` respectively, each
with its own identifier — this is the exact case the redesign exists for.
Their `automated_jobs[].scenario_ref` (currently `checkout_smoke_qa`)
updates to the consolidated key (`checkout_smoke`) to match.

## Testing

- `validator.py`: nested structural validation, per-environment duplicate
  detection, scoped automated-job reference validation.
- Wizard: nested environment→scenario collection, resume behavior,
  automated-job scenario choices filtered to the picked environment.
- `context.py`: combined-pair `InputOption` construction (identifiers,
  slugs, raw keys — three parallel pairs of lists).
- Renderers: single combined dropdown/parameter/choice block per
  platform; automated job's baked `--test-case` value.
- `scripts.py`: extend the existing stub-based end-to-end tests
  (fake `docker`/`wlrun`/`curl` on `PATH`) to invoke via `--test-case`;
  unknown test-case value still errors cleanly; `run-summary.json` still
  has separate, correct `environment`/`scenario` fields.
- All 9 example configs re-validated and regenerated via
  `test_example_configs.py`.
