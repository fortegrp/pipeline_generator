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
- Provides a runtime wrapper skeleton for:
  - BlazeMeter
  - LoadRunner Professional

## Status

This is a scaffolded v1 foundation:

- Wizard, validation, and generation are working
- Runtime command flow and adapter interfaces are implemented
- Actual remote execution for BlazeMeter and LoadRunner Professional is still a TODO

## Install

From this folder:

```bash
cd /Users/alinamolot/Documents/Project/pipeline_generator
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

If your environment has an older `pip`, this fallback can help:

```bash
pip install --no-build-isolation -e .
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

Preview a runtime invocation without contacting tools:

```bash
pipeline-generator run \
  --config setups/acme-gha-loadrunner.yaml \
  --mode manual \
  --environment qa \
  --scenario checkout_smoke \
  --dry-run
```

Preview an automated job invocation:

```bash
pipeline-generator run \
  --config setups/acme-gha-loadrunner.yaml \
  --mode automated \
  --job post-deploy-smoke \
  --dry-run
```

## CLI Commands

- `pipeline-generator wizard`
- `pipeline-generator validate`
- `pipeline-generator generate`
- `pipeline-generator run`

## Output Structure

When you generate assets, the tool creates a setup-specific folder:

```text
generated/
  acme-gha-loadrunner-storefront/
    customer.yaml
    README.md
    .github/workflows/performance-manual.yml
    .github/workflows/performance-automated.yml
```

Azure DevOps setups will render Azure YAML files instead.

## Config Shape

Example:

```yaml
version: 1
incomplete: false
setup:
  id: acme-github-actions-loadrunner-professional-storefront
  working_location: central_repo
  final_pipeline_destination: customer_repo
  ci_can_use_central_repo_directly: false
  target_repository: github.com/acme/storefront
  generation_mode: both
cicd:
  type: github_actions
tool:
  type: loadrunner_professional
  auth:
    type: username_password
  connection:
    controller_host: lr-controller.acme.local
    controller_results_path: C:\\Results
catalog:
  environments:
    - key: qa
      name: QA
      identifier: env-qa
  scenarios:
    - key: checkout_smoke
      name: Checkout Smoke
      identifier: LR_CHECKOUT_SMOKE
manual_pipeline:
  enabled: true
  name: Performance Manual Run
  timeout_minutes: 240
automated_jobs:
  - name: post-deploy-smoke
    enabled: true
    environment_ref: qa
    scenario_ref: checkout_smoke
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

## Recommended Next Work

- Implement real BlazeMeter API adapter methods
- Implement remote Windows execution for LoadRunner Professional
- Add GitLab CI and Jenkins renderers
- Add non-interactive `generate` workflows around completed YAML inputs
