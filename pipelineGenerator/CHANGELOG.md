# Changelog

All notable changes to `pipeline-generator` are documented here.

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
