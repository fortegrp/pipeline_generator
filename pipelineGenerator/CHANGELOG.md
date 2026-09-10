# Changelog

All notable changes to `pipeline-generator` are documented here.

## [1.0.0rc3] - 2026-09-10

A code-quality pass over `1.0.0rc2`. No behavior change to generated
output or CLI behavior -- confirmed byte-for-byte identical output for
all 9 example configs, and end-to-end tests unchanged before/after.

- `build_setup_id()` strips a trailing `.git` from `target_repository`
  before slugifying, so `https://.../repo.git` doesn't produce an
  auto-suggested setup ID ending in `-git`.
- `validate_config()`'s required-fields check and the wizard's
  `_is_incomplete()` now read from one shared `required_field_values()`
  helper instead of two hand-maintained lists that could drift apart.
- The wizard's "keep as-is / add more / start over" resume-list logic,
  duplicated between catalog and automated-job prompting, is now one
  shared helper (with new test coverage, since `wizard/flow.py` had none
  before this pass).
- The BlazeMeter `--timeout-minutes` flag computation, duplicated 6
  times across the three CI/CD renderers, is now one shared helper.
- `AutomatedJobSpec` type hint added to a previously-untyped parameter
  in all three renderers.
- Removed `slugify()`'s dead second regex.
- The config schema's enum-like constants (`SUPPORTED_CICD`,
  `SUPPORTED_TOOLS`, `GENERATION_MODES`, `AUTH_TYPES`,
  `WORKING_LOCATIONS`, `PIPELINE_DESTINATIONS`, `PRE_RUN_CHECKS`, and
  `PRE_RUN_CHECKS_BY_TOOL`'s values) are now `tuple` instead of `list`,
  signaling and enforcing that they're never mutated. `base_config()`'s
  own data fields (`catalog.environments`, `automated_jobs`, etc.)
  remain `list`, since those are genuinely mutated.
- `run_wizard()` was a 117-line linear function doing all 8 wizard steps
  inline; decomposed into one function per step plus an 18-line
  orchestrator. Added the first end-to-end test for the full wizard
  flow to confirm the decomposition changed nothing observable.

A `TypedDict` for the config model was considered and explicitly
deferred: the customer-facing risk it would address (a malformed
`customer.yaml` crashing the tool) is already closed by `1.0.0rc2`'s
runtime validator hardening, and without a type-checker in CI its
remaining value (catching developer typos) is speculative relative to
the cost of touching nearly every file in the project.

## [1.0.0rc2] - 2026-09-10

A QA, security, and code-quality pass over `1.0.0rc1`, before any external
use. No new features -- all changes are bug fixes or internal cleanup.

### Fixed (functional/robustness bugs found in manual QA testing)

- `pre_run_checks` typos (e.g. `verify_scenario_exist`) were silently
  dropped with no warning and no trace in the generated script; now
  warned by `validate`.
- Duplicate catalog keys (two environments/scenarios sharing a `key`)
  made the second entry's identifier silently unreachable in the
  generated resolver function; now warned.
- A config with no manual pipeline and no automated jobs enabled
  validated clean and generated zero CI/CD pipeline files with no
  warning; now warned.
- Regenerating into the same `--output-dir` after switching `tool.type`
  (or removing an automated job) left stale files behind (e.g. the old
  tool's `scripts/run-<tool>.sh`); `generate` now wipes and rebuilds the
  setup directory each time.
- `wizard --resume` crashed with a raw traceback on a malformed existing
  draft YAML; now a clean message and exit code `1`.

### Fixed (security/robustness hardening)

- `validate_config` assumed every config section (`setup`, `cicd`,
  `tool`, `tool.auth`, `tool.connection`, `catalog`, `manual_pipeline`,
  `automated_jobs`, and every catalog entry) was the correct dict/list
  shape, with zero defensive checks -- a blank YAML key (parsing to
  `null`) or a list of plain strings instead of mappings crashed with an
  uncaught `AttributeError`. This is reachable through ordinary customer
  mistakes, not just adversarial input. Every mismatch now produces a
  clean validation error instead of a crash, and validation still
  continues past a malformed section to report other real problems in
  the same pass.
- Confirmed not exploitable: YAML "billion laughs" alias-expansion DoS
  (PyYAML aliases share object references rather than textually
  re-expanding); no `eval`/`exec`/`os.system`/`subprocess`/`shell=True`/
  `pickle` anywhere in the Python source.

### Changed (code quality, no behavior change to generated output)

- `build_setup_id()` strips a trailing `.git` from `target_repository`
  before slugifying.
- The wizard's `_is_incomplete()` and `validate_config()`'s
  required-fields check now read from one shared `required_field_values()`
  helper instead of two hand-maintained lists that could drift apart.
- The wizard's "keep as-is / add more / start over" resume-list logic,
  duplicated between catalog and automated-job prompting, is now one
  shared helper.
- The BlazeMeter `--timeout-minutes` flag computation, duplicated 6
  times across the three CI/CD renderers, is now one shared helper.
- `AutomatedJobSpec` type hint added to a previously-untyped parameter
  in all three renderers.
- Removed `slugify()`'s dead second regex.

Confirmed generated output for all 9 example configs is byte-for-byte
identical to `1.0.0rc1`.

## [1.0.0rc1] - 2026-09-10

First internal release candidate. Everything below is implemented and
tested; see `docs/current-state-and-readiness-plan.md` for the full
detail behind each item and what's intentionally still out of scope.

### CLI

- Three subcommands: `wizard`, `validate`, `generate`.
- `wizard` interactively builds or resumes a `customer.yaml` draft,
  filling in only what's missing on a re-run against an existing file.
- `validate` and `generate` catch expected failures (missing/malformed
  config file, validation errors) and print a clean one-line message
  instead of a traceback, with stable, documented exit codes (`0` success,
  `1` your input was wrong, `2` a CLI usage error, `130` an interactively
  cancelled wizard).
- Every command and argument has help text (`--help` at any level).

### Config

- A single customer YAML config drives everything: CI/CD platform, tool
  choice, catalog of environments/scenarios, manual and automated pipeline
  definitions.
- `incomplete: true`/`false` distinguishes an in-progress draft from a
  setup that's supposed to be complete — `generate` enforces that a
  config claiming `incomplete: false` actually has no validation warnings.
- Validation separates errors (always block) from warnings (block only on
  a config claiming to be complete), with dedicated tests for both valid
  and invalid configs.

### Generated Output

- CI/CD pipeline files for GitHub Actions, Azure DevOps, and Jenkins, from
  one shared generic pipeline model — the same manual/automated pipeline
  logic renders identically across all three platforms.
- All generated YAML/Groovy output is safely escaped (`renderers/quoting.py`)
  against adversarial config values (quotes, colons, path traversal), and
  runtime-supplied values (environment/scenario picked at trigger time)
  are delivered via environment variables rather than spliced into
  template expressions, closing a real GitHub Actions `workflow_dispatch`
  injection gap.
- A generated `scripts/run-<tool_type>.sh` per setup — the actual, real
  script the pipeline calls to trigger a test, with no Python or
  `pipeline-generator` involved at execution time:
  - **JMeter** — runs `jmeter -n -t ...` for real, writing into its own
    per-run `run-output/<environment_slug>_<scenario_slug>/` folder.
  - **LoadRunner Professional** — runs `wlrun -Run -TestPath ...` for
    real, assuming the CI job runs on an agent co-located with the
    Controller.
  - **BlazeMeter** — drives the REST API v4 directly (start, poll,
    summary) via `curl`/`jq`, authenticating via
    `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET`.
  - All three write a normalized `run-summary.json` after attempting a
    run (`status`, `run_id`, timestamps, duration, report link, artifact
    status) — one shared schema regardless of which tool ran.
  - Real pre-run checks per tool where a local/API equivalent exists
    (test-plan existence, controller/`wlrun` reachability, BlazeMeter
    host/project/test existence); anything without a local equivalent
    stays a clearly labeled `# TODO precheck: ...` comment.
- A generated setup README covering setup summary, remaining TODOs,
  tool-specific connection details, CI/CD-specific manual and automated
  usage instructions, artifact locations, and troubleshooting guidance.

### Testing and CI

- GitHub Actions CI (`pipeline-generator-ci.yml`) runs the full suite on
  every push/PR across Python 3.9 and 3.12.
- 100 tests covering config validation (valid and invalid), generation for
  every example config, all three renderers' YAML/Groovy output
  (including adversarial-input escaping), all three tools' generated
  scripts executed end to end against stubbed fake remote systems
  (`jmeter`/`wlrun`/`curl`/`jq`), the generated README, and CLI
  success/failure paths.

### Known Limitations

- LoadRunner Professional's generated CI/CD pipeline still targets a
  hosted runner by default — retargeting to a Controller-co-located agent
  is a manual step (documented in the generated README's Troubleshooting
  section).
- BlazeMeter's exact API v4 status vocabulary and report endpoint are our
  best understanding, not yet verified against a live account.
- No `--version` flag or non-interactive config-creation mode yet.
