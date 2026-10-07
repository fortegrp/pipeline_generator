# Pipeline Generator

A Python scaffold for onboarding customer-specific performance testing setups and generating CI/CD pipeline assets from one YAML configuration.

## What This Project Does

- Guides an engineer through onboarding with an interactive wizard
- Saves a draft-friendly YAML config with TODO placeholders
- Generates:
  - a manual top-level pipeline for performance engineers
  - an automated reusable job/template for DevOps
- Supports a generic internal pipeline model with renderers for:
  - GitHub Actions
  - Azure DevOps
  - Jenkins
- Writes a `scripts/run-<tool>.sh` alongside each generated setup, which is
  what the generated pipeline's "Run performance wrapper" step calls
  directly:
  - JMeter — a real, working script that runs JMeter inside a Docker
    container (`docker run ... -n -t ...`) against the configured test plan;
    the whole working directory is bind-mounted in, so fragments/CSV data
    sets referenced by relative path still resolve.
  - LoadRunner Professional — a real, working script that runs `wlrun -Run
    -TestPath ...` locally, assuming the CI job runs on an agent co-located
    with the LoadRunner Controller.
  - BlazeMeter — a real, working script that authenticates via API key,
    starts a test through BlazeMeter's REST API, polls until it finishes
    (bounded by a `--timeout-minutes` flag), and downloads a summary
    report.

`pipeline-generator` itself never executes a performance test or contacts
any of these tools — its job ends at generating files. The generated script
is what actually runs, and it runs entirely independently of this tool
(no Python, no `pipeline-generator` on `PATH`, at execution time).

## Status

`1.0.0rc3` — first internal release candidate, actively used and tested,
not yet verified against a live BlazeMeter account:

- Wizard, validation, and generation are all working, with dedicated tests
  for valid and invalid configs and for CLI success/failure paths
- `generate` writes a real, working `scripts/run-jmeter.sh` for JMeter
  setups, `scripts/run-loadrunner_professional.sh` for LoadRunner
  Professional setups (assumes the CI job runs on an agent co-located with
  the LoadRunner Controller), and `scripts/run-blazemeter.sh` for
  BlazeMeter setups (calls BlazeMeter's REST API directly) — all three
  write a normalized `run-summary.json` after attempting a run
- Config validation catches malformed sections, unrecognized
  `pre_run_checks` values, duplicate catalog keys, and no-op setups with
  clean errors/warnings rather than crashing
- See `CHANGELOG.md` for the full version history and
  `docs/current-state-and-readiness-plan.md` for what's resolved vs. still
  open

## Install

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

If your environment has an older `pip`, this fallback can help:

```bash
pip install --no-build-isolation -e .
```

For development, install the `dev` extra to get `pytest`, then run the test suite:

```bash
pip install -e ".[dev]"
pytest
```

## Quick Start

Create a new draft config interactively:

```bash
pipeline-generator wizard --output setups/acme-gha-loadrunner.yaml
```

Validate a config:

```bash
pipeline-generator validate --config setups/acme-gha-loadrunner.yaml
```

Generate pipeline files and setup docs:

```bash
pipeline-generator generate --config setups/acme-gha-loadrunner.yaml --output-dir generated
```

This is the last step — the generated `scripts/run-<tool>.sh` alongside the
CI/CD files is what actually runs a performance test, and it's the generated
pipeline (not `pipeline-generator`) that calls it.

## CLI Commands

### `wizard`

Create or resume a draft setup YAML interactively.

```bash
pipeline-generator wizard --output setups/acme.yaml [--resume]
```

- `--output` (required): path to the YAML file to create or update.
- `--resume`: required to touch a file that already exists. Running the
  wizard against an existing `--output` path without `--resume` refuses up
  front and leaves the file untouched, instead of overwriting it — pass
  `--resume` to continue editing that draft, or point `--output` at a new
  path to start a fresh one.

See [Interactive Wizard](#interactive-wizard) below for what the flow itself
looks like.

### `validate`

Check a config against the schema without generating anything.

```bash
pipeline-generator validate --config setups/acme.yaml [--strict]
```

- `--strict`: treat warnings as errors (exit non-zero on any warning),
  regardless of the config's `incomplete` flag. Useful for a CI gate that
  wants zero tolerance even for drafts.

### `generate`

Generate CI/CD pipeline files and a setup README from a config.

```bash
pipeline-generator generate --config setups/acme.yaml --output-dir generated
```

- `--output-dir` (default `generated`): directory where the setup-specific
  output folder is created.

Validation errors always block generation. Validation *warnings* block
generation only when the config says `incomplete: false` — see
[Draft vs. Complete Setups](#draft-vs-complete-setups-the-incomplete-flag).

Generation is the tool's last step: it never triggers or contacts a
performance test itself. Alongside the CI/CD files and `customer.yaml`,
`generate` writes `scripts/run-<tool_type>.sh` — a real, executable script
that the generated pipeline's "Run performance wrapper" step calls directly
(e.g. `./scripts/run-jmeter.sh --test-case "$TEST_CASE"`, where the test
case is one `<environment>: <scenario>` pair from the catalog). For JMeter
this script actually resolves that pair to its catalog identifiers and runs JMeter inside a Docker
container (`docker run --rm -v "$(pwd):/workspace" -w /workspace
<docker_image> -n -t ...`) — the agent/runner needs Docker installed and
available, but not a local JMeter install.
LoadRunner Professional is also real: it assumes the CI job runs on a
dedicated agent co-located with the LoadRunner Controller, resolves
`--test-case` the same way, and runs `wlrun -Run -TestPath
<scenario_identifier> -ResultName run-output/<environment_slug>_
<scenario_slug>` — a scenario's catalog identifier is a full `.lrs` file
path rather than a remote name, since `wlrun` has no native "environment"
switch (see the user guide for the full catalog convention). BlazeMeter is
also real: it authenticates via API key, starts a test through
BlazeMeter's REST API (`POST /api/v4/tests/<id>/start`), polls until it
finishes (bounded by a `--timeout-minutes` flag added only to BlazeMeter's
invocation), and downloads a summary report — see the user guide for the
full precheck vocabulary and the API endpoints' verification status. All
three tools also write a
`run-output/<environment_slug>_<scenario_slug>/run-summary.json` after
attempting a run, with a normalized schema (tool, status, timestamps,
duration, report link) shared across JMeter, LoadRunner Professional, and
BlazeMeter.

## Interactive Wizard

`pipeline-generator wizard` walks through the config in eight numbered
sections (what to generate, CI/CD + tool selection, tool connection
details, test parameters, manual pipeline, environments/scenarios,
automated jobs, pre-run checks), saving progress to `--output` after each
section. A few things
about how it behaves:

- **Test parameters.** A short test type label (e.g. `load`, `soak` — passed to
  your test script and recorded in `run-summary.json`, never changes
  behavior) for every tool; for JMeter and BlazeMeter also users, ramp-up
  (seconds), duration (minutes) and throughput (requests/second, `0` = no
  cap). Type `TODO` for anything you don't know yet. LoadRunner takes all
  of these from the `.lrs` scenario, so it's only asked the label.
- **Inline hints.** Choices with non-obvious implications (`generation_mode`)
  show a one-line explanation of what each option means.
- **Each environment owns its scenarios.** After entering environments,
  the wizard asks for each one's scenarios, so the manual pipeline offers
  a single dropdown of the `<environment>: <scenario>` pairs you actually
  defined — a QA-only scenario can't be run against staging by mistake.
  Keys must be simple names (letters, digits, `_`, `.`, `-`); an invalid
  key is re-asked. An automated job's scenario choice is limited to its
  chosen environment's scenarios.
- **Resuming never discards existing entries.** If you `--resume` a draft
  that already has environments, scenarios, or automated jobs, the wizard
  shows what's already there and asks whether to keep it as-is, add more on
  top of it, or start over — it never silently wipes an existing list just
  because you said "yes, let's edit this."
- **Pre-run checks are a single screen.** Instead of four separate yes/no
  prompts, you get one list and type comma-separated numbers, `all`,
  `none`, or press Enter to keep whatever was already enabled.
- **Cancelling is safe.** Ctrl-C or closing stdin exits cleanly with a
  message noting whether any progress was saved, instead of a stack trace.
- **It ends with a recap.** After the last section, the wizard prints a
  plain-language summary of what was configured and immediately runs the
  same validation `pipeline-generator validate` would, so you see any
  problems before leaving the terminal.

## Draft vs. Complete Setups (the `incomplete` flag)

Every config has a top-level `incomplete: true|false` flag — the wizard sets
it to `true` while any value is still `TODO`, and it can also be set by hand. A draft still generates a full
package: the generated script then refuses to run while a value it needs
is `TODO`, printing the exact `customer.yaml` field to fill (e.g.
`ERROR: load_profile.users is not set (still TODO)`).

- **`incomplete: true` (a draft):** `generate` only ever blocks on hard
  **errors** (an unsupported `cicd.type` or `tool.type`).
  Warnings — missing catalog entries, an automated job pointing at an
  environment/scenario that doesn't exist yet, missing connection details —
  are reported but never block anything. This is what lets onboarding start
  before every detail is known.
- **`incomplete: false` (declared ready):** the same warnings now block
  `generate` too, with a message telling you to either fix them or flip the
  flag back to `true`. The idea is that marking a setup complete is a
  promise the tool actually checks, instead of a label that has no effect.

`validate` itself never blocks on warnings unless you pass `--strict`,
regardless of `incomplete` — it's meant to be a cheap way to inspect a
config's state at any point without that promise being enforced.

## Output Structure

When you generate assets, the tool creates a setup-specific folder:

```text
generated/
  acme-gha-loadrunner-storefront/
    customer.yaml
    README.md
    scripts/run-loadrunner_professional.sh
    .github/workflows/performance-manual.yml
    .github/workflows/performance-automated-<job-name>.yml
```

Azure DevOps setups render Azure Pipelines YAML under `azure/` instead, and
Jenkins setups render declarative `Jenkinsfile.*` files under `jenkins/`
instead — one file for the manual pipeline and one per enabled automated
job, in each case.

The `scripts/run-<tool_type>.sh` file is always present alongside those
CI/CD files, regardless of platform, since every generated pipeline calls it
the same way (`./scripts/run-<tool_type>.sh --test-case "$TEST_CASE"`,
plus the load-profile flags for manual runs).

## Config Shape

Example:

```yaml
incomplete: false
setup:
  id: acme-github-actions-loadrunner-professional-storefront
  generation_mode: both
cicd:
  type: github_actions
  runner: self-hosted, windows, loadrunner   # runs-on labels; blank = ubuntu-latest
tool:
  type: loadrunner_professional
  connection:
    wlrun_path: wlrun
catalog:
  environments:
    - key: qa
      identifier: QA
      scenarios:              # each environment owns its scenarios
        - key: checkout_smoke
          identifier: C:\Scenarios\checkout_smoke_qa.lrs
    - key: staging
      identifier: Staging
      scenarios:              # same key, this environment's own .lrs
        - key: checkout_smoke
          identifier: C:\Scenarios\checkout_smoke_staging.lrs
manual_pipeline:
  enabled: true
  name: Performance Manual Run
  timeout_minutes: 240
automated_jobs:
  - name: post-deploy-smoke
    enabled: true
    environment_ref: qa
    scenario_ref: checkout_smoke   # must exist under environment qa
    timeout_minutes: 90
pre_run_checks:
  - verify_controller_access
  - verify_scenario_exists
load_profile:
  test_type: load   # LoadRunner: only the label; load shape comes from the .lrs
```

For JMeter and BlazeMeter, `load_profile` also carries the load shape:

```yaml
load_profile:
  test_type: load
  users: 20
  ramp_up_seconds: 60
  duration_minutes: 10
  throughput_rps: 0   # 0 = no cap
```

These are baked into the generated script as defaults, exposed as
pre-filled trigger inputs on the manual pipeline (so one run can use more
users without regenerating), and used as-is by automated jobs. JMeter
receives them as `-J` properties your `.jmx` reads via `${__P(...)}` (the
generated README lists the exact names); BlazeMeter applies them to the
test via its API before starting it.

`cicd.type` supports `github_actions`, `azure_devops`, and `jenkins`.
`tool.type` supports `loadrunner_professional`, `blazemeter`, and `jmeter`.
JMeter runs inside a Docker container rather than as a local install, so
its `tool.connection` needs a `test_plan_path` and optionally a
`docker_image` (blank uses `justb4/jmeter:5.6.3`) — the agent/runner needs
Docker installed. Ready-made examples for every CI/CD × tool combination
are under [`examples/`](examples/).

## Recommended Next Work

- Verify BlazeMeter's exact status-string vocabulary and report endpoint
  against a live account (flagged as best-understanding in
  `renderers/scripts.py` and the generated setup README)
- Add a GitLab CI renderer
- Add non-interactive `generate` workflows around completed YAML inputs
