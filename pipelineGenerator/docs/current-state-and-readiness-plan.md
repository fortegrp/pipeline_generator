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
packages. Runtime execution is present as an architectural skeleton, but real
remote execution against BlazeMeter and LoadRunner Professional has not yet been
implemented.

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
- Runtime dry-run path.
- Adapter interfaces for performance testing tools.
- Stub adapters for BlazeMeter, LoadRunner Professional, and JMeter.
- Example customer configs for the supported CI/CD and tool combinations.
- Renderer tests for all three CI/CD platforms (GitHub Actions and Azure
  DevOps tests also parse the generated YAML to catch syntax breakage).
- A test that validates and generates every example config.
- Clean CLI error handling for `wizard` and `run` (expected exceptions are
  caught and printed as plain messages instead of tracebacks).
- CI (GitHub Actions, `.github/workflows/pipeline-generator-ci.yml` at the
  repo root) running `pytest` on push/PR across Python 3.9 and 3.12.

Not implemented yet:

- Real BlazeMeter API integration.
- Real LoadRunner Professional remote execution.
- Real pre-run checks.
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

Tool adapters exist, but all three are stubs. They define the expected
execution interface and raise `NotImplementedError`. For BlazeMeter and
LoadRunner Professional this means real *remote* execution; for JMeter it
means a real *local* `jmeter` subprocess invocation, which — unlike the other
two — needs no remote API or credentials to implement, making it the
lowest-effort adapter to finish for real.

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
      adapters/
      config/
      generator/
      renderers/
      runtime/
      wizard/
  tests/
```

### Key Modules

`src/pipeline_generator/cli.py`

Defines the command-line interface. The CLI exposes four commands:

- `wizard`
- `validate`
- `generate`
- `run`

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
Actions, Azure DevOps, and Jenkins.

`src/pipeline_generator/runtime/`

Builds run requests and coordinates execution through a tool adapter. In
dry-run mode, it writes an execution plan without contacting remote systems.

`src/pipeline_generator/adapters/`

Defines the adapter protocol and current tool adapter stubs. This is where real
BlazeMeter and LoadRunner execution logic should be implemented.

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
- A generated setup README.

Current behavior: generation always stops on validation errors. Whether it
also stops on warnings now depends on the config's own `incomplete` flag:
warning-only configs with `incomplete: true` (drafts) still generate, while
`incomplete: false` configs (declared ready) are blocked by the same
warnings, with a message pointing at the fix or at flipping the flag back.
This reuses the config's own declared intent instead of adding a separate
`--allow-incomplete`/`--allow-warnings` flag.

### Run

Manual dry run:

```bash
pipeline-generator run \
  --config setups/acme.yaml \
  --mode manual \
  --environment qa \
  --scenario checkout_smoke \
  --dry-run
```

Automated dry run:

```bash
pipeline-generator run \
  --config setups/acme.yaml \
  --mode automated \
  --job post-deploy-smoke \
  --dry-run
```

Current behavior: dry-run mode writes `run-output/execution-plan.json`. Non-dry
execution calls the selected adapter, but the adapters are not implemented yet.
The same `incomplete`-flag-based warning check described under `generate`
applies here too, before either path runs.

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
7. Write a generated README.
8. Copy the final `customer.yaml` into the generated setup package.

The generic model currently includes:

- Setup ID.
- CI/CD type.
- Optional manual pipeline spec.
- Automated job specs.
- Pipeline inputs for environments and scenarios.
- Runtime command arguments.

This design is useful because it keeps CI/CD-specific rendering separate from
the customer config shape.

## Runtime Flow

The runtime flow is:

1. Load and validate config.
2. Select a tool adapter based on `tool.type`.
3. Build a run request.
4. Create `run-output/`.
5. If `--dry-run` is set, write an execution plan and stop.
6. If real execution is requested:
   - run adapter prechecks,
   - start the remote run,
   - wait for completion,
   - collect artifacts,
   - write a summary.

The intended adapter interface is:

- `run_prechecks(config, request)`
- `start_run(config, request)`
- `wait_for_completion(config, handle, timeout_minutes)`
- `collect_artifacts(config, result, output_dir)`

Current limitation: both real adapters raise `NotImplementedError` for start,
wait, and artifact collection.

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
adding a new CLI flag: `generate`/`run` still only block on errors when
`incomplete: true` (drafts stay exactly as permissive as before), but block on
warnings too once a config declares `incomplete: false` — treating that flag
as an enforced promise rather than a label with no effect. `validate` itself
is unchanged and only escalates warnings when `--strict` is passed.

### Runtime Errors Are Not User-Friendly

Some runtime request errors are raised as `ValueError`. The CLI does not catch
them and convert them into clean command-line output.

Risk:

- Users see Python tracebacks for normal input mistakes.

Recommended change:

- Catch expected exceptions in the CLI, print concise errors, and return
  nonzero exit codes.

### README and Schema Are Slightly Out of Sync — Resolved

The README example used `customer_repo` for `final_pipeline_destination`,
which isn't a valid value (the schema only accepts `stay_in_central_repo` or
`copy_to_customer_repo`). Fixed to use `copy_to_customer_repo`.

### Renderer Output Uses Handwritten YAML Strings — Partially Resolved

Renderers build output through f-strings, which used to embed user-controlled
values (job names, pipeline names, environment/scenario values) completely
unescaped — a stray `"`, `:`, or shell metacharacter in any of those could
produce invalid YAML or, worse, get interpreted literally inside a shell
`run:`/`script:` step.

GitHub Actions and Azure DevOps renderers now route every embedded value
through `renderers/quoting.py`: `yaml_dquote()` (JSON-string escaping, a
valid subset of YAML double-quoted scalar syntax) for values that land inside
YAML, `shell_quote()` (`shlex.quote`) for values that land inside a shell
command, and `safe_filename_component()`/per-platform job-id sanitizers so a
hostile job name can't produce a path-traversing filename or an invalid job
identifier. Covered by adversarial-input tests
(`test_render_github_actions_escapes_adversarial_values`,
`test_render_azure_devops_escapes_adversarial_values`) that feed in values
containing quotes, colons, semicolons, spaces, and `../` sequences and assert
the output still parses as valid YAML with the values round-tripping intact.

Still open:

- The Jenkins renderer (added after this plan was written) has not received
  the same treatment — its Groovy string interpolation is still raw f-string
  substitution.
- The GitHub Actions `${{ github.event.inputs.* }}` and Azure DevOps
  `${{ parameters.* }}` expressions in the `run:`/`script:` steps are
  resolved by the platform via compile-time text substitution, which is a
  known injection vector on both platforms if the substituted value isn't
  constrained. Today it's constrained to the declared `choice`/`values` list
  we render (itself now safely quoted), so this is a defense-in-depth gap
  rather than an active hole, but the fully-hardened version would swap to
  runtime variable interpolation (`$(parameters.x)` / an `env:` indirection)
  instead of compile-time template expressions.

### Adapter Implementations Are Stubs

BlazeMeter, LoadRunner Professional, and JMeter adapters define the right
shape but do not execute real tests.

Risk:

- The generated pipelines can call `pipeline-generator run`, but real execution
  will fail unless `--dry-run` is used.

Recommended change:

- Implement adapters incrementally. JMeter is the lowest-effort of the three
  to make real, since it only needs a local subprocess call
  (`jmeter -n -t <plan> -l <results> -e -o <report>`) rather than a remote
  API or controller — no credentials, polling, or network reliability
  concerns. BlazeMeter is next, since it's API-driven. LoadRunner
  Professional remains the most involved, since it also requires deciding
  the remote-execution mechanism (see Milestone 2 below).

### Test Coverage Is Minimal

Current tests cover only:

- Setup ID slug generation.
- Base config validation warnings.

Risk:

- Renderer regressions, CLI regressions, and config edge cases can go unnoticed.

Recommended change:

- Add tests around validation, generation output, runtime dry-runs, and CLI exit
  behavior.

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
- Return stable nonzero exit codes for validation and runtime input failures.
- Add `--version`.
- Add `--output-dir` for runtime output.
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
- [ ] Add dry-run tests for manual and automated runtime modes.
- [ ] Add CLI tests for successful and failing paths.
- [x] Add tests that generate assets for every example config.

## Milestone 2: Runtime Execution Readiness

### 1. Implement BlazeMeter Adapter

Goals:

- Run BlazeMeter tests from generated pipelines.

Tasks:

- Implement API authentication.
- Resolve workspace, project, and test identifiers.
- Start a test run.
- Poll run status.
- Handle timeouts.
- Download reports and artifacts.
- Produce a normalized result payload.
- Add integration-test seams with mocked API responses.
- Document required secrets and network access.

### 2. Define LoadRunner Execution Strategy

Goals:

- Establish the correct enterprise-safe path for controlling LoadRunner
  Professional.

Open decision:

- How should the generator trigger LoadRunner Professional?

Options:

- WinRM to a Windows controller.
- SSH to a Windows host.
- A dedicated Jenkins or Azure agent on the controller network.
- A controller-side wrapper script.
- Existing customer orchestration tooling.

Tasks:

- Choose the supported execution mechanism.
- Define required credentials and network prerequisites.
- Implement controller connectivity checks.
- Start scenarios remotely.
- Poll scenario completion.
- Collect results from the controller results path.
- Normalize success, failure, timeout, and partial artifact states.

### 3. Implement Real Pre-Run Checks

Goals:

- Fail early when a run cannot succeed.
- Keep existing config semantics stable while clarifying which actions happen
  before execution and which happen after execution.

Tasks:

- Implement `verify_controller_access`.
- Implement `verify_scenario_exists`.
- Implement `verify_load_generators_connected`.
- Preserve compatibility for the existing `collect_results` value, but clarify
  whether it represents a pre-run artifact readiness check or migrate it into a
  future `post_run_steps` section.
- Return structured check statuses: `passed`, `failed`, `warning`, `skipped`.
- Let config decide whether failed checks block execution.

### 4. Normalize Runtime Output

Goals:

- Give CI/CD systems stable artifacts and summaries.

Tasks:

- Define `execution-plan.json`.
- Define `summary.json`.
- Define adapter result schema.
- Include timestamps, duration, run ID, report link, status, environment,
  scenario, and artifact status.
- Ensure all runtime outputs are written under a configurable output directory.

## Recommended Implementation Order

- [x] 1. Fix README/schema mismatch.
- [x] 2. Add development dependencies and make tests easy to run.
- [x] 3. Add CI for the generator project (GitHub Actions, path-scoped to
      this project, matrix over Python 3.9/3.12).
- [x] 4. Make production-ready generation stricter while preserving explicit
      draft generation (done via the `incomplete` flag, not a new CLI flag).
- [x] 5. Improve CLI error handling (`wizard` and `run` now catch their
      expected exceptions and print clean messages instead of tracebacks;
      `generate` has no exception paths beyond what validation already
      catches).
- [x] 6. Add renderer tests and YAML validation (all three renderers —
      GitHub Actions, Azure DevOps, Jenkins — now have a test that parses
      the generated YAML/asserts the generated Groovy's key values).
- [x] 7. Harden GitHub Actions rendering (safe YAML quoting via
      `renderers/quoting.py`, job-id sanitization, safe filenames, shell
      quoting for CLI args — see "Renderer Output Uses Handwritten YAML
      Strings" below for what's still open).
- [x] 8. Harden Azure DevOps rendering (same treatment as GitHub Actions).
- [ ] 9. Improve generated README content.
- [ ] 10. Implement JMeter adapter (local subprocess call — lowest effort of
      the three since it needs no remote API or credentials).
- [ ] 11. Implement BlazeMeter adapter.
- [ ] 12. Decide and implement LoadRunner execution strategy.
- [ ] 13. Replace precheck stubs with real checks.
- [ ] 14. Add runtime integration tests with mocked remote systems.
- [ ] 15. Publish an internal release candidate.

## Definition of Ready

The generator can be considered ready for generating customer pipeline packages
when:

- All example configs validate successfully.
- Invalid configs fail with clear messages.
- Generated GitHub Actions YAML is syntactically valid.
- Generated Azure DevOps YAML is syntactically valid.
- Generated README files include enough instructions for handoff.
- Tests cover validation, generation, and dry-run behavior.
- CI passes on every change.

The runtime can be considered ready for executing tests when:

- At least one real adapter can start, monitor, and collect artifacts from a
  remote test run.
- Failed runs produce clear summary output.
- Timeout and partial artifact cases are handled.
- Secrets and credentials are documented.
- Runtime behavior is covered by automated tests using mocks or test doubles.

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
the current architecture for future adapter work.
