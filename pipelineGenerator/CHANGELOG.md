# Changelog

All notable changes to `pipeline-generator` are documented here.

## [Unreleased]

- New `cicd.runner` picks where generated pipelines run: GitHub Actions
  `runs-on` labels (comma-separated), an Azure DevOps self-hosted agent
  pool, or a Jenkins agent label; blank keeps the hosted default
  (`ubuntu-latest` / `agent any`). The wizard asks it in Step 2. It's
  required for LoadRunner Professional (wizard default `TODO`, validator
  warning, README TODO), whose pipelines previously targeted hosted runners
  that can't run `wlrun` and needed a hand-edit. Generated steps now always
  run the script with bash — `shell: bash` on GitHub and a `bash:` step on
  Azure (previously `script:`, i.e. cmd.exe on Windows agents) — so a
  Windows agent needs Git for Windows' bash on the agent's PATH (see the
  user guide for the exact folders). `generate` also writes
  `scripts/.gitattributes` (`*.sh text eol=lf`) so a Windows checkout
  doesn't turn the script into CRLF, and LoadRunner now passes `wlrun` an
  absolute `-ResultName`. `cicd.runner` accepts a list of labels; a `TODO`
  runner warns for every tool.

- BlazeMeter credentials are now wired into every generated pipeline.
  Previously no pipeline passed `BLAZEMETER_API_KEY_ID`/
  `BLAZEMETER_API_KEY_SECRET` to the script, so every BlazeMeter run
  stopped at "must be set". GitHub Actions maps repository secrets of
  those names into the run step, and automated (`workflow_call`) workflows
  declare them as required secrets (call with `secrets: inherit`). Azure
  DevOps maps secret pipeline variables of those names into the step's
  `env:`. Jenkins wraps the call in `withCredentials` on a Username with
  password credential `blazemeter-api-key`. The generated README's TODOs
  now say exactly what to create per platform (and drop the vague "fill
  secret variable names" line).
  `run-blazemeter.sh` also stops with a clear error when a credential
  arrives as an unexpanded Azure `$(...)` macro (an undefined secret
  variable), instead of failing later with a misleading 401.

- **Breaking:** scenarios now belong to an environment.
  `catalog.scenarios` (a flat top-level list) is removed; each
  `catalog.environments[]` entry has its own `scenarios[]`. A scenario key
  only needs to be unique within its environment, so `checkout_smoke` can
  point at `qa`'s `.lrs` under `qa` and at staging's under `staging` —
  retiring the `_qa`/`_staging` key-suffix workaround. The manual pipeline
  (all three CI/CD platforms) now shows **one** `test_case` dropdown listing
  only the defined `<environment>: <scenario>` pairs instead of two
  independent dropdowns, so a mismatched pair can no longer be selected.
  `scripts/run-<tool>.sh` takes `--test-case "<environment>: <scenario>"`
  instead of `--environment`/`--scenario` (automated jobs bake the same
  flag); the four generated `resolve_*` functions become one
  `resolve_test_case`. Catalog keys must now be simple names (letters,
  digits, `_`, `.`, `-`, starting with a letter or digit — an error
  otherwise), which also rules out selector collisions. The validator
  checks duplicate scenario keys per environment, warns on an environment
  with no scenarios, and checks an automated job's `scenario_ref` against
  its own environment. The wizard asks each environment's scenarios right
  after the environments, re-asks invalid keys, and offers an automated
  job only its chosen environment's scenarios. `run-summary.json` is
  unchanged. No migration shim: move each config's scenarios under their
  environment (all 9 examples are migrated) — an old config's top-level
  `catalog.scenarios` is reported as an error saying exactly that. A
  missing or non-string catalog key (e.g. YAML `key: 1` or `key: yes`) is
  now an error instead of a `generate` crash.

- **Breaking:** JMeter and BlazeMeter configs now need a filled
  `load_profile` (`users`, `ramp_up_seconds`, `duration_minutes`,
  `throughput_rps`). An existing `incomplete: false` config without it
  fails `generate` with `load_profile.* is missing` warnings — add the
  section (or run `wizard --resume`). BlazeMeter runs now always apply
  these values to the test.
- Added test parameters. New `load_profile` config section: `test_type`
  (free-text label, every tool) and, for JMeter and BlazeMeter, `users`,
  `ramp_up_seconds`, `duration_minutes`, `throughput_rps` (`0` = no cap).
  LoadRunner Professional deliberately takes its load shape from the
  `.lrs` scenario; there is no ramp-down. The wizard asks them in a new
  Step 4 ("Test parameters"; it's now 8 steps), accepting `TODO`. The
  values are baked into `scripts/run-<tool>.sh` as defaults, overridable
  with `--users`/`--ramp-up-seconds`/`--duration-minutes`/
  `--throughput-rps`/`--test-type`; the manual pipeline (all three CI/CD
  platforms) exposes them as pre-filled trigger inputs delivered via env
  vars; automated jobs use the config values. JMeter receives them as
  `-J` properties (plus derived `duration_seconds` = ramp-up + duration,
  since JMeter's thread lifetime includes the ramp-up, and
  `throughput_per_minute`) that the `.jmx` reads via `${__P(...)}` — the
  generated README lists them. BlazeMeter applies them with
  `PATCH /api/v4/tests/<id>` (`overrideExecutions`) before starting; this
  persists on the test and is pending verification against a live
  account. `run-summary.json` gains `test_type`, `users`,
  `ramp_up_seconds`, `duration_minutes`, `throughput_rps` (numbers are
  `null` for LoadRunner, keeping one shared key set). The validator warns
  on TODO load values (JMeter/BlazeMeter only), errors on out-of-range
  ones (including leading zeros at run time), requires `test_type` to be a
  short single-line label, and warns when a pipeline timeout isn't longer
  than ramp-up + duration.
- Generated scripts now stop before any pre-run check or tool call when a
  value they need is still `TODO` (connection fields, the resolved catalog
  identifier, load values), with one line naming the `customer.yaml` field
  — instead of handing the literal string `TODO` to the tool.
- The wizard now keeps a config `incomplete: true` while any value is
  still missing/TODO (e.g. a TODO test plan path or load value), not only
  while a required field is missing. Other warnings (a too-short timeout,
  a duplicate key) still block `generate` on a complete config. Previously such a config was saved as
  `incomplete: false` and `generate` then refused it.

- Removed the `verify_load_generators_connected` pre-run check (offered
  for LoadRunner Professional) from `PRE_RUN_CHECKS` and
  `PRE_RUN_CHECKS_BY_TOOL`. Same issue as `collect_results` before it: it
  was offered as a real option in the wizard but only ever rendered as a
  dead `# TODO precheck: ...` comment — it would need Controller-side
  load-generator host-status querying with no local CLI equivalent
  available to `wlrun`, so it was never going to become real. Every
  pre-run check now offered by the wizard is actually implemented for the
  tool(s) it's offered for.
- Wizard's environment/scenario identifier prompt no longer says "remote
  identifier" for every tool — that was only accurate for BlazeMeter (a
  real Test ID on BlazeMeter's servers). It's now tool-specific:
  JMeter's is a `-J` property value your `.jmx` reads, LoadRunner's
  scenario identifier is a `.lrs` file path, and BlazeMeter's stays a Test
  ID. Also documented (in the user guide and the prompt label itself) that
  the *environment* identifier specifically is never actually used by the
  generated script for LoadRunner or BlazeMeter — only its `key` affects
  the results-folder name; it's still asked for consistency across tools,
  but the wording no longer implies it does something it doesn't.
- JMeter execution moved fully to Docker. `scripts/run-jmeter.sh` now runs
  `docker run --rm -v "$(pwd):/workspace" -w /workspace <docker_image> -n
  -t ...` instead of a local `jmeter` binary — the whole working directory
  is bind-mounted (not just the test plan file) so CSV data sets/fragments
  referenced by relative path still resolve, and results land directly on
  the host filesystem. `tool.connection.jmeter_bin` is replaced by
  `docker_image` (optional, defaults to `justb4/jmeter:5.6.3` via
  `DEFAULT_JMETER_DOCKER_IMAGE` in `config/schema.py`). Added a new
  `verify_docker_available` pre-run check (checks `docker` is on `PATH`),
  mirroring LoadRunner's `verify_controller_access`. Existing `customer.yaml`
  files with `jmeter_bin` still load fine (it's just ignored) but should be
  updated to `docker_image`; the agent/runner now needs Docker installed
  instead of a local JMeter install.
- Wizard no longer asks for a setup ID. The "Setup identifier" step is
  gone; `setup.id` is now assigned silently right after CI/CD platform and
  tool are chosen, as `<cicd_type>-<tool_type>` plus a short random hex
  suffix (`generate_unique_setup_id()` in `id_builder.py`) so two setups
  sharing the same CI/CD+tool combo can't suggest the same ID and silently
  overwrite each other's generated output folder. Once assigned it's never
  regenerated on a later `--resume`, even if CI/CD or tool changes. The
  wizard is now 7 steps instead of 8. You can still hand-edit `setup.id`
  directly in the YAML for a more readable name.
- Wizard Step 5 no longer asks "Generate manual pipeline?" as its own
  yes/no question — choosing `manual_only`/`both` back in Step 1 already
  means you want one, so asking again just read as a duplicate question.
  `manual_pipeline.enabled` is now set automatically to match
  `generation_mode` instead of being independently wizard-toggleable.
  Also fixed the JMeter connection prompt (and matching doc line), which
  referenced "the target repository" — a concept removed from this
  project's config model in the prior cleanup pass.
- Removed four more dead config fields, found by tracing every `base_config()`
  field to confirm something actually reads it: `version` (top-level,
  never read anywhere), `artifacts.download_remote_results` and
  `artifacts.fail_on_partial_download` (never read, not even wizard-asked),
  `catalog.environments[].name`/`catalog.scenarios[].name` (the wizard's
  "environment/scenario display name" prompt — captured, stored, even
  threaded into `InputOption.display_name`, but never rendered into any
  generated pipeline file or the README; `InputOption.display_name` is
  removed accordingly), and `tool.auth.type` (asked in wizard Step 2 and
  validated against `AUTH_TYPES` as a required field, but nothing branched
  on its value — real credential handling is hardcoded per `tool.type`
  directly in `scripts.py`). Wizard Step 2 no longer asks for an
  authentication option, and catalog entries are now just `key` +
  `identifier`. `AUTH_TYPES` is removed from the schema.
- Removed the `collect_results` pre-run check from `PRE_RUN_CHECKS` and
  every tool's `PRE_RUN_CHECKS_BY_TOOL` entry. It was never implemented
  for any tool (JMeter, LoadRunner Professional, and BlazeMeter all only
  ever rendered it as a dead `# TODO precheck: collect_results` comment),
  and conceptually it never belonged in a *pre-run* check list —
  collecting results is something you do after a run finishes, not
  before it starts. Existing `customer.yaml` files listing it now get a
  validation warning ("Unrecognized pre_run_checks value") instead of
  silently no-oping; remove it from `pre_run_checks` to clear the
  warning.
- Removed `setup.working_location`, `setup.final_pipeline_destination`,
  `setup.ci_can_use_central_repo_directly`, and `setup.target_repository`
  from the config schema. The first three were purely descriptive (echoed
  into the generated README, in one case not even that) and never
  affected what got generated; `target_repository` only fed an
  auto-suggested setup ID. Wizard Step 1 now asks a single question
  (`generation_mode`) instead of five, with a plain-language explanation
  of manual vs. automated pipelines up front. `build_setup_id()` now
  slugifies `<cicd_type>-<tool_type>` only (no repo name component).
  Existing `customer.yaml` files with the removed fields still load fine
  (they're just ignored) but should have them removed.

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
