# Generator-Only Scope: Replace Runtime Execution with Generated Tool Scripts

## Context

`pipeline-generator` currently has two roles: generating CI/CD pipeline
files (`generate`), and acting as a runtime wrapper those generated
pipelines call to actually trigger a performance test (`run`, backed by
`runtime/` and `adapters/`). All three tool adapters (BlazeMeter, LoadRunner
Professional, JMeter) are stubs — `run` without `--dry-run` currently raises
`NotImplementedError`.

Decision: running performance tests is out of scope for this tool entirely.
`pipeline-generator`'s job ends at generation time. The actual test
invocation must be part of what gets *generated* — a real, standalone script
included alongside the CI/CD files — not something the Python CLI does at
pipeline-run time, not even as a stub with `--dry-run`.

## Goals

- Remove every code path where `pipeline-generator` itself contacts a
  remote system or spawns the actual test tool.
- Generate a per-setup script that the CI/CD pipeline calls to run the test.
  For JMeter this script is real and working (JMeter needs no remote
  credentials — it's a local process). For BlazeMeter/LoadRunner
  Professional, the script is a template with connection details already
  filled in and a clearly marked TODO for the actual API/controller call,
  matching today's honest "not implemented, here's where it goes" stance —
  just moved from a Python exception to a shell script.
- Keep the config schema, wizard, and `validate` unchanged — they already
  capture the right information (tool type, connection details, catalog,
  automated jobs); only what happens with that information at `generate`
  time changes.

## Non-Goals

- No `--dry-run`-equivalent at the script level. Dry-run preview was a
  `pipeline-generator run` feature; it goes away with `run`. The generated
  script is short, plain bash — reading it *is* the preview.
- No auto-install of JMeter/Java on the CI runner. Same assumption as
  today: the runner already has what it needs.
- No changes to `validate`, the wizard, or the config schema. This is
  scoped entirely to what `generate` produces and what `run` was.

## Design

### Removed entirely

- `src/pipeline_generator/runtime/` (orchestrator.py, prechecks.py,
  summary.py, artifacts.py, main.py)
- `src/pipeline_generator/adapters/` (base.py, blazemeter.py,
  loadrunner_professional.py, jmeter.py)
- The `run` subcommand and its argparse wiring in `cli.py`
- `tests/` files that exist solely to test the above

### New: `renderers/scripts.py`

`generate_assets` (in `generator/service.py`) gains one more renderer call,
alongside the existing CI/CD renderer dispatch:

```python
outputs.extend(render_tool_script(config, package, setup_dir))
```

`render_tool_script` writes exactly one file: `scripts/run-<tool_type>.sh`
(e.g. `scripts/run-jmeter.sh`, `scripts/run-blazemeter.sh`,
`scripts/run-loadrunner_professional.sh` — `tool_type` is an enum value, not
user input, so no sanitization is needed for the filename itself). The file
is written executable (`chmod 0o755`).

**Script interface**, identical across all three tools:

```bash
scripts/run-<tool>.sh --environment <key> --scenario <key>
```

No `--config`/customer.yaml argument — everything the script needs
(connection details, the environment/scenario catalog) is already baked
into its text at generation time. The only thing resolved at *invocation*
time is which catalog entry was selected, because that's the one thing a
manual pipeline run must be able to choose at trigger time.

**Key → identifier resolution.** Every script embeds two resolver
functions generated from `catalog.environments`/`catalog.scenarios`,
using **exact string comparison (`[ "$1" = '...' ]`), not a `case`
statement** — `case` patterns treat `*`, `?`, `[`, `]` as glob
metacharacters, so a catalog key containing one of those characters would
silently match more (or fewer) branches than intended. Exact `[ = ]`
comparison has no such special-character behavior. Every embedded key and
identifier string is escaped via the existing `shell_quote()`
(`shlex.quote`) from `renderers/quoting.py`, the same helper already used
elsewhere to embed arbitrary config values into generated shell text:

```bash
resolve_environment_identifier() {
  if [ "$1" = 'qa' ]; then echo 'env-qa'; return; fi
  if [ "$1" = 'staging' ]; then echo 'env-stg'; return; fi
  echo "Unknown environment key: $1" >&2
  exit 1
}
```

(Same shape for `resolve_scenario_identifier`, generated from
`catalog.scenarios`.)

This one script is used by *both* the manual and automated pipeline steps.
For the manual pipeline, the key comes from a runtime-selected build
parameter (same `env:`/`environment{}`-indirection pattern already in place
for security — see below). For an automated job, the key is simply a fixed
literal in the generated CI step, because the job's `environment_ref`/
`scenario_ref` are already known at generation time — no separate
resolution path or calling convention needed; the script always does its
own key→identifier lookup either way.

**Per-tool script body:**

- **JMeter** (real, not a template): after resolving identifiers, the
  script:
  1. `mkdir -p run-output`
  2. Runs a real precheck: `[ -f 'performance/checkout.jmx' ] || { echo
     "Test plan not found: performance/checkout.jmx" >&2; exit 1; }` — this
     is what `verify_scenario_exists` actually means for a local tool, and
     it's fully checkable without any adapter. If `pre_run_checks` doesn't
     include `verify_scenario_exists`, this check is simply not emitted.
     `verify_controller_access` / `verify_load_generators_connected` have no
     JMeter equivalent (no controller) — never emitted for a JMeter script
     even if enabled in the config, since there's nothing for them to check.
  3. Runs `jmeter -n -t 'performance/checkout.jmx' -l run-output/results.jtl
     -e -o run-output/report ${1+"$@"}` (or similar; exact JMeter flags are
     an implementation detail, not a design decision) — using `jmeter_bin`
     if set, otherwise assuming `jmeter` is on `PATH`.
  4. Exits non-zero if JMeter itself exits non-zero.

- **BlazeMeter / LoadRunner Professional** (template): connection details
  (`base_url`/`workspace_id`/`project_id` or `controller_host`/
  `controller_results_path`/`domain`/`project`) are substituted into
  variables at the top of the script, `pre_run_checks` are emitted as
  commented-out TODO lines (nothing can be verified generically), and the
  script ends with:

  ```bash
  echo "ERROR: BlazeMeter execution is not implemented in this generated script yet." >&2
  echo "Fill in the API call using the variables above." >&2
  exit 1
  ```

  This preserves today's "fails loudly if you forget to implement it"
  behavior — just as generated shell text instead of a Python
  `NotImplementedError`.

### Renderer changes (GitHub Actions / Azure DevOps / Jenkins)

Only the "Run performance wrapper" step's command changes, from
`pipeline-generator run --config customer.yaml --mode ... --environment
"$ENVIRONMENT" ...` to `./scripts/run-<tool>.sh --environment "$ENVIRONMENT"
--scenario "$SCENARIO"` (manual) or `./scripts/run-<tool>.sh --environment
qa --scenario checkout_smoke` (automated, literal values). The existing
`env:`/`environment{}`-block indirection pattern for the manual pipeline's
runtime-selected values is unchanged — it protects the same thing
regardless of what's being called. Everything else generated by these three
renderers (parameters/choices, timeouts, artifact upload/archive steps)
is unchanged; `run-output/` is still what gets uploaded, it's just the new
script that populates it now instead of the old `runtime/artifacts.py`.

### CLI (`cli.py`)

The `run` subcommand and its argparse block are deleted. `wizard`,
`validate`, and `generate` are unchanged.

### Config schema, wizard, validate

**No changes.** `tool.type`/`auth`/`connection`, `catalog`,
`automated_jobs`, `pre_run_checks`, and `artifacts.*` all stay exactly as
they are — they're what `render_tool_script` reads to build the script.
`validate`'s per-tool connection warnings (missing `test_plan_path`, etc.)
are unaffected.

### Testing

- Delete tests that only exist to test `run`/`runtime`/`adapters`.
- Add `tests/test_tool_scripts.py` covering all three tools:
  - JMeter: generated script content includes the resolver functions, the
    real precheck, and the `jmeter` invocation; a script with adversarial
    catalog keys (containing `*`, `'`, spaces) still round-trips correctly
    through the `[ = ]` comparisons (proving the glob-injection concern
    above is actually closed, the same way this session's earlier
    adversarial-input tests proved the YAML/Groovy escaping).
  - BlazeMeter/LoadRunner: generated script includes the substituted
    connection variables and ends with the `exit 1` TODO stub.
  - All three: file is written with the executable bit set.
- Update the three renderer tests (GitHub Actions/Azure/Jenkins) to assert
  the new `./scripts/run-<tool>.sh` invocation instead of
  `pipeline-generator run`.
- `tests/test_example_configs.py` continues to work unchanged (it only
  calls `generate_assets`, doesn't care what's inside the output).

### Documentation

Needs updates as part of implementation, not this spec: README.md,
`CLAUDE.md`, `docs/pipeline-generator-user-guide.md`, and
`docs/current-state-and-readiness-plan.md` all currently describe `run`,
`--dry-run`, and the adapter stubs as core features — all of that framing
changes to "the generated script is what runs the test," and the
readiness plan's Milestone 2 (BlazeMeter/LoadRunner/JMeter adapter
implementation) gets reframed around finishing the generated *script*
templates instead of Python adapter classes.
