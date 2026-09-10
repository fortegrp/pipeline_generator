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

Install the `dev` extra to get `pytest`:

```bash
pip install -e ".[dev]"
```

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

Exercise the CLI directly (the three subcommands are `wizard`, `validate`, `generate`):

```bash
pipeline-generator wizard --output setups/acme.yaml
pipeline-generator validate --config setups/acme.yaml [--strict]
pipeline-generator generate --config setups/acme.yaml --output-dir generated
```

`examples/{github,azure,jenkins}-{blazemeter,loadrunner,jmeter}/customer.yaml` are
ready-made configs covering the supported CI/CD × tool matrix — use them for
manual testing instead of writing new configs from scratch.

## Architecture

The tool's job: take one customer YAML config and turn it into a generated,
setup-specific folder containing CI/CD pipeline files a customer can drop into
their repo, plus a `scripts/run-<tool_type>.sh` those pipelines invoke
directly to actually trigger a performance test. `pipeline-generator` itself
never executes anything — its job ends at `generate`; the generated script
runs standalone, with no Python or `pipeline-generator` involved at
execution time.

Pipeline: **customer YAML → validate → generic pipeline model → CI/CD renderer → generated setup package**.

- `config/` — the config's source-of-truth shape (`schema.py`: supported
  enums and `base_config()`), YAML load/save/merge with defaults
  (`loader.py`), TODO-placeholder handling (`placeholders.py`), and
  `validator.py`, which separates **errors** (always reported) from
  **warnings**. `validate_config()` never blocks anything on its own — the
  CLI decides what to do with the result: `cli.py`'s
  `_blocks_action()` always blocks on errors, and additionally blocks on
  warnings unless `config["incomplete"]` is `True`. This is the mechanism
  that lets a config be a legitimate in-progress draft (`incomplete: true`)
  while still being loadable and partially useful, while a config that
  declares itself `incomplete: false` has that claim actually enforced by
  `generate` (the only action left that calls it — `_blocks_action` still
  takes an `action` label for its message, but `generate` is the only
  caller now). `validate_config()` also defends against a structurally
  malformed config (a blank YAML key parsing to `null`, a list of plain
  strings where a list of mappings was expected) via `_as_dict`/
  `_as_list_of_dicts` coercion helpers used everywhere a section is read —
  every mismatch becomes a clean error instead of an uncaught
  `AttributeError`, and validation still continues past the malformed
  section to report other real problems in the same pass. Beyond
  structural shape, it also warns on a `pre_run_checks` value outside the
  `PRE_RUN_CHECKS` enum (a likely typo, otherwise silently dropped at
  generation time with no trace), a duplicate `key` within
  `catalog.environments`/`catalog.scenarios` (the second entry's
  identifier becomes silently unreachable in the generated resolver
  function), and a setup with neither the manual pipeline nor any
  automated job enabled (generates zero CI/CD pipeline files).
- `wizard/` — interactive flow (`flow.py`) that builds/resumes a draft YAML
  using `merged_base_config`, so re-running the wizard against an existing
  file only fills in what's missing. `cli.py` refuses to touch an existing
  `--output` file unless `--resume` is passed (no silent overwrite), and
  resuming a draft with existing environments/scenarios/automated jobs offers
  keep-as-is/add-more/start-over rather than discarding the list.
  `id_builder.py` slugifies `cicd_type + tool_type + repo_name` into the
  setup ID used as the generated folder name.
- `generator/` — `context.py` reads validated config and builds a
  `GenericPipelinePackage` (`generic_model.py`): a CI/CD-agnostic
  representation of the manual pipeline (inputs, timeout, run command) and
  automated jobs. This indirection is what lets `renderers/` stay ignorant of
  the customer YAML shape — renderers only ever see the generic model.
  `service.py:generate_assets` slugifies `setup.id` before using it as the
  output directory name — `setup.id` comes from the config file, which this
  tool's own `customer_repo` model expects a less-trusted collaborator to be
  able to edit, so an unsanitized `../../etc` or absolute-path value would
  otherwise write outside `--output-dir` entirely (pathlib's `/` discards
  everything before an absolute right-hand operand).
- `renderers/` — turn the generic model into platform-specific files:
  `github_actions.py` (writes `.github/workflows/`), `azure_devops.py` (writes
  `azure/`), `jenkins.py` (writes declarative `Jenkinsfile.*` files under
  `jenkins/`), `readme.py` (generated setup README). Adding a new CI/CD
  platform means: adding its value to `SUPPORTED_CICD` in `config/schema.py`,
  adding a renderer here, and adding a branch in
  `generator/service.py:generate_assets` — the generic model itself doesn't
  need to change since renderers only consume `GenericPipelinePackage`.
  `quoting.py` holds the escaping helpers all three renderers must route
  every config-derived string through: `yaml_dquote`/`groovy_squote` for
  values landing inside YAML/Groovy, `shell_quote` for values baked directly
  into a shell command at generation time, and `safe_filename_component` for
  anything used in an output filename. Values a platform resolves at
  *runtime* from a build trigger (GitHub's `workflow_dispatch` inputs,
  Azure's pipeline `parameters`, Jenkins' build `parameters`) get delivered
  via an environment variable (`env:` step mapping, or an `environment {}`
  block) and referenced as `"$VAR"` in the shell script, rather than spliced
  into the command text via `${{ }}`/`${...}` — GitHub's `type: choice`
  restriction is enforced only by its web UI, not its dispatch API, so
  splicing that value directly used to be a real, triggerable injection, not
  just a defense-in-depth concern.
  `scripts.py:render_tool_script` writes the `scripts/run-<tool_type>.sh`
  that the generated pipeline actually calls to trigger a test. It renders
  two shell functions, `resolve_environment_identifier`/
  `resolve_scenario_identifier`, one per catalog key, each an
  `if [ "$1" = <key> ]; then echo <identifier>; return; fi` line —
  deliberately exact-match string comparisons rather than a `case`
  statement, since `case` patterns are shell globs and a catalog key
  containing `*`/`?`/`[`/`]` (config-controlled, not validated as
  glob-safe) would otherwise be able to match an environment/scenario key
  it wasn't meant to. For `jmeter`, the rendered script is real: it resolves
  the passed `--environment`/`--scenario` to their identifiers, optionally
  checks the test plan file exists first (only if `verify_scenario_exists`
  is in `pre_run_checks`), then creates
  `run-output/<environment_slug>_<scenario_slug>/` and runs
  `jmeter -n -t <test_plan_path> -l
  run-output/<environment_slug>_<scenario_slug>/results.jtl -e -o
  run-output/<environment_slug>_<scenario_slug>/report
  -Jenvironment=... -Jscenario=...` for real.
  `loadrunner_professional` is also real: it assumes the CI job runs on a
  dedicated agent co-located with the LoadRunner Controller (so
  `wlrun.exe` is already on the box) and runs `wlrun -Run -TestPath
  <scenario_identifier> -ResultName
  run-output/<environment_slug>_<scenario_slug>` — since `wlrun` has no
  native "environment" parameter, a scenario's catalog `identifier` is a
  full `.lrs` file path (customers author one catalog scenario entry per
  environment/scenario combination they have a file for), and the
  environment only names the results folder. `wlrun`'s exit code is known
  to be unreliable on some LoadRunner versions (can return 0 on a failed
  scenario); nonzero is still treated as failure as the best local signal
  available (this results-folder path uses `resolve_environment_slug`/
  `resolve_scenario_slug`, sanitized via `safe_filename_component`, not the
  raw catalog keys — a hostile key otherwise escapes `run-output/`).
  `blazemeter` is also real: it authenticates via `BLAZEMETER_API_KEY_ID`/
  `BLAZEMETER_API_KEY_SECRET` (Basic Auth), optionally checks the host is
  reachable / the project exists / the test exists
  (`verify_host_reachable`/`verify_project_exists`/`verify_scenario_exists`
  — BlazeMeter has its own precheck vocabulary in `PRE_RUN_CHECKS`, distinct
  from LoadRunner's controller-flavored one), starts the test via
  `POST /api/v4/tests/$scenario_identifier/start`, polls
  `GET /api/v4/masters/$master_id/status` bounded by a `--timeout-minutes`
  flag (BlazeMeter-only; the other two tools' generated invocations are
  unaffected), and downloads a summary report on success. The exact
  status-string vocabulary and report endpoint are flagged in the script's
  own comments as best-understanding, pending verification against a live
  account. JMeter and LoadRunner Professional both run locally/on-agent (no
  remote API credentials managed by this script), so their `tool.auth.type`
  is `none`; BlazeMeter's stays `api_token` — see `AUTH_TYPES` in
  `config/schema.py`.

All three tools now also write a normalized
`run-output/<environment_slug>_<scenario_slug>/run-summary.json` after the
tool run is actually attempted (never for a pre-run-check failure, which
still exits immediately with its existing one-line stderr message) — one
shared schema (`tool`, `run_id`, `environment`, `scenario`, `status`
(`passed`/`failed`/`error`), `started_at`/`ended_at`/`duration_seconds`,
`report_link`, `results_dir`, `artifact_status`) produced by shared
`_render_summary_capture_start`/`_render_summary_write` helpers in
`scripts.py`, so a CI/CD step downstream of any of the three
`run-<tool_type>.sh` scripts can read one consistent file regardless of
which tool ran. `environment`/`scenario` are passed through a generated
`json_escape` bash function before embedding, since they carry the raw,
unsanitized `--environment`/`--scenario` CLI values (catalog keys) rather
than the already-sanitized slugs `results_dir` is built from. This also
gave JMeter its own `results_dir` for the first time — it previously wrote
flat into `run-output/`, so a second run silently overwrote the first.
BlazeMeter's own `summary.json`/`report_link.json` (its raw API-report
passthrough) are unchanged and remain separate from `run-summary.json`.

`generate` re-validates the config before doing anything (`cli.py` calls
`validate_config`, then `_blocks_action()` — see the `config/` bullet above
for the errors-vs-warnings rule). All three commands now have clean error
handling: `wizard` catches `EOFError`/`KeyboardInterrupt` (cancellation)
and `OSError`/`yaml.YAMLError` (a malformed existing draft on `--resume`);
`validate`/`generate` both route `load_config()` through
`_load_config_or_none()`, which catches the same `OSError`/`yaml.YAMLError`
pair for a missing or malformed `--config` file. Every case prints a clean
one-line message and returns a stable exit code (`0` success, `1` your
input was wrong, `2` a CLI usage error, `130` an interactively cancelled
wizard) instead of an uncaught traceback.

See `docs/current-state-and-readiness-plan.md` for the full known-gaps list
and multi-milestone readiness plan (stricter validation profiles, YAML-safe
renderer output) if working on hardening this project further — all three
tools' generated scripts are now real, working execution.
