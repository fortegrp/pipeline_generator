# Pipeline Generator: Current State and Readiness Plan

## Purpose

Pipeline Generator is a Python CLI scaffold for onboarding customer-specific
performance testing setups and generating CI/CD pipeline assets from a single
YAML configuration file.

The project is designed to help performance engineers and DevOps teams produce
repeatable pipeline packages for performance test execution. A setup can define
the target CI/CD platform, performance testing tool, environments, scenarios,
manual pipeline behavior, automated jobs, pre-run checks, and artifact handling
rules.

At the current stage, the project is strongest as a generator for CI/CD setup
packages. `pipeline-generator` never executes a performance test itself — its
job ends at `generate`, which now writes a `scripts/run-<tool_type>.sh`
alongside the CI/CD files. That script is real, working execution for JMeter;
for BlazeMeter and LoadRunner Professional it's a template with connection
details filled in but the actual remote API/controller call still a `# TODO`.

The readiness plan in this document is intended to strengthen the original
idea, not replace it. In particular, the project should continue to support
draft-friendly onboarding with TODO placeholders. Stricter validation should
apply when a setup is being treated as ready for handoff or execution, while
draft generation should remain available through explicit user intent.

## Current Project Status

The project is a scaffolded v1 foundation.

Implemented:

- Python package structure using a `src/` layout.
- CLI entry point named `pipeline-generator`.
- Interactive wizard for creating or resuming setup YAML files.
- YAML config loading, saving, merging with defaults, and validation.
- Generic internal pipeline model.
- GitHub Actions renderer.
- Azure DevOps renderer.
- Jenkins renderer.
- Generated setup README.
- A generated `scripts/run-<tool_type>.sh` per setup, written alongside the
  CI/CD files — real, working JMeter execution; a filled-in-but-TODO
  template for BlazeMeter and LoadRunner Professional.
- Example customer configs for the supported CI/CD and tool combinations.
- Renderer tests for all three CI/CD platforms (GitHub Actions and Azure
  DevOps tests also parse the generated YAML to catch syntax breakage).
- A test that validates and generates every example config.
- Clean CLI error handling for `wizard` (expected exceptions are caught and
  printed as plain messages instead of tracebacks; `generate` has no
  exception paths beyond what validation already catches).
- CI (GitHub Actions, `.github/workflows/pipeline-generator-ci.yml` at the
  repo root) running `pytest` on push/PR across Python 3.9 and 3.12.

Not implemented yet:

- The real BlazeMeter API call in the generated `run-blazemeter.sh`
  template's `# TODO` block.
- The real LoadRunner Professional controller call in the generated
  `run-loadrunner_professional.sh` template's `# TODO` block.
- Real pre-run checks beyond JMeter's `verify_scenario_exists` (the
  generated script actually checks the test plan file exists for JMeter;
  every other configured check, for every tool, is currently only a
  `# TODO precheck: ...` comment in the BlazeMeter/LoadRunner templates —
  JMeter has no other checks defined).
- Robust generated YAML/Groovy escaping and validation (the renderers still
  build output via unescaped f-strings; the new renderer tests catch
  accidental syntax breakage but don't guard against a customer value like a
  stray quote producing invalid output).
- Strong schema enforcement.
- Dedicated tests for configs that should fail validation, and CLI tests for
  successful/failing command paths.

## Supported Platforms and Tools

### CI/CD Platforms

The generator currently supports:

- `github_actions`
- `azure_devops`
- `jenkins`

Renderer output locations:

- GitHub Actions files are written under `.github/workflows/`.
- Azure DevOps files are written under `azure/`.
- Jenkins files are written under `jenkins/` as declarative `Jenkinsfile.*` files.

### Performance Testing Tools

The config model currently supports:

- `blazemeter`
- `loadrunner_professional`
- `jmeter` — local/self-hosted rather than a remote SaaS tool; typically
  paired with `tool.auth.type: none` and a `test_plan_path` connection field.

`generate` writes a `scripts/run-<tool_type>.sh` for every setup, but the
three tools aren't equally finished. JMeter's generated script is real,
working execution: it resolves the environment/scenario to their catalog
identifiers and runs a real `jmeter -n -t ...` subprocess — no remote API or
credentials needed. BlazeMeter's and LoadRunner Professional's generated
scripts are templates, not stubs: real, syntactically valid bash with
connection details already filled in as variables and configured pre-run
checks listed as `# TODO precheck: ...` comments, but the actual remote
API/controller call is left undone — the script prints a clear
`"... execution is not implemented in this generated script yet."` and exits
non-zero until someone fills that part in.

### Authentication Types

Supported auth type values are:

- `api_token`
- `username_password`
- `service_account`
- `network_vpn_manual_setup`
- `none` — for tools like JMeter that run locally and need no remote auth.

The current project validates these values but does not yet implement secret
resolution, credential injection, or remote authentication behavior.

## Repository Structure

```text
pipeline_generator/
  README.md
  pyproject.toml
  setup.py
  examples/
    azure-blazemeter/
    azure-loadrunner/
    github-blazemeter/
    github-loadrunner/
  src/
    pipeline_generator/
      cli.py
      config/
      generator/
      renderers/
      wizard/
  tests/
```

### Key Modules

`src/pipeline_generator/cli.py`

Defines the command-line interface. The CLI exposes three commands:

- `wizard`
- `validate`
- `generate`

There is no `run` command — `pipeline-generator` never executes a
performance test itself. `generate` writes a `scripts/run-<tool_type>.sh`
that the generated pipeline calls directly instead.

`src/pipeline_generator/config/`

Contains the base config shape, supported enum values, YAML loading and saving,
placeholder handling, and validation logic.

`src/pipeline_generator/wizard/`

Contains the interactive onboarding flow. The wizard asks for setup location,
target repository, CI/CD platform, performance tool, authentication type,
connection details, environments, scenarios, automated jobs, and pre-run checks.

`src/pipeline_generator/generator/`

Builds a generic internal pipeline package from customer YAML. This package is
intended to keep renderer logic separate from raw config parsing.

`src/pipeline_generator/renderers/`

Converts the generic pipeline model into CI/CD-specific files for GitHub
Actions, Azure DevOps, and Jenkins, plus the setup README. `scripts.py`
additionally writes `scripts/run-<tool_type>.sh` — a real, working script for
JMeter, and a connection-details-filled-in template (ending in a `# TODO`
and a clear "not implemented yet" error) for BlazeMeter and LoadRunner
Professional. Every catalog key it resolves inside the generated script goes
through an exact-match shell comparison (`if [ "$1" = <key> ]; ...`), not a
`case` statement — `case` patterns are shell globs, so a catalog key
containing `*`/`?`/`[`/`]` could otherwise glob-match an environment/scenario
key it wasn't meant to. This is where real BlazeMeter and LoadRunner
Professional execution logic should be implemented, by filling in each
template's `# TODO` block.

## CLI Behavior

### Wizard

```bash
pipeline-generator wizard --output setups/acme.yaml
```

Creates a draft YAML config. The wizard supports TODO placeholders so a setup
can be started before all customer details are known.

Resume mode:

```bash
pipeline-generator wizard --output setups/acme.yaml --resume
```

Running the wizard against an `--output` path that already exists without
`--resume` refuses up front instead of overwriting the file. Resuming a
draft that already has environments, scenarios, or automated jobs offers
keep-as-is/add-more/start-over instead of silently discarding the existing
list. The flow is broken into eight numbered sections with inline hints on
the less obvious choices, pre-run checks are chosen from a single
multi-select screen, and it ends by printing a summary and running the same
checks `validate` would.

### Validate

```bash
pipeline-generator validate --config setups/acme.yaml
```

Loads a config, merges it with base defaults, and validates supported values and
required fields.

Strict mode:

```bash
pipeline-generator validate --config setups/acme.yaml --strict
```

In strict mode, warnings are treated as failures.

### Generate

```bash
pipeline-generator generate --config setups/acme.yaml --output-dir generated
```

Generates a setup-specific output directory containing:

- A copy of `customer.yaml`.
- CI/CD pipeline YAML files.
- A generated `scripts/run-<tool_type>.sh`.
- A generated setup README.

Current behavior: generation always stops on validation errors. Whether it
also stops on warnings now depends on the config's own `incomplete` flag:
warning-only configs with `incomplete: true` (drafts) still generate, while
`incomplete: false` configs (declared ready) are blocked by the same
warnings, with a message pointing at the fix or at flipping the flag back.
This reuses the config's own declared intent instead of adding a separate
`--allow-incomplete`/`--allow-warnings` flag.

There is no `run` (or `--dry-run`) CLI command any more — this used to be
a fourth subcommand that built a run request from the config and either
wrote a dry-run execution plan or drove a Python tool adapter. That whole
subsystem (`runtime/`, `adapters/`, the `run` subcommand) has been deleted.
`generate` is the tool's last step now; see "Generated Run Script" below for
what replaced `run`.

### Generated Run Script (not a CLI command)

`generate` writes `scripts/run-<tool_type>.sh` alongside the CI/CD files.
This is what the generated pipeline's step actually calls
(`./scripts/run-<tool_type>.sh --environment "$ENVIRONMENT" --scenario
"$SCENARIO"`) — it is a plain, standalone bash script with no dependency on
`pipeline-generator` or Python at execution time. It can also be run by hand
from a checkout of the generated setup.

- For **JMeter**, it's real and complete: it resolves `--environment`/
  `--scenario` to their catalog identifiers, optionally checks the test plan
  file exists first (if `verify_scenario_exists` is in `pre_run_checks`),
  then runs `jmeter -n -t <test_plan_path> -l run-output/results.jtl -e -o
  run-output/report -Jenvironment=... -Jscenario=...` for real.
- For **BlazeMeter** and **LoadRunner Professional**, it's a template: real,
  syntactically valid bash with connection details already filled in as
  variables and remaining `pre_run_checks` listed as `# TODO precheck: ...`
  comments, ending with `echo "ERROR: <Tool> execution is not implemented in
  this generated script yet." >&2` and `exit 1`.

There is no more `incomplete`-flag warning check at this stage — that check
only ever ran at `generate` time, before the script was written; the script
itself has no knowledge of the config's `incomplete` flag.

## Config Model

The YAML config is the source of truth for a customer setup.

Major sections:

- `version`: config version.
- `incomplete`: whether TODO placeholders are still expected.
- `setup`: setup identity, repository location, destination, and generation mode.
- `cicd`: selected CI/CD platform.
- `tool`: selected performance testing tool, auth type, and connection details.
- `manual_pipeline`: manual pipeline settings.
- `automated_jobs`: reusable automated job definitions.
- `catalog`: available environments and scenarios.
- `pre_run_checks`: checks requested before execution.
- `artifacts`: artifact download behavior.
- `readme`: generated documentation options.

Supported generation modes:

- `manual_only`
- `automated_only`
- `both`

Supported working locations:

- `central_repo`
- `customer_repo`

Supported final pipeline destinations:

- `stay_in_central_repo`
- `copy_to_customer_repo`

## Generation Flow

The generation flow is:

1. Load `customer.yaml`.
2. Merge the loaded config with base defaults.
3. Validate the merged config.
4. Build a generic pipeline package.
5. Select a renderer based on `cicd.type`.
6. Write generated pipeline files.
7. Write `scripts/run-<tool_type>.sh`.
8. Write a generated README.
9. Copy the final `customer.yaml` into the generated setup package.

The generic model currently includes:

- Setup ID.
- CI/CD type.
- Tool type.
- Optional manual pipeline spec.
- Automated job specs (each carrying its `environment_ref`/`scenario_ref`).
- Pipeline inputs for environments and scenarios, each carrying its catalog
  `identifier`.

Each renderer builds its own `./scripts/run-<tool_type>.sh --environment ...
--scenario ...` invocation from `package.tool_type` and the relevant
`environment_ref`/`scenario_ref`, rather than reading a shared run-command
field off the generic model — the three platforms need different delivery
mechanisms for runtime-supplied values (see "Renderer Output Uses
Handwritten YAML Strings" below), which a single generic command list
couldn't represent safely.

This design is useful because it keeps CI/CD-specific rendering separate from
the customer config shape.

## Generated Script Execution Flow

There is no more Python-side runtime flow — `pipeline-generator` never
executes anything itself. What used to be the runtime flow (load config,
select an adapter, build a run request, dry-run or drive the adapter through
`run_prechecks`/`start_run`/`wait_for_completion`/`collect_artifacts`) has
been replaced by the flow baked into the generated
`scripts/run-<tool_type>.sh` itself, which runs standalone, later, on
whatever machine the CI/CD job executes on:

1. Parse `--environment` and `--scenario` (both required).
2. Resolve each to its catalog `identifier` via generated shell functions
   (`resolve_environment_identifier`/`resolve_scenario_identifier`) — an
   unrecognized key prints `Unknown environment key: ...` /
   `Unknown scenario key: ...` and exits non-zero.
3. Create `run-output/`.
4. Run the tool:
   - **JMeter**: optionally verify the test plan file exists (if
     `verify_scenario_exists` is configured), then run `jmeter -n -t ...`
     for real.
   - **BlazeMeter** / **LoadRunner Professional**: print each remaining
     configured pre-run check as a `# TODO precheck: ...` comment (they are
     not executed), then print a clear "not implemented in this generated
     script yet" error and exit 1 — the API/controller call itself is not
     yet written.

Current limitation: the BlazeMeter and LoadRunner Professional scripts stop
before calling any remote API/controller — see "BlazeMeter and LoadRunner
Professional Scripts Are Templates, Not Adapters" below for what's needed to
finish either one.

## Current Examples

The repository includes nine example customer configs:

- `examples/github-blazemeter/customer.yaml`
- `examples/github-loadrunner/customer.yaml`
- `examples/github-jmeter/customer.yaml`
- `examples/azure-blazemeter/customer.yaml`
- `examples/azure-loadrunner/customer.yaml`
- `examples/azure-jmeter/customer.yaml`
- `examples/jenkins-blazemeter/customer.yaml`
- `examples/jenkins-loadrunner/customer.yaml`
- `examples/jenkins-jmeter/customer.yaml`

These examples demonstrate the intended matrix of supported CI/CD platforms and
performance tools.

## Known Gaps and Risks

### Validation Is Too Permissive for Generation — Resolved

Validation distinguishes errors from warnings. `generate` and `run` used to
only block on errors, so warning-only configs could generate incomplete or
broken pipeline files regardless of how finished the setup actually was.

This is now resolved by reusing the config's own `incomplete` flag instead of
adding a new CLI flag: `generate` still only blocks on errors when
`incomplete: true` (drafts stay exactly as permissive as before), but blocks on
warnings too once a config declares `incomplete: false` — treating that flag
as an enforced promise rather than a label with no effect. (`run` no longer
exists as a command; this rule applied to it too, back when it did.)
`validate` itself is unchanged and only escalates warnings when `--strict` is
passed.

### Runtime Errors Are Not User-Friendly — Resolved (moot)

This used to describe the `run` CLI command's request-building `ValueError`s
(bad `--job`, missing `--environment`/`--scenario`) surfacing as raw Python
tracebacks instead of clean CLI output. The `run` command, and the Python
runtime layer that raised those errors, have both been deleted — bad input
is now handled entirely inside the generated `scripts/run-<tool_type>.sh`
itself (missing `--environment`/`--scenario` prints a one-line `Usage: ...`
message and exits 1; an unrecognized environment/scenario key prints
`Unknown environment key: ...` / `Unknown scenario key: ...` and exits 1),
so there's no longer a Python exception path here to catch.

### README and Schema Are Slightly Out of Sync — Resolved

The README example used `customer_repo` for `final_pipeline_destination`,
which isn't a valid value (the schema only accepts `stay_in_central_repo` or
`copy_to_customer_repo`). Fixed to use `copy_to_customer_repo`.

### `setup.id` Could Write Outside the Output Directory — Resolved

`generate_assets()` built the generated setup's directory as
`output_dir / config["setup"]["id"]` with no sanitization. `setup.id` comes
straight from the config file being generated, and this tool's own
`working_location: customer_repo` model explicitly expects that file to be
authored/edited outside the central repo by a less-trusted collaborator — so
a `setup.id` of `../../etc` (relative traversal) or an absolute path (which
`pathlib`'s `/` operator resolves by discarding everything before it) let
`generate` write files anywhere on disk the invoking process had permission
to reach, entirely outside `--output-dir`. Fixed by slugifying `setup.id`
(the same `slugify()` already used for wizard-generated setup ids) before
using it as a path segment, confirmed by
`test_generate_assets_confines_relative_traversal_to_output_dir` and
`test_generate_assets_ignores_absolute_setup_id` in
`tests/test_generate_assets_path_safety.py` (both reproduce the escape
against the pre-fix code before asserting the fix holds).

### Renderer Output Uses Handwritten YAML Strings — Resolved

Renderers build output through f-strings, which used to embed user-controlled
values (job names, pipeline names, environment/scenario values) completely
unescaped — a stray `"`, `:`, `'`, or shell metacharacter in any of those
could produce invalid YAML/Groovy or, worse, get interpreted literally inside
a shell `run:`/`script:`/`sh` step.

All three renderers now route every embedded value through
`renderers/quoting.py`: `yaml_dquote()` (JSON-string escaping, a valid subset
of YAML double-quoted scalar syntax) for values inside YAML, `groovy_squote()`
for values inside a Jenkinsfile's Groovy strings, `shell_quote()`
(`shlex.quote`) for values baked directly into a shell command at generation
time, and `safe_filename_component()`/per-platform job-id sanitizers so a
hostile job name can't produce a path-traversing filename or an invalid job
identifier. Covered by adversarial-input tests per renderer
(`test_render_github_actions_escapes_adversarial_values`,
`test_render_azure_devops_escapes_adversarial_values`,
`test_render_jenkins_escapes_adversarial_values`) that feed in values
containing quotes, colons, semicolons, spaces, and `../` sequences and assert
the output still parses/round-trips correctly.

A second, distinct class of risk was also closed: the GitHub Actions manual
workflow's `${{ github.event.inputs.* }}` and the Azure DevOps manual
pipeline's `${{ parameters.* }}` (and Jenkins' `${params.X}`) used to be
spliced directly into the `run:`/`script:`/`sh` text as compile-time template
expressions. This was a confirmed, exploitable gap on GitHub Actions
specifically: `workflow_dispatch`'s `type: choice` restriction is enforced
only by GitHub's web UI, not by the dispatch REST/CLI API — so anyone able to
trigger the workflow via API could pass an arbitrary string for
`--environment`/`--scenario`, bypassing the "it's constrained to our declared
choices" assumption entirely and getting it spliced straight into the shell
command. All three renderers now deliver these values via an environment
variable (`env:` on GitHub Actions/Azure DevOps steps, an `environment {}`
block or Jenkins' auto-exported build parameters for Jenkins) and reference
them as `"$VAR"` in the shell script instead, so the value is delivered as
data rather than re-parsed as command text.

### BlazeMeter and LoadRunner Professional Scripts Are Templates, Not Adapters — Partially Resolved

This gap used to be about Python `ToolAdapter` stubs (`adapters/`) that
defined the right shape but raised `NotImplementedError` for every tool. That
whole adapter/runtime subsystem has been deleted; there is no more Python
execution layer at all. In its place, `generate` writes a
`scripts/run-<tool_type>.sh` per setup:

- **JMeter is now real, working execution** — resolved. The generated
  script resolves the environment/scenario and runs a real `jmeter -n -t
  <plan> -l <results> -e -o <report>` subprocess. Nothing left to do here.
- **BlazeMeter and LoadRunner Professional remain unimplemented**, but as
  templates rather than stubs: the generated script is real, syntactically
  valid bash with connection details already filled in as variables and
  configured pre-run checks listed as `# TODO precheck: ...` comments — it
  just stops short of the actual API/controller call, printing a clear
  `"... execution is not implemented in this generated script yet."` and
  exiting 1.

Risk:

- The generated pipelines call `./scripts/run-<tool_type>.sh` directly, and
  for BlazeMeter/LoadRunner Professional that call will always fail with the
  "not implemented yet" error until someone fills in the template.

Recommended change:

- Fill in the two remaining templates incrementally, directly in
  `renderers/scripts.py`'s `_render_template_script` (or by hand-editing the
  generated script for a one-off setup). BlazeMeter is the lower-effort of
  the two, since it's API-driven. LoadRunner Professional remains the more
  involved of the two, since it also requires deciding the remote-execution
  mechanism (see Milestone 2 below).

### Test Coverage Is Minimal

Current tests cover only:

- Setup ID slug generation.
- Base config validation warnings.

Risk:

- Renderer regressions, CLI regressions, and config edge cases can go unnoticed.

Recommended change:

- Add tests around validation, generation output, generated script content
  (per tool), and CLI exit behavior.

## Readiness Plan

The project should be made ready in two milestones:

- Milestone 1: Ready to generate reliable customer pipeline packages.
- Milestone 2: Ready to execute performance tests remotely.

## Milestone 1: Generation Readiness

### 1. Tighten Config Validation

Goals:

- Prevent incomplete or internally inconsistent configs from generating broken
  assets by default.
- Give users clear messages about what must be fixed.
- Preserve the original draft-friendly onboarding flow for configs that still
  contain TODO placeholders.

Tasks:

- Validate `setup.final_pipeline_destination` against supported values.
- Validate `setup.working_location` against supported values.
- Validate automated job references as errors for complete configs.
- Validate manual pipeline catalog requirements as errors when manual generation
  is enabled.
- Validate timeout values as positive integers.
- Validate job names for CI/CD compatibility.
- Validate environment and scenario keys for uniqueness.
- [x] Treat `incomplete: true` configs as drafts — `generate`/`run` only
  block on warnings when `incomplete: false`.
- [x] Allow draft generation to keep working without new friction — resolved
  by reusing the existing `incomplete` flag rather than adding an
  `--allow-incomplete`/`--allow-warnings` flag.
- [x] Add clear CLI language that distinguishes draft validation from
  ready-for-handoff validation — `generate`/`run` now print a message naming
  the `incomplete: false` promise that's being broken when they block.

### 2. Formalize the Schema

Goals:

- Make the config contract explicit and easier to evolve.
- Support both draft configs and ready-to-generate configs without losing the
  wizard's TODO-based onboarding model.

Tasks:

- Introduce typed config models or a JSON Schema.
- Document every field, type, allowed value, and default.
- Define validation profiles for draft, generation-ready, and execution-ready
  configs.
- Add config version handling.
- Add a migration strategy before introducing future breaking changes.

### 3. Harden Renderers

Goals:

- Generate CI/CD YAML that remains valid with real customer names and IDs.

Tasks:

- Safely quote YAML values.
- Normalize generated job IDs and file names.
- Add generated YAML syntax validation.
- Add renderer snapshot tests.
- Ensure automated job names are valid for GitHub Actions and Azure DevOps.
- Add secret and variable placeholders where each platform expects them.
- Make generated output deterministic.

### 4. Improve Generated Documentation

Goals:

- Make each generated setup package self-explanatory for performance engineers
  and DevOps users.

Tasks:

- Include CI/CD-specific manual run instructions.
- Include automated job integration instructions.
- Include required secrets and variables.
- Include tool-specific connection details.
- Include artifact behavior and output locations.
- Include troubleshooting guidance.
- Reflect `working_location` and `final_pipeline_destination` in the generated
  README.

### 5. Improve CLI UX

Goals:

- Make the CLI predictable, scriptable, and friendly.

Tasks:

- Catch expected exceptions and print clean error messages.
- Return stable nonzero exit codes for validation failures.
- Add `--version`.
- Add clear help text for every command.
- Consider adding a non-interactive config creation mode.

### 6. Add Project CI and Tests

Goals:

- Prevent regressions in generator behavior.

Tasks:

- [x] Add a development dependency group for test tooling.
- [x] Run tests with `pytest`.
- [x] Add GitHub Actions or Azure DevOps CI for this repository.
- [x] Test supported Python versions (3.9 and 3.12 in the CI matrix).
- [ ] Add validation tests for valid and invalid configs (the example-config
      test below covers the valid side; there's no dedicated test yet for
      configs that should fail validation).
- [x] Add renderer tests for GitHub Actions and Azure DevOps.
- [x] Add tests for the generated `scripts/run-<tool_type>.sh` content, for
      manual and automated modes across all three tools (superseded what
      would have been "dry-run tests for manual and automated runtime
      modes" back when a `run --dry-run` command existed).
- [ ] Add CLI tests for successful and failing paths.
- [x] Add tests that generate assets for every example config.

## Milestone 2: Runtime Execution Readiness

Milestone 2 used to be framed around implementing Python `ToolAdapter`
subclasses. There is no more Python adapter layer — the implementation
surface for everything below is now `renderers/scripts.py`'s
`_render_template_script` (which produces the generated
`scripts/run-<tool_type>.sh`), not a runtime module. JMeter's generated
script is already real and complete (`[x]`, see the Recommended
Implementation Order list below) — the remaining work here is entirely
BlazeMeter and LoadRunner Professional.

### 1. Fill In the BlazeMeter Script Template

Goals:

- Make the generated `scripts/run-blazemeter.sh` actually run BlazeMeter
  tests, in place of its current `# TODO`/`exit 1`.

Tasks:

- Implement API authentication in the generated script (or in a small
  helper it sources).
- Resolve workspace, project, and test identifiers (the script already has
  `base_url`/`workspace_id`/`project_id` filled in as variables).
- Start a test run.
- Poll run status.
- Handle timeouts.
- Download reports and artifacts into `run-output/`.
- Produce a normalized result output (see task 4 below).
- Add tests that exercise the generated script against a mocked/fake
  BlazeMeter API.
- Document required secrets and network access.

### 2. Define LoadRunner Execution Strategy

Goals:

- Establish the correct enterprise-safe path for controlling LoadRunner
  Professional from the generated `scripts/run-loadrunner_professional.sh`.

Open decision:

- How should the generated script trigger LoadRunner Professional?

Options:

- WinRM to a Windows controller.
- SSH to a Windows host.
- A dedicated Jenkins or Azure agent on the controller network.
- A controller-side wrapper script.
- Existing customer orchestration tooling.

Tasks:

- Choose the supported execution mechanism.
- Define required credentials and network prerequisites.
- Implement controller connectivity checks in the generated script (the
  script already has `controller_host`/`controller_results_path`/`domain`/
  `project` filled in as variables).
- Start scenarios remotely.
- Poll scenario completion.
- Collect results from the controller results path into `run-output/`.
- Normalize success, failure, timeout, and partial artifact states.

### 3. Implement Real Pre-Run Checks

Goals:

- Fail early when a run cannot succeed.
- Keep existing config semantics stable while clarifying which actions happen
  before execution and which happen after execution.

Tasks:

- [x] `verify_scenario_exists` is implemented for JMeter (the generated
  script checks the test plan file exists before running).
- Implement `verify_controller_access` in the generated LoadRunner
  Professional script (currently a `# TODO precheck: ...` comment only).
- Implement `verify_scenario_exists` for BlazeMeter/LoadRunner Professional
  (currently a `# TODO precheck: ...` comment only).
- Implement `verify_load_generators_connected` in the generated LoadRunner
  Professional script (currently a `# TODO precheck: ...` comment only).
- Preserve compatibility for the existing `collect_results` value, but clarify
  whether it represents a pre-run artifact readiness check or migrate it into a
  future `post_run_steps` section.
- Have each check produce a clear pass/fail message and exit code from the
  script, rather than only a `# TODO` comment.

### 4. Normalize Runtime Output

Goals:

- Give CI/CD systems stable artifacts and summaries from every generated
  script, once BlazeMeter/LoadRunner Professional execution is real.

Tasks:

- Define a summary file each generated script writes to `run-output/` after
  running (e.g. `run-output/summary.json`) — JMeter's script does not write
  one yet either, since it just calls `jmeter` and lets it fill
  `run-output/` directly.
- Include timestamps, duration, run ID, report link, status, environment,
  scenario, and artifact status in that summary.
- Keep the format the same across all three tools' generated scripts.
- Ensure every generated script writes to `run-output/` (already true
  today) rather than anywhere configurable per-invocation.

## Recommended Implementation Order

- [x] 1. Fix README/schema mismatch.
- [x] 2. Add development dependencies and make tests easy to run.
- [x] 3. Add CI for the generator project (GitHub Actions, path-scoped to
      this project, matrix over Python 3.9/3.12).
- [x] 4. Make production-ready generation stricter while preserving explicit
      draft generation (done via the `incomplete` flag, not a new CLI flag).
- [x] 5. Improve CLI error handling (`wizard` catches its expected
      exceptions and prints clean messages instead of tracebacks; `generate`
      has no exception paths beyond what validation already catches. `run`
      no longer exists as a CLI command — bad input to the generated script
      is now handled by the script itself with plain one-line messages).
- [x] 6. Add renderer tests and YAML validation (all three renderers —
      GitHub Actions, Azure DevOps, Jenkins — now have a test that parses
      the generated YAML/asserts the generated Groovy's key values).
- [x] 7. Harden GitHub Actions rendering (safe YAML quoting via
      `renderers/quoting.py`, job-id sanitization, safe filenames, shell
      quoting for CLI args, and `env:`-indirection for the runtime
      `workflow_dispatch` input values — see "Renderer Output Uses
      Handwritten YAML Strings" below).
- [x] 8. Harden Azure DevOps rendering (same treatment as GitHub Actions).
      Jenkins received the same treatment separately (not one of the
      original 14 items, since Jenkins support was added afterward).
- [ ] 9. Improve generated README content.
- [x] 10. Replace the Python runtime/adapter subsystem with a generated
      `scripts/run-<tool_type>.sh` per setup, real for JMeter (local
      subprocess call — needed no remote API or credentials, as predicted)
      and a filled-in-but-TODO template for BlazeMeter/LoadRunner
      Professional (see `docs/superpowers/plans/
      2026-09-08-generator-only-tool-scripts.md` for how this was done).
- [ ] 11. Fill in the real API call in the generated
      `run-blazemeter.sh` template.
- [ ] 12. Decide the LoadRunner Professional remote-execution strategy and
      fill in the real controller call in the generated
      `run-loadrunner_professional.sh` template.
- [ ] 13. Replace the remaining `# TODO precheck: ...` comments in the
      BlazeMeter/LoadRunner Professional templates with real checks.
- [ ] 14. Add tests that exercise the generated scripts against
      mocked/fake remote systems.
- [ ] 15. Publish an internal release candidate.

## Definition of Ready

The generator can be considered ready for generating customer pipeline packages
when:

- All example configs validate successfully.
- Invalid configs fail with clear messages.
- Generated GitHub Actions YAML is syntactically valid.
- Generated Azure DevOps YAML is syntactically valid.
- Generated README files include enough instructions for handoff.
- Tests cover validation, generation, and the generated
  `scripts/run-<tool_type>.sh` content for every tool.
- CI passes on every change.

The BlazeMeter and LoadRunner Professional generated scripts can be
considered ready for executing tests when:

- At least one of the two can start, monitor, and collect artifacts from a
  remote test run for real (JMeter's generated script already does this).
- Failed runs produce clear summary output.
- Timeout and partial artifact cases are handled.
- Secrets and credentials are documented.
- The generated script's real-execution behavior is covered by automated
  tests using mocks or test doubles.

## Immediate Next Steps

The most valuable next work is to make the generation path reliable before
building deeper runtime behavior.

Recommended first changes:

- [x] 1. Fix the README value for `final_pipeline_destination`.
- [x] 2. Add `dev` dependencies in `pyproject.toml`.
- [x] 3. Add tests for every example config.
- [x] 4. Make `generate` (and `run`) fail on warnings for configs marked
      `incomplete: false`; drafts (`incomplete: true`) remain unaffected.
- [x] 5. Add renderer output tests (all three CI/CD platforms now covered).
- [x] 6. Add clean CLI error handling (`wizard` and `run`; `generate` has no
      exception paths beyond what validation already catches).

These changes would make the project safer to use immediately while preserving
the current architecture for future work filling in the BlazeMeter/LoadRunner
Professional script templates.

(Items 4 and 6 above predate the removal of the `run` CLI command and the
Python `runtime`/`adapters` layers entirely — see "Generated Run Script" and
"BlazeMeter and LoadRunner Professional Scripts Are Templates, Not Adapters"
above for the current model.)
