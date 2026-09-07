# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo context

This directory (`pipelineGenerator`) is one of three sibling projects inside a
larger git repo rooted one level up (`HARconverter`, `Visualisation`,
`pipelineGenerator`). Treat this project's scope as everything under this
directory; the sibling projects are unrelated tools with their own CLAUDE.md
files (`../Visualisation/CLAUDE.md`).

## Commands

Install (editable, from this directory):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

There is no dev-dependency group in `pyproject.toml` — `pytest` must be
installed manually into the venv (`pip install pytest`) before running tests.

Run all tests:

```bash
pytest
```

Run a single test file or test:

```bash
pytest tests/test_validation.py
pytest tests/test_validation.py::test_validation_warns_for_incomplete_base_config
```

There is no lint/format tooling configured in this project.

Exercise the CLI directly (the four subcommands are `wizard`, `validate`, `generate`, `run`):

```bash
pipeline-generator wizard --output setups/acme.yaml
pipeline-generator validate --config setups/acme.yaml [--strict]
pipeline-generator generate --config setups/acme.yaml --output-dir generated
pipeline-generator run --config setups/acme.yaml --mode manual --environment qa --scenario checkout_smoke --dry-run
pipeline-generator run --config setups/acme.yaml --mode automated --job post-deploy-smoke --dry-run
```

`examples/{github,azure}-{blazemeter,loadrunner}/customer.yaml` are ready-made
configs covering the supported CI/CD × tool matrix — use them for manual
testing instead of writing new configs from scratch.

## Architecture

The tool's job: take one customer YAML config and turn it into a generated,
setup-specific folder containing CI/CD pipeline files a customer can drop into
their repo, plus a wrapper CLI (`pipeline-generator run`) those pipelines
invoke to actually trigger a performance test.

Pipeline: **customer YAML → validate → generic pipeline model → CI/CD renderer → generated setup package**.

- `config/` — the config's source-of-truth shape (`schema.py`: supported
  enums and `base_config()`), YAML load/save/merge with defaults
  (`loader.py`), TODO-placeholder handling (`placeholders.py`), and
  `validator.py`, which separates **errors** (always block) from **warnings**
  (only block `generate`/`run` when `config["incomplete"]` is `False` — see
  `is_placeholder` checks in `validator.py`). This error/warning split is the
  key mechanism that lets a config be a legitimate in-progress draft (via
  `incomplete: true`) while still being loadable and partially useful.
- `wizard/` — interactive flow (`flow.py`) that builds/resumes a draft YAML
  using `merged_base_config`, so re-running the wizard against an existing
  file only fills in what's missing. `id_builder.py` slugifies
  `cicd_type + tool_type + repo_name` into the setup ID used as the generated
  folder name.
- `generator/` — `context.py` reads validated config and builds a
  `GenericPipelinePackage` (`generic_model.py`): a CI/CD-agnostic
  representation of the manual pipeline (inputs, timeout, run command) and
  automated jobs. This indirection is what lets `renderers/` stay ignorant of
  the customer YAML shape — renderers only ever see the generic model.
- `renderers/` — turn the generic model into platform-specific files:
  `github_actions.py` (writes `.github/workflows/`), `azure_devops.py` (writes
  `azure/`), `jenkins.py` (writes declarative `Jenkinsfile.*` files under
  `jenkins/`), `readme.py` (generated setup README). Adding a new CI/CD
  platform means: adding its value to `SUPPORTED_CICD` in `config/schema.py`,
  adding a renderer here, and adding a branch in
  `generator/service.py:generate_assets` — the generic model itself doesn't
  need to change since renderers only consume `GenericPipelinePackage`.
- `runtime/` — what the *generated* pipelines actually call
  (`pipeline-generator run`). `orchestrator.py:run_execution` builds a run
  request from the config (manual needs `--environment`/`--scenario`,
  automated needs `--job` and looks up `environment_ref`/`scenario_ref` from
  `automated_jobs`), then either writes a dry-run `execution-plan.json` or
  drives a tool adapter through `run_prechecks → start_run →
  wait_for_completion → collect_artifacts` and writes `summary.json`.
- `adapters/` — `base.py` defines the `ToolAdapter` protocol and
  `get_adapter(tool_type)` factory. `blazemeter.py` and
  `loadrunner_professional.py` are stubs: prechecks are stubbed as "planned",
  and `start_run`/`wait_for_completion`/`collect_artifacts` all raise
  `NotImplementedError`. Real remote execution against either tool is not yet
  implemented — only `--dry-run` currently produces real output for `run`.

`generate` and `run` both re-validate the config before doing anything
(`cli.py` calls `validate_config` in every branch), and `generate` only stops
on `result.errors`, not `result.warnings` — a config with warnings (e.g.
missing catalog entries) can still generate files.

See `docs/current-state-and-readiness-plan.md` for the full known-gaps list
and multi-milestone readiness plan (stricter validation profiles, YAML-safe
renderer output, real adapter implementations) if working on hardening this
project further.
