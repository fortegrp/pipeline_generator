# Pipeline Generator — User Guide

This is a complete, practical guide to using `pipeline-generator`: onboarding
a customer's performance testing setup, generating the CI/CD pipeline files
they'll run, and understanding every option along the way. It assumes no
prior familiarity with the tool's internals — for architecture notes aimed
at people modifying the code, see `CLAUDE.md`; for the roadmap and known
gaps, see `docs/current-state-and-readiness-plan.md`.

## 1. What This Tool Is For

A performance engineer onboarding a new customer typically needs to answer
the same set of questions every time: which CI/CD platform does the customer
use, which performance testing tool, what environments and test scenarios
exist, should the pipeline be manual (triggered by hand) or automated
(wired into deployments), and so on. `pipeline-generator` turns those answers
into one YAML file (`customer.yaml`) and then turns that file into real,
ready-to-commit pipeline definitions for the customer's CI/CD platform.

The mental model has three moving parts, plus one file `generate` writes
that isn't a `pipeline-generator` command at all:

```
   wizard                validate              generate            scripts/run-<tool>.sh
(interactive)   →    (check for       →    (write CI/CD      →    (what the generated
 creates/edits        problems)              files, README,         pipeline calls to
 customer.yaml                               and the script)        actually run a test)
```

- **`customer.yaml`** is the single source of truth for one customer setup.
  Everything else is derived from it.
- **`wizard`** is the friendliest way to create or edit that file, but it's
  optional — you can hand-write or hand-edit the YAML directly.
- **`validate`** checks a config for problems without touching the
  filesystem otherwise.
- **`generate`** turns a config into an actual folder of CI/CD files (a
  GitHub Actions workflow, an Azure Pipelines YAML file, or a Jenkinsfile),
  a README, and a `scripts/run-<tool>.sh`, ready to hand to the customer or
  commit into their repo. This is the tool's last step —
  `pipeline-generator` never triggers or contacts a performance test itself;
  it has no code that talks to GitHub, Azure DevOps, Jenkins, BlazeMeter, or
  a LoadRunner controller.
- **`scripts/run-<tool>.sh`** is the one real step every generated pipeline
  calls to do its work (e.g. `./scripts/run-jmeter.sh --environment "$ENV"
  --scenario "$SCENARIO"`). It's a plain bash script with no dependency on
  `pipeline-generator` or Python at all, so it runs the same way whether the
  CI/CD platform's job that calls it happens to have this tool installed or
  not. All three tools are real and complete: JMeter and LoadRunner
  Professional resolve the environment/scenario to their catalog
  identifiers and run `jmeter`/`wlrun` directly; BlazeMeter authenticates
  and drives BlazeMeter's own REST API (section 10 has the details for all
  three, including two known limitations neither LoadRunner nor BlazeMeter
  has fully closed yet). You can also run any of them by hand from a
  checkout of the generated setup, without going through the CI/CD
  platform, to test before committing anything.

## 2. Prerequisites and Installation

Requires Python 3.9+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

If your environment has an older `pip`:

```bash
pip install --no-build-isolation -e .
```

This installs the `pipeline-generator` command into your virtualenv. Confirm
it worked:

```bash
pipeline-generator --help
```

You should see three subcommands: `wizard`, `validate`, `generate`.

(If you're going to run the test suite or otherwise develop on the tool
itself rather than just use it, install the `dev` extra instead:
`pip install -e ".[dev]"`, which additionally installs `pytest`.)

## 3. Quick Start

The fastest path from nothing to a generated pipeline:

```bash
# 1. Answer questions interactively; produces setups/acme.yaml
pipeline-generator wizard --output setups/acme.yaml

# 2. Sanity-check the result (the wizard already does this at the end, but
#    you can re-run it any time, e.g. after hand-editing the YAML)
pipeline-generator validate --config setups/acme.yaml

# 3. Turn it into real CI/CD files, plus a scripts/run-<tool>.sh
pipeline-generator generate --config setups/acme.yaml --output-dir generated
```

After step 3, `generated/<setup-id>/` contains everything you'd commit into
(or hand off to) the customer's repository, including a `scripts/run-<tool>.sh`
you can try locally before handing anything off. Section 9 covers exactly
what gets written for each CI/CD platform.

## 4. The Interactive Wizard

`pipeline-generator wizard --output <path>` is the recommended way to create
or edit a `customer.yaml`. It's organized into eight numbered sections,
prints one-line hints on the choices whose implications aren't obvious, and
finishes by showing you a summary plus the same check `validate` would run.

**Two important safety behaviors before you start:**

- **It will not silently overwrite an existing file.** If `--output` already
  points at a file, you must pass `--resume` to touch it; otherwise the
  wizard refuses immediately with a message telling you so. Point `--output`
  at a new path to start a genuinely new setup instead.
- **Cancelling is safe.** Pressing Ctrl-C or hitting end-of-input exits
  cleanly with a message telling you whether any progress was saved — never
  a raw crash.

### Step 1 — Setup basics

| Prompt | What it means |
|---|---|
| `Working location` (`central_repo` / `customer_repo`) | Where the *setup files themselves* (this YAML, eventually the generated pipeline files) are authored: in this generator's own central repo, or directly inside the customer's repository. |
| `Final pipeline destination` (`stay_in_central_repo` / `copy_to_customer_repo`) | Where the *generated* pipeline files end up living long-term. |
| `Can the CI/CD system consume files directly from the central repo?` | If yes, the customer's CI/CD can reference the generated files in place, without them being copied anywhere. |
| `Target repository identity` | Free text identifying the customer's repo, e.g. `github.com/acme/storefront`. Used later to auto-suggest a setup ID. |
| `Generation mode` (`manual_only` / `automated_only` / `both`) | Whether to generate the on-demand manual pipeline, the reusable automated job, or both. |

### Step 2 — CI/CD platform and performance tool

Three prompts, each a numbered menu:

- **CI/CD platform**: `github_actions`, `azure_devops`, or `jenkins`.
- **Performance tool**: `loadrunner_professional`, `blazemeter`, or `jmeter`.
- **Authentication option**: `api_token`, `username_password`,
  `service_account`, `network_vpn_manual_setup`, or `none`. (`none` is
  meant for JMeter, which runs locally and needs no remote credentials —
  see section 10.)

### Step 3 — Setup identifier

The wizard suggests a setup ID by slugifying
`<cicd-platform>-<tool>-<repo-name>` (e.g.
`github-actions-loadrunner-professional-storefront`). This ID becomes the
name of the folder `generate` creates, so accepting the suggestion (just
press Enter) is usually the right move. You can type your own instead — it
will be automatically made filesystem-safe when `generate` runs, regardless
of what you type here.

### Step 4 — Tool connection details

Depends on which tool you picked in Step 2:

**LoadRunner Professional:**

| Field | Notes |
|---|---|
| `wlrun_path` | Optional — path to the `wlrun` executable; blank uses `PATH`. Assumes the CI job runs on an agent co-located with the LoadRunner Controller (see section 10). |

Catalog scenario entries for LoadRunner Professional use a full `.lrs`
scenario file path as their `identifier` (one entry per environment/
scenario combination), rather than a remote name — see section 10 for why.

**BlazeMeter:**

| Field | Notes |
|---|---|
| `base_url` | Defaults to `https://a.blazemeter.com`. Required. |
| `workspace_id` | Required. |
| `project_id` | Required. |

**JMeter:**

| Field | Notes |
|---|---|
| `test_plan_path` | Required — path to the `.jmx` test plan inside the target repository, e.g. `performance/checkout.jmx`. |
| `jmeter_bin` | Optional — path to the `jmeter` executable if it isn't on `PATH`. |

### Step 5 — Manual pipeline

Only asked if Step 1's generation mode included the manual pipeline
(`manual_only` or `both`):

- `Generate manual pipeline?` (yes/no)
- `Manual pipeline name` — becomes the pipeline's display name.
- `Manual pipeline timeout minutes` — must be a positive whole number;
  invalid input re-prompts rather than silently falling back to a default.

### Step 6 — Environments and scenarios

For a brand-new config, you're asked "Add environments now?" / "Add
scenarios now?" (yes/no); saying no leaves the catalog empty for now (fine
for a draft — see section 6).

**If you're resuming a draft that already has entries**, the wizard shows
what's there and asks what to do:

```
Existing environments: qa, staging
What do you want to do with environments?
  1. keep as-is (default)
  2. add more
  3. start over
```

"Add more" appends to the existing list without making you retype it;
"start over" discards it and starts fresh. This is deliberate — earlier
versions of this flow made "yes, edit this" silently wipe the existing list,
which was a real problem for any catalog with more than a couple of entries.

Each environment/scenario entry has three fields: a `key` (used
programmatically, e.g. as a dropdown value and in automated job
references), a `name` (display label), and a `remote identifier` (the
tool-side name/ID, e.g. a LoadRunner scenario ID or a JMeter thread group
name — defaults to a `TODO` placeholder if you don't have it yet).

### Step 7 — Automated jobs

Only asked if generation mode included automated jobs (`automated_only` or
`both`). Same keep-as-is/add-more/start-over pattern as Step 6 when
resuming. For each new job you enter:

- **Job name** (blank to stop adding jobs)
- **Environment key** and **Scenario key** — if you already have catalog
  entries from Step 6, these are presented as a numbered choice from that
  catalog (not free text), so a job can't accidentally reference an
  environment/scenario that doesn't exist.
- **Timeout minutes** — same positive-integer prompt as Step 5.

### Step 8 — Pre-run checks

One screen listing the checks applicable to whichever tool you picked in
Step 2 — JMeter sees 2 (`verify_scenario_exists`, `collect_results`);
LoadRunner Professional sees 4 (`verify_controller_access`,
`verify_scenario_exists`, `verify_load_generators_connected`,
`collect_results`); BlazeMeter sees 4 different ones
(`verify_host_reachable`, `verify_project_exists`, `verify_scenario_exists`,
`collect_results`) — BlazeMeter's real failure modes don't match
LoadRunner's controller-flavored vocabulary, so it gets its own. Type
comma-separated numbers to select specific ones, `all`, `none`, or just
press Enter to keep whatever was already enabled (useful when resuming).

### After Step 8

The wizard prints a plain-language summary (setup ID, CI/CD, tool, target
repo, whether the manual pipeline is enabled, and counts of environments/
scenarios/automated jobs), then runs the same check `validate` would and
prints the result — so you see any outstanding warnings immediately, in the
same terminal session, without a separate command.

## 5. Understanding `customer.yaml`

Full annotated example (`incomplete: false`, i.e. a finished, ready-to-hand-off
setup):

```yaml
version: 1
incomplete: false                 # false = "this is done"; see section 6

setup:
  id: acme-github-actions-loadrunner-professional-storefront
  working_location: central_repo               # central_repo | customer_repo
  final_pipeline_destination: copy_to_customer_repo  # stay_in_central_repo | copy_to_customer_repo
  ci_can_use_central_repo_directly: false
  target_repository: github.com/acme/storefront
  generation_mode: both                          # manual_only | automated_only | both

cicd:
  type: github_actions            # github_actions | azure_devops | jenkins

tool:
  type: loadrunner_professional   # loadrunner_professional | blazemeter | jmeter
  auth:
    type: none                    # api_token | username_password | service_account
                                   # | network_vpn_manual_setup | none
  connection:
    wlrun_path: wlrun              # optional; blank/absent defaults to "wlrun" on PATH

manual_pipeline:
  enabled: true
  name: Performance Manual Run
  timeout_minutes: 240

automated_jobs:
  - name: post-deploy-smoke
    enabled: true
    environment_ref: qa              # must match a catalog.environments[].key
    scenario_ref: checkout_smoke_qa  # must match a catalog.scenarios[].key
    timeout_minutes: 90

catalog:
  environments:
    - key: qa
      name: QA
      identifier: QA
  scenarios:
    - key: checkout_smoke_qa
      name: Checkout Smoke (QA)
      identifier: C:\Scenarios\checkout_smoke_qa.lrs

pre_run_checks:
  - verify_controller_access
  - verify_scenario_exists
  - verify_load_generators_connected
  - collect_results

artifacts:
  download_remote_results: true
  fail_on_partial_download: false

readme:
  include_manual_usage: true
  include_automated_usage: true
```

You will rarely need to hand-write this from scratch — the wizard builds it
for you — but hand-editing an existing file (to add one automated job, fix a
typo, adjust a timeout) is completely normal and supported. `validate` and
`generate` both re-read the file from disk every time, so there's no state
to get out of sync.

Nine ready-made example configs covering every CI/CD × tool combination
live under [`examples/`](../examples/) in this repo — copy one as a
starting point if you'd rather edit YAML directly than run the wizard.

## 6. Draft vs. Complete Setups — the `incomplete` Flag

This is the single most important behavioral rule to understand, because it
changes what `generate` will let you do.

`validate` (and the checks the wizard runs at the end) classify every
problem it finds as either an **error** or a **warning**:

- **Errors** are things that are simply invalid regardless of context — an
  unsupported `cicd.type`, `tool.type`, or `auth.type` value. These always
  block `generate`, no matter what.
- **Warnings** are things that are fine for a draft but would be a problem
  for a finished setup — a missing connection field, an empty catalog, an
  automated job pointing at an environment/scenario that doesn't exist yet.

What happens with warnings depends on the config's own `incomplete` flag:

- **`incomplete: true`** (the wizard's default for a new config): warnings
  are reported but never block anything. `generate` proceeds. This is what
  makes it possible to start onboarding a customer before every detail is
  known.
- **`incomplete: false`** (a config declaring itself finished): the same
  warnings now block `generate` too. You'll see the warning list followed
  by:

  ```
  This setup is marked complete (incomplete: false) but has warnings above.
  Fix them, or set incomplete: true in the config to generate as a draft anyway.
  ```

The idea: marking a setup `incomplete: false` is a promise, and the tool
actually holds you to it, rather than being a label with no effect. If
you're not ready for that yet, set it back to `true` and keep working.

`validate --strict` is a separate, always-available override: it treats
*any* warning as blocking, regardless of `incomplete`. Use it for a stricter
manual check without changing the file.

## 7. Generating Pipeline Files

```bash
pipeline-generator generate --config setups/acme.yaml --output-dir generated
```

This does, in order:

1. Re-validates the config (see section 6 for what can block this step).
2. Creates `generated/<setup-id>/` (the setup ID is sanitized into a safe
   folder name automatically, even if you typed something unusual for it).
3. Copies the config itself in as `customer.yaml`.
4. Renders the CI/CD-specific files (see section 9 for exactly what, per
   platform).
5. Writes `scripts/run-<tool_type>.sh`, executable, which is what those
   CI/CD files actually call to run a test (see section 8).
6. Writes a `README.md` summarizing the setup, its manual/automated usage,
   and a short "remaining TODOs" list (fill in secrets, replace any `TODO`
   placeholders, etc.).

Everything under `generated/<setup-id>/` is what you commit into or hand off
to the customer's repository.

## 8. Running Performance Tests

There is no `pipeline-generator run` command — `pipeline-generator`'s job
ends at `generate`. Instead, every generated setup ships its own
`scripts/run-<tool_type>.sh`, a self-contained bash script with no
dependency on `pipeline-generator` or Python. This is the command the
*generated* pipeline files themselves invoke:

```bash
./scripts/run-jmeter.sh --environment qa --scenario checkout_smoke
```

You can also run it by hand from inside a generated (or already-committed)
setup folder, before ever triggering the real pipeline, since it's just a
plain script:

```bash
cd generated/acme-github-actions-jmeter-storefront
./scripts/run-jmeter.sh --environment qa --scenario checkout_smoke
```

What the script does:

1. Parses `--environment` and `--scenario` (both required; BlazeMeter also
   requires `--timeout-minutes`).
2. Resolves each to its catalog `identifier` using generated shell
   functions (`resolve_environment_identifier`/
   `resolve_scenario_identifier`) — an unrecognized key prints
   `Unknown environment key: ...` / `Unknown scenario key: ...` and exits
   non-zero.
3. Creates `run-output/`.
4. Runs the tool.

Step 4 is where the three tools currently differ:

- **JMeter** — real, working execution. If `verify_scenario_exists` is in
  `pre_run_checks`, it first checks the configured `test_plan_path` exists
  (`Test plan not found: ...` and exit 1 if not), then runs:

  ```bash
  jmeter -n -t <test_plan_path> -l run-output/results.jtl -e -o run-output/report \
    -Jenvironment=<resolved environment identifier> -Jscenario=<resolved scenario identifier>
  ```

  Note that JMeter parameterizes a single `.jmx` test plan via `-J`
  properties rather than selecting between multiple plan files, so a
  scenario's `identifier` should be a property value your test plan reads
  with `${__P(scenario)}` (e.g. `checkout-smoke`) — not a filename. The
  `.jmx` file itself is named once, in `tool.connection.test_plan_path`.

- **LoadRunner Professional** — real, working execution, assuming the CI
  job runs on an agent co-located with the LoadRunner Controller. If
  `verify_controller_access` is in `pre_run_checks`, it first checks
  `wlrun_path` resolves to a runnable command; if `verify_scenario_exists`
  is configured, it checks the resolved scenario `.lrs` file exists. Then
  it runs:

  ```bash
  wlrun -Run -TestPath <resolved scenario identifier> \
    -ResultName run-output/<environment key>_<scenario key>
  ```

  Unlike JMeter, `wlrun` has no native "environment" parameter, so a
  scenario's catalog `identifier` is a full `.lrs` file path (one catalog
  entry per environment/scenario combination) rather than a property
  value — the environment key is used only to name the results folder.
  `wlrun`'s own exit code is known to be unreliable on some LoadRunner
  versions (it can return 0 even on a failed scenario); nonzero is still
  treated as failure since it's the best signal available locally.

- **BlazeMeter** — real, working execution. It first requires
  `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET` to be set (two of the
  three prechecks below need them). If configured, `verify_host_reachable`
  checks `base_url` responds at all (no auth needed); `verify_project_exists`
  checks the configured `project_id` exists inside `workspace_id`;
  `verify_scenario_exists` checks the configured test ID exists — both
  authenticated BlazeMeter API calls. It then starts the test via
  `POST /api/v4/tests/<id>/start`, polls
  `GET /api/v4/masters/<id>/status` every 15 seconds until it finishes
  (bounded by a required `--timeout-minutes` flag the generated pipeline
  always passes), and downloads a summary report into
  `run-output/<environment_slug>_<scenario_slug>/summary.json`. See
  section 10 for the two API-surface details flagged as needing
  verification against a live account.

Bad input (missing `--environment`/`--scenario`/`--timeout-minutes` where
required, an unrecognized key, or a non-numeric `--timeout-minutes`) is
reported as a plain one-line message on stderr with a non-zero exit code,
not a stack trace.

## 9. CI/CD Platforms — What Gets Generated

All three renderers produce one file for the manual pipeline (if enabled)
and one file per enabled automated job, all of which call the same
`scripts/run-<tool_type>.sh` under the hood with the appropriate
`--environment`/`--scenario` flags — so the generated pipeline logic is
identical across platforms; only the wrapping syntax differs. None of them
install Python or `pipeline-generator` — the script is pure bash and needs
nothing beyond the tool itself (e.g. `jmeter` on `PATH`) at execution time.

### GitHub Actions

Written to `.github/workflows/`:

- `performance-manual.yml` — a `workflow_dispatch` workflow with `choice`
  inputs for environment and scenario, populated from your catalog.
- `performance-automated-<job-name>.yml` — a `workflow_call` reusable
  workflow, one per enabled automated job.

Both check out the repo, run `./scripts/run-<tool_type>.sh` with the
environment/scenario, and upload `run-output/` as a build artifact.

### Azure DevOps

Written to `azure/`:

- `performance-manual.yml` — a pipeline with `string`-typed parameters
  (`environment`, `scenario`) constrained to your catalog's values.
- `performance-automated-<job-name>.yml` — one per enabled automated job.

Both check out the repo, run `./scripts/run-<tool_type>.sh` in a
"Run performance wrapper" step, and publish `run-output/` as a pipeline
artifact.

### Jenkins

Written to `jenkins/` as declarative Jenkinsfiles:

- `Jenkinsfile.performance-manual` — a pipeline with `choice` build
  parameters for environment and scenario.
- `Jenkinsfile.performance-automated-<job-name>` — one per enabled
  automated job.

Both `sh` out to `./scripts/run-<tool_type>.sh` with the environment/scenario,
and archive `run-output/**` as build artifacts.

## 10. Performance Testing Tools

The config schema, wizard prompts, and validation all work end-to-end for
all three tools, and `generate` writes a real, working
`scripts/run-<tool_type>.sh` for each:

- **JMeter and LoadRunner Professional.** The generated script resolves
  the environment/scenario and runs `jmeter -n -t <test_plan_path> ...` or
  `wlrun -Run -TestPath <scenario_identifier> ...` for real, with no
  further work needed. LoadRunner Professional assumes the CI job runs on
  an agent co-located with the LoadRunner Controller — see
  `docs/superpowers/specs/
  2026-09-09-loadrunner-local-agent-execution-design.md` for the full
  design and why other execution strategies (SSH/WinRM remoting, LoadRunner
  Enterprise's REST API) were rejected. **Known limitation:** the generated
  CI/CD pipeline files themselves currently target a hosted runner/pool by
  default (`ubuntu-latest` for GitHub Actions, a Microsoft-hosted pool for
  Azure DevOps) — none of these can run `wlrun`. Before a LoadRunner
  Professional setup will actually work, you must hand-edit the generated
  pipeline to target a self-hosted agent that's co-located with the
  Controller (Jenkins' `agent any` is closest to workable already, but
  still needs a Windows-capable shell step). This retargeting isn't
  automated yet — see the generated setup README's "Remaining TODOs".
- **BlazeMeter.** The generated script authenticates via
  `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET`, optionally verifies
  host reachability / project existence / test existence, starts a test
  through BlazeMeter's REST API v4, polls until it finishes (bounded by a
  required `--timeout-minutes` flag), and downloads a summary report — see
  `docs/superpowers/specs/
  2026-09-09-blazemeter-real-api-execution-design.md` for the full design.
  **Known limitation:** the exact status-string vocabulary
  (`ENDED`/`ERROR`/`ABORTED`) and the `reports/main/summary` endpoint are
  this design's best understanding of the BlazeMeter API v4, not
  independently verified against current live documentation (which sits
  behind a login-gated API explorer) — verify against a real account
  before production use.

| Tool | Auth model | Connection fields | Precheck vocabulary | Generated script |
|---|---|---|---|---|
| **LoadRunner Professional** | `none` (runs on a controller-adjacent agent) | optional `wlrun_path` | `verify_controller_access`, `verify_scenario_exists`, `verify_load_generators_connected` (TODO comment only), `collect_results` | Real and complete — runs `wlrun` locally; no remote credentials managed by this script; needs a self-hosted runner (see above). |
| **BlazeMeter** | Remote (`api_token`) | `base_url`, `workspace_id`, `project_id` | `verify_host_reachable`, `verify_project_exists`, `verify_scenario_exists`, `collect_results` (TODO comment only) | Real and complete — drives BlazeMeter's REST API; needs `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET` set; two API-surface details need live-account verification (see above). |
| **JMeter** | `none` (runs locally) | `test_plan_path`, optional `jmeter_bin` | `verify_scenario_exists`, `collect_results` (TODO comment only) | Real and complete — no remote API or credentials needed, just a local `jmeter` subprocess call. |

## 11. Validating Configs

```bash
pipeline-generator validate --config setups/acme.yaml [--strict]
```

Prints `Validation passed.` if there are no errors or warnings, otherwise
lists errors and warnings separately. Exit code is non-zero if there are any
errors, or (with `--strict`) any warnings at all. This never writes
anything to disk — it's safe to run at any point, as often as you like, to
check a config's current state.

## 12. Full Walkthrough Example

Onboarding a fictional customer, Acme Corp, who uses GitHub Actions and
BlazeMeter, from scratch:

```bash
# 1. Run the wizard
pipeline-generator wizard --output setups/acme-bm.yaml
#    Step 1: working_location=central_repo, final_pipeline_destination=
#            copy_to_customer_repo, target_repository=github.com/acme/storefront,
#            generation_mode=both
#    Step 2: cicd=github_actions, tool=blazemeter, auth=api_token
#    Step 3: accept the suggested setup ID
#    Step 4: base_url=https://a.blazemeter.com, workspace_id=12345,
#            project_id=67890
#    Step 5: enabled=yes, name="Acme BlazeMeter Manual Run", timeout=180
#    Step 6: add environments (qa), add scenarios (checkout_smoke_qa,
#            identifier = the real BlazeMeter Test ID, e.g. 1234567)
#    Step 7: add one automated job: post-deploy-smoke, env=qa,
#            scenario=checkout_smoke_qa, timeout=60
#    Step 8: enable verify_host_reachable, verify_project_exists,
#            verify_scenario_exists, collect_results
#    -> wizard prints a summary and validation result, then exits

# 2. Check it's actually ready to hand off
pipeline-generator validate --config setups/acme-bm.yaml
# If it prints only "Validation passed." you're good. If there are
# warnings and the file says incomplete: false, fix them or set
# incomplete: true first (see section 6).

# 3. Generate the real pipeline files
pipeline-generator generate --config setups/acme-bm.yaml --output-dir generated
# -> generated/github-actions-blazemeter-storefront/ now contains
#    customer.yaml, README.md, scripts/run-blazemeter.sh, and
#    .github/workflows/*.yml (the workflow already passes --timeout-minutes
#    60 automatically for the automated job, 180 for the manual pipeline)

# 4. Sanity-check the generated script locally before handing off
cd generated/github-actions-blazemeter-storefront
export BLAZEMETER_API_KEY_ID=... BLAZEMETER_API_KEY_SECRET=...
./scripts/run-blazemeter.sh --environment qa --scenario checkout_smoke_qa --timeout-minutes 60
# -> resolves qa/checkout_smoke_qa to their catalog identifiers, checks jq
#    is available, requires the two env vars above, runs the configured
#    prechecks, then starts the real BlazeMeter test and polls it to
#    completion -- or fails with a specific error (missing secret, host
#    unreachable, project/test not found, or timeout) rather than the old
#    "not implemented yet" message.

# 5. Hand off generated/github-actions-blazemeter-storefront/ to Acme,
#    or commit it into their repo directly, per whatever
#    final_pipeline_destination you chose in Step 1.
```

## 13. Troubleshooting

**"`<path>` already exists. Pass `--resume` to continue editing it..."**
You ran `wizard` with `--output` pointing at a file that's already there.
Add `--resume` to continue that draft, or pick a new `--output` path.

**"This setup is marked complete (incomplete: false) but has warnings
above."**
See section 6. Either resolve the listed warnings, or set `incomplete: true`
in the YAML if you're not actually ready to finalize this setup yet.

**"Automated job '...' references an unknown environment/scenario."**
The job's `environment_ref`/`scenario_ref` doesn't match any `key` under
`catalog.environments`/`catalog.scenarios`. If you built the job through the
wizard's Step 7, this shouldn't happen (refs are chosen from the catalog);
it's more likely if you hand-edited the YAML.

**"ERROR: BLAZEMETER_API_KEY_ID must be set" / "... BLAZEMETER_API_KEY_SECRET must be set"**
The generated `scripts/run-blazemeter.sh` needs both env vars set before
it will make any API call — set them as CI/CD secrets (see the generated
setup README).

**"ERROR: jq is required to parse BlazeMeter API responses but was not found."**
The generated `scripts/run-blazemeter.sh` needs `jq` installed on whatever
agent/runner executes it. GitHub-hosted and Azure-hosted runners have it
preinstalled; self-hosted agents (including any Jenkins agent) may not —
install it there first.

**"ERROR: cannot reach BlazeMeter host: ..." / "... project not found ..." / "... test not found ..."**
One of BlazeMeter's configured prechecks
(`verify_host_reachable`/`verify_project_exists`/`verify_scenario_exists`)
failed — check `base_url`/`workspace_id`/`project_id` in `customer.yaml`
and the catalog scenario's `identifier` (must be a real BlazeMeter Test
ID), or that the API key has access to that workspace/project.

**"ERROR: Timed out after N minutes waiting for BlazeMeter test to finish"**
The test didn't reach `ENDED` status within `--timeout-minutes` (set from
`timeout_minutes` in `customer.yaml`) — check the run in the BlazeMeter
web UI, or increase the timeout.

**"ERROR: wlrun not found: ..."**
The generated `scripts/run-loadrunner_professional.sh` couldn't find the
configured `wlrun_path` on this machine. LoadRunner Professional's script
assumes it's running on an agent co-located with the LoadRunner Controller
(section 10) — check `wlrun_path` in `customer.yaml`, or that the CI job
is actually running on the right agent.

**"Unknown environment key: ..." / "Unknown scenario key: ..."**
The `--environment`/`--scenario` value passed to `scripts/run-<tool>.sh`
doesn't match any `key` in `catalog.environments`/`catalog.scenarios` for
that setup. Check the value against `customer.yaml`, or regenerate if the
catalog changed after the script was last written.

**"Usage: ./scripts/run-<tool>.sh --environment <key> --scenario <key>" / "... --timeout-minutes <minutes>"**
The script was called without a required flag — `--environment`/
`--scenario` for every tool, plus `--timeout-minutes` for BlazeMeter — check
the CI/CD step (or your own command line) that invokes it, against
section 8.

**Wizard exits with "Wizard cancelled..." instead of finishing.**
You hit Ctrl-C, or piped input ran out. This is a clean cancellation, not a
crash — the message tells you whether anything was saved to `--output`
before the cancellation.

## 14. Current Limitations

Worth knowing going in:

- **BlazeMeter's exact API surface is unverified against live
  documentation.** The status-string vocabulary and report endpoint are
  this design's best understanding of the BlazeMeter API v4 (section 10)
  — verify against a real account before relying on this in production.
- **LoadRunner Professional's generated pipelines need manual
  runner-retargeting.** They default to hosted runners that can't reach a
  LoadRunner Controller (section 10) — this isn't automated yet.
- **Renderer output is escaped/safe, but not schema-validated beyond
  YAML/Groovy syntax.** A generated workflow will parse correctly and won't
  let a hostile config value break out of its intended context, but the
  tool doesn't independently verify the result against GitHub Actions' or
  Azure Pipelines' full schema.
- **No non-interactive wizard mode.** Every wizard field comes from an
  interactive prompt; there's no way yet to pre-seed answers from flags or
  an answer file for scripted/bulk onboarding.
- **GitLab CI is not supported** as a `cicd.type` (GitHub Actions, Azure
  DevOps, and Jenkins are).

See `docs/current-state-and-readiness-plan.md` for the full, actively
maintained list of what's done and what's next.
