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
  - JMeter — a real, working script that runs `jmeter -n -t ...` against the
    configured test plan.
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

This is a scaffolded v1 foundation:

- Wizard, validation, and generation are working
- `generate` writes a real, working `scripts/run-jmeter.sh` for JMeter
  setups, `scripts/run-loadrunner_professional.sh` for LoadRunner
  Professional setups (assumes the CI job runs on an agent co-located with
  the LoadRunner Controller), and `scripts/run-blazemeter.sh` for
  BlazeMeter setups (calls BlazeMeter's REST API directly)

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
(e.g. `./scripts/run-jmeter.sh --environment "$ENVIRONMENT" --scenario
"$SCENARIO"`). For JMeter this script actually resolves the environment/
scenario to their catalog identifiers and runs `jmeter -n -t ...` for real.
LoadRunner Professional is also real: it assumes the CI job runs on a
dedicated agent co-located with the LoadRunner Controller, resolves
`--environment`/`--scenario` the same way, and runs `wlrun -Run -TestPath
<scenario_identifier> -ResultName run-output/<environment_slug>_
<scenario_slug>` — a scenario's catalog identifier is a full `.lrs` file
path rather than a remote name, since `wlrun` has no native "environment"
switch (see the user guide for the full catalog convention). BlazeMeter is
also real: it authenticates via API key, starts a test through
BlazeMeter's REST API (`POST /api/v4/tests/<id>/start`), polls until it
finishes (bounded by a `--timeout-minutes` flag added only to BlazeMeter's
invocation), and downloads a summary report — see the user guide for the
full precheck vocabulary and the API endpoints' verification status.

## Interactive Wizard

`pipeline-generator wizard` walks through the config in eight numbered
sections (setup basics, CI/CD + tool selection, setup ID, tool connection
details, manual pipeline, environments/scenarios, automated jobs, pre-run
checks), saving progress to `--output` after each section. A few things
about how it behaves:

- **Inline hints.** Choices with non-obvious implications (`working_location`,
  `final_pipeline_destination`, `generation_mode`, and whether the CI/CD
  system can use the central repo directly) show a one-line explanation of
  what each option means.
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
it automatically based on whether required fields are still filled with
`TODO`, and it can also be set by hand.

- **`incomplete: true` (a draft):** `generate` only ever blocks on hard
  **errors** (an unsupported `cicd.type`, `tool.type`, or `auth.type`).
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
the same way (`./scripts/run-<tool_type>.sh --environment "$ENVIRONMENT"
--scenario "$SCENARIO"`).

## Config Shape

Example:

```yaml
version: 1
incomplete: false
setup:
  id: acme-github-actions-loadrunner-professional-storefront
  working_location: central_repo
  final_pipeline_destination: copy_to_customer_repo
  ci_can_use_central_repo_directly: false
  target_repository: github.com/acme/storefront
  generation_mode: both
cicd:
  type: github_actions
tool:
  type: loadrunner_professional
  auth:
    type: none
  connection:
    wlrun_path: wlrun
catalog:
  environments:
    - key: qa
      name: QA
      identifier: QA
  scenarios:
    - key: checkout_smoke_qa
      name: Checkout Smoke (QA)
      identifier: C:\Scenarios\checkout_smoke_qa.lrs
manual_pipeline:
  enabled: true
  name: Performance Manual Run
  timeout_minutes: 240
automated_jobs:
  - name: post-deploy-smoke
    enabled: true
    environment_ref: qa
    scenario_ref: checkout_smoke_qa
    timeout_minutes: 90
pre_run_checks:
  - verify_controller_access
  - verify_scenario_exists
  - verify_load_generators_connected
  - collect_results
artifacts:
  download_remote_results: true
  fail_on_partial_download: false
```

`cicd.type` supports `github_actions`, `azure_devops`, and `jenkins`.
`tool.type` supports `loadrunner_professional`, `blazemeter`, and `jmeter`.
JMeter is local/self-hosted rather than a remote SaaS tool, so its
`tool.auth.type` is typically `none`, and its `tool.connection` only needs a
`test_plan_path` (and optionally `jmeter_bin` if the executable isn't on
`PATH`). Ready-made examples for every CI/CD × tool combination are under
[`examples/`](examples/).

## Recommended Next Work

- Add configurable CI/CD runner/agent targeting for LoadRunner Professional
  setups (generated pipelines default to hosted runners that can't reach a
  LoadRunner Controller; today this requires a manual hand-edit after
  generation — see the user guide's section 10 caveat)
- Verify BlazeMeter's exact status-string vocabulary and report endpoint
  against a live account (flagged as best-understanding in
  `renderers/scripts.py` and the generated setup README)
- Add a GitLab CI renderer
- Add non-interactive `generate` workflows around completed YAML inputs
