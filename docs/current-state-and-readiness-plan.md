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
- Generated setup README.
- Runtime dry-run path.
- Adapter interfaces for performance testing tools.
- Stub adapters for BlazeMeter and LoadRunner Professional.
- Example customer configs for the supported CI/CD and tool combinations.
- Minimal pytest-based tests.

Not implemented yet:

- Real BlazeMeter API integration.
- Real LoadRunner Professional remote execution.
- Real pre-run checks.
- Robust generated YAML escaping and validation.
- Strong schema enforcement.
- Comprehensive automated test coverage.
- CI for the generator project itself.

## Supported Platforms and Tools

### CI/CD Platforms

The generator currently supports:

- `github_actions`
- `azure_devops`

Renderer output locations:

- GitHub Actions files are written under `.github/workflows/`.
- Azure DevOps files are written under `azure/`.

### Performance Testing Tools

The config model currently supports:

- `blazemeter`
- `loadrunner_professional`

Tool adapters exist, but both are stubs. They define the expected execution
interface and raise `NotImplementedError` for real remote execution.

### Authentication Types

Supported auth type values are:

- `api_token`
- `username_password`
- `service_account`
- `network_vpn_manual_setup`

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

Converts the generic pipeline model into CI/CD-specific YAML files for GitHub
Actions and Azure DevOps.

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

Current behavior: generation stops only on validation errors. Warning-only
configs can still generate files.

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

The repository includes four example customer configs:

- `examples/github-blazemeter/customer.yaml`
- `examples/github-loadrunner/customer.yaml`
- `examples/azure-blazemeter/customer.yaml`
- `examples/azure-loadrunner/customer.yaml`

These examples demonstrate the intended matrix of supported CI/CD platforms and
performance tools.

## Known Gaps and Risks

### Validation Is Too Permissive for Generation

Validation distinguishes errors from warnings. The `generate` command only
blocks on errors, so warning-only configs may still generate incomplete or
broken pipeline files.

Risk:

- Empty environment or scenario dropdowns.
- Automated jobs that reference missing catalog entries.
- Generated packages that look complete but fail at runtime.

Recommended change:

- Make `generate` strict by default, or add explicit `--allow-warnings` /
  `--allow-incomplete` flags.

### Runtime Errors Are Not User-Friendly

Some runtime request errors are raised as `ValueError`. The CLI does not catch
them and convert them into clean command-line output.

Risk:

- Users see Python tracebacks for normal input mistakes.

Recommended change:

- Catch expected exceptions in the CLI, print concise errors, and return
  nonzero exit codes.

### README and Schema Are Slightly Out of Sync

The README example uses `customer_repo` for `final_pipeline_destination`, but
the schema supports `stay_in_central_repo` and `copy_to_customer_repo`.

Risk:

- Users copy an invalid value from documentation.

Recommended change:

- Update README to use `copy_to_customer_repo`.

### Renderer Output Uses Handwritten YAML Strings

Renderers currently build YAML through f-strings.

Risk:

- Unescaped names, special characters, or unsupported identifiers can create
  invalid CI/CD YAML.

Recommended change:

- Add safe quoting, identifier normalization, and generated YAML syntax tests.

### Adapter Implementations Are Stubs

BlazeMeter and LoadRunner Professional adapters define the right shape but do
not execute real tests.

Risk:

- The generated pipelines can call `pipeline-generator run`, but real execution
  will fail unless `--dry-run` is used.

Recommended change:

- Implement adapters incrementally, starting with BlazeMeter because it is
  likely API-driven and easier to automate consistently.

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

Tasks:

- Validate `setup.final_pipeline_destination` against supported values.
- Validate `setup.working_location` against supported values.
- Validate automated job references as errors for complete configs.
- Validate manual pipeline catalog requirements as errors when manual generation
  is enabled.
- Validate timeout values as positive integers.
- Validate job names for CI/CD compatibility.
- Validate environment and scenario keys for uniqueness.
- Decide whether `incomplete: true` configs can be generated.
- Add CLI flags for strictness, such as `--strict` or `--allow-incomplete`.

### 2. Formalize the Schema

Goals:

- Make the config contract explicit and easier to evolve.

Tasks:

- Introduce typed config models or a JSON Schema.
- Document every field, type, allowed value, and default.
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

- Add a development dependency group for test tooling.
- Run tests with `pytest`.
- Add GitHub Actions or Azure DevOps CI for this repository.
- Test supported Python versions.
- Add validation tests for valid and invalid configs.
- Add renderer tests for GitHub Actions and Azure DevOps.
- Add dry-run tests for manual and automated runtime modes.
- Add CLI tests for successful and failing paths.
- Add tests that generate assets for every example config.

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

Tasks:

- Implement `verify_controller_access`.
- Implement `verify_scenario_exists`.
- Implement `verify_load_generators_connected`.
- Reconsider `collect_results`; it may belong after execution rather than
  before execution.
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

1. Fix README/schema mismatch.
2. Add development dependencies and make tests easy to run.
3. Add CI for the generator project.
4. Make validation stricter for generation.
5. Improve CLI error handling.
6. Add renderer tests and YAML validation.
7. Harden GitHub Actions rendering.
8. Harden Azure DevOps rendering.
9. Improve generated README content.
10. Implement BlazeMeter adapter.
11. Decide and implement LoadRunner execution strategy.
12. Replace precheck stubs with real checks.
13. Add runtime integration tests with mocked remote systems.
14. Publish an internal release candidate.

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

1. Fix the README value for `final_pipeline_destination`.
2. Add `dev` dependencies in `pyproject.toml`.
3. Add tests for every example config.
4. Make `generate` fail on warnings unless explicitly overridden.
5. Add renderer output tests.
6. Add clean CLI error handling.

These changes would make the project safer to use immediately while preserving
the current architecture for future adapter work.
