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

One flat list of valid pairs replaces the two independent option lists:

```python
def run_target_selector(environment_key: str, scenario_key: str) -> str:
    return f"{environment_key}: {scenario_key}"


@dataclass
class RunTarget:
    environment_key: str
    environment_identifier: str
    scenario_key: str
    scenario_identifier: str

    @property
    def selector(self) -> str:
        return run_target_selector(self.environment_key, self.scenario_key)
```

(Neither name starts with `Test`/`test_`: pytest would try to collect
an imported `Test*` class or `test_*` function.)

- `GenericPipelinePackage.environments`/`.scenarios` (two
  `list[InputOption]`) are replaced by `run_targets: list[RunTarget]`,
  built by one walk over `catalog.environments[].scenarios[]` in
  `context.py`.
- `ManualPipelineSpec.inputs` is removed. Every renderer already
  hardcoded `inputs[0]`/`inputs[1]` rather than iterating, so the
  `PipelineInput` indirection was never used generically; renderers now
  read `[t.selector for t in package.run_targets]` directly.
  `InputOption` and `PipelineInput` are deleted — nothing else uses them.
- `AutomatedJobSpec.environment_ref`/`scenario_ref` are replaced by one
  `test_case: str`, formatted once in `context.py`. Renderers bake it
  as-is and never format a selector themselves.

`run_target_selector()` is the only place the `"<env>: <scenario>"`
format exists; `context.py` uses it for automated jobs too.

## D. Generated script (`scripts.py`)

The four `resolve_*` functions are replaced by one,
`resolve_test_case`, which sets every per-run variable in a single
exact-match branch per pair:

```bash
resolve_test_case() {
  if [ "$1" = 'qa: checkout_smoke' ]; then environment_key='qa'; scenario_key='checkout_smoke'; environment_identifier='QA'; scenario_identifier='C:\Scenarios\checkout_smoke_qa.lrs'; environment_slug='qa'; scenario_slug='checkout_smoke'; return; fi
  echo "Unknown test case: $1" >&2
  exit 1
}
```

- Still exact-match `if [ "$1" = ... ]`, never `case` (glob safety).
  Every value goes through `shell_quote`.
- Slugs are computed at generation time with `safe_filename_component`,
  as today.
- `main` declares the six variables `local` and calls
  `resolve_test_case "$test_case"` directly (not in `$(...)`); bash's
  dynamic scoping assigns `main`'s locals. The per-tool
  `resolve_*_slug` calls in the three tool bodies are deleted.
- CLI: `--test-case "<environment key>: <scenario key>"` replaces
  `--environment`/`--scenario`, for manual and automated triggers alike.
- `_render_resolvers`, `_render_slug_resolvers` and
  `_render_resolver_function` are deleted.
- `run-summary.json` still reports `environment`/`scenario` from
  `$environment_key`/`$scenario_key` — schema unchanged.

## E. Renderers

All three build one trigger input from `package.run_targets`:

- **GitHub Actions**: one `workflow_dispatch.inputs.test_case` (`type:
  choice`), delivered via `env: TEST_CASE`.
- **Azure DevOps**: one `testCase` parameter (`type: string`, `values:`),
  delivered via `env: TEST_CASE`.
- **Jenkins**: one `choice(name: 'TEST_CASE', ...)`; automated jobs set
  `TEST_CASE` in `environment {}`.

The script call becomes `--test-case "$TEST_CASE"` everywhere. Automated
GitHub/Azure jobs bake `--test-case {shell_quote(job.test_case)}`.

`readme.py`'s manual-usage and troubleshooting lines that mention
`--environment`/`--scenario`, "environment/scenario parameters" and
`Unknown environment key` are updated to the single test-case input.

## F. Validation (`validator.py`)

- **Key format (new error):** every non-placeholder environment and
  scenario `key` must match `CATALOG_KEY_PATTERN =
  r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"` (in `schema.py`). Keys are short
  names, not free text. This guarantees the selector can't collide (no
  `:` in keys), keeps the dropdown readable, and makes results folder
  names predictable. `shell_quote`/`safe_filename_component` stay as
  a second line of defense.
- `catalog.environments[].scenarios` is validated as a nested list of
  dicts per environment (reusing `_as_list_of_dicts`).
- Duplicate scenario keys are checked **per environment**; reuse across
  environments is the point.
- New warning: an environment with zero scenarios (it never appears in
  the dropdown).
- "No scenarios" warning means zero across all environments.
- Automated job: `scenario_ref` must exist under its `environment_ref`.
- "Manual pipeline enabled but environments/scenarios missing" becomes
  "enabled but there are no environment/scenario pairs."

The wizard enforces the same pattern at the key prompt (re-asks on an
invalid key), so a wizard-built config never hits the error.

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
  detection, scoped automated-job reference validation, key-format error.
- Wizard: nested environment→scenario collection, resume behavior,
  automated-job scenario choices filtered to the picked environment.
- `context.py`: one `RunTarget` per pair, in catalog order; automated
  job `test_case` formatted from its refs.
- Renderers: single combined dropdown/parameter/choice block per
  platform; automated job's baked `--test-case` value.
- `scripts.py`: extend the existing stub-based end-to-end tests
  (fake `docker`/`wlrun`/`curl` on `PATH`) to invoke via `--test-case`;
  unknown test-case value still errors cleanly; `run-summary.json` still
  has separate, correct `environment`/`scenario` fields.
- All 9 example configs re-validated and regenerated via
  `test_example_configs.py`.
