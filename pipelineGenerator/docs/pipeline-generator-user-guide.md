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
  calls to do its work (e.g. `./scripts/run-jmeter.sh --test-case
  "$TEST_CASE"`, where the test case is one `<environment>: <scenario>`
  pair from the catalog). It's a plain bash script with no dependency on
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

### Step 1 — What should this setup generate?

| Prompt | What it means |
|---|---|
| `Generation mode` (`manual_only` / `automated_only` / `both`) | Whether to generate the on-demand manual pipeline (a human triggers it, picking environment/scenario each run), the reusable automated job(s) (no human involved — another pipeline calls it with a fixed environment/scenario), or both. This also decides whether Step 5 (manual pipeline) and Step 7 (automated jobs) run at all. |

### Step 2 — CI/CD platform and performance tool

Two prompts, each a numbered menu:

- **CI/CD platform**: `github_actions`, `azure_devops`, or `jenkins`.
- **Performance tool**: `loadrunner_professional`, `blazemeter`, or `jmeter`.

Right after these two answers, the wizard silently assigns `setup.id` —
there's no prompt for it. It's `<cicd-platform>-<tool>` plus a short random
suffix (e.g. `github-actions-loadrunner-professional-4f2a9c`): the suffix
exists so two setups that happen to share the same CI/CD+tool combo don't
suggest the same id and silently overwrite each other's output folder (this
becomes the name of the folder `generate` creates). It's generated once —
resuming a draft that already has an id never changes it, even if you
switch CI/CD platform or tool on that resume. You can still hand-edit
`setup.id` directly in the YAML afterward if you want something more
readable; it's made filesystem-safe automatically when `generate` runs
regardless of what it's set to.

Then the wizard asks **which runner/agent runs the pipeline** (`cicd.runner`):

| CI/CD | What to enter | Blank means |
|---|---|---|
| GitHub Actions | `runs-on` labels, comma-separated (e.g. `self-hosted, windows, loadrunner`) | GitHub-hosted `ubuntu-latest` |
| Azure DevOps | a self-hosted agent pool name (e.g. `LoadRunner Agents`) | Microsoft-hosted `ubuntu-latest` |
| Jenkins | an agent label expression (e.g. `loadrunner-controller`) | `agent any` |

JMeter and BlazeMeter are fine on the hosted default. **LoadRunner
Professional** runs `wlrun` on the agent itself, so it must target the
Windows machine next to your Controller; its default is `TODO`, and the
setup stays a draft until it's set. Generated steps always run the script
with **bash** (`shell: bash` on GitHub, a `bash:` step on Azure, `sh` on
Jenkins). On a Windows agent:

- Install Git for Windows and put `C:\Program Files\Git\bin` (GitHub/Azure)
  or `C:\Program Files\Git\usr\bin` (Jenkins `sh`, which also needs
  `nohup`) on the agent service's PATH **ahead of** `C:\Windows\System32`
  — otherwise WSL's `bash.exe` is found first and can't see `wlrun.exe`.
  The installer's default only adds `Git\cmd`, which has no bash. Restart
  the agent service afterwards.
- The generated `scripts/.gitattributes` pins `*.sh` to LF line endings;
  copy it into your repo with the script, or a CRLF checkout (Git for
  Windows' default) makes bash fail with `/usr/bin/env: 'bash\r'`.
- The LoadRunner Controller is a GUI app, so the agent may need to run as
  an interactive user rather than a Windows service.
- Write `wlrun_path` with forward slashes if it's a full path
  (`C:/Program Files (x86)/.../wlrun.exe`).

### Step 3 — Tool connection details

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
| `test_plan_path` | Required — path to the `.jmx` test plan, relative to your repository root, e.g. `performance/checkout.jmx`. |
| `docker_image` | Optional — Docker image JMeter runs in; blank uses `justb4/jmeter:5.6.3`. The agent/runner needs Docker installed, not a local JMeter install. |

### Step 4 — Test parameters

| Prompt | Asked for | Notes |
|---|---|---|
| `Test type label` | every tool | Short single-line label (`load`, `stress`, `soak`, `spike`, …; letters, digits, spaces, `_.-`, up to 64), default `load`. Only a label: passed to your test script (`-Jtest_type` for JMeter) and recorded in `run-summary.json`; it never changes how the test runs. |
| `Number of users` | JMeter, BlazeMeter | Whole number ≥ 1. |
| `Ramp-up (seconds)` | JMeter, BlazeMeter | Whole number ≥ 0. |
| `Duration at full load (minutes)` | JMeter, BlazeMeter | Whole number ≥ 1 — the steady-state/hold time after ramp-up. |
| `Target throughput (requests/second, 0 = no cap)` | JMeter, BlazeMeter | Whole number ≥ 0. |

Type `TODO` (or keep a `TODO` default) for anything you don't know yet —
the setup stays a draft, still generates, and the generated script refuses
to run until it's filled in. LoadRunner Professional is only asked the
label: users, ramp-up, duration and throughput come from the `.lrs`
scenario itself. There is no ramp-down setting.

How the values reach the tool:

- **JMeter** — passed as `-J` properties your `.jmx` must read:
  `${__P(users,1)}` (Number of Threads), `${__P(ramp_up_seconds,0)}`
  (Ramp-up), `${__P(duration_seconds,60)}` (Thread Group → Specify thread
  lifetime → Duration; = ramp-up + duration at full load, because JMeter's
  thread lifetime includes the ramp-up), `${__P(throughput_per_minute,0)}`
  (Constant Throughput Timer; derived from req/s), `${__P(throughput_rps,0)}`
  and `${__P(test_type)}`.
- **BlazeMeter** — applied to the test with one API call
  (`overrideExecutions`: concurrency, rampUp, holdFor, throughput) before it
  starts. This persists on the test in BlazeMeter, and the field names are
  pending verification against a live account.

The manual pipeline shows each value as a trigger input pre-filled from
`customer.yaml`, so a single run can use different values without
regenerating. Automated jobs always use the `customer.yaml` values.

### Step 5 — Manual pipeline

Only asked if Step 1's generation mode included the manual pipeline
(`manual_only` or `both`) — choosing that mode already means you want a
manual pipeline, so this step just fills in its details rather than
asking again:

- `Manual pipeline name` — becomes the pipeline's display name.
- `Manual pipeline timeout minutes` — must be a positive whole number;
  invalid input re-prompts rather than silently falling back to a default.

### Step 6 — Environments and scenarios

For a brand-new config, you're asked "Add environments now?" (yes/no);
saying no leaves the catalog empty for now (fine for a draft — see
section 6). Saying yes collects the environments, then asks for **each
environment's own scenarios** in turn. Scenarios belong to an environment:
the same scenario key (e.g. `checkout_smoke`) can exist under `qa` and
`staging` with a different identifier each, and the manual pipeline's
single dropdown lists only the `<environment>: <scenario>` pairs you
defined — so a scenario that only exists for QA can't be run against
staging by mistake.

Keys must be simple names — letters, digits, `_`, `.`, `-`, starting with
a letter or digit (e.g. `qa`, `checkout_smoke`); anything else is re-asked.

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

Each environment/scenario entry has two fields: a `key` (used
programmatically, e.g. in the dropdown value and in automated job
references) and an `identifier` whose meaning depends on the tool picked in
Step 2 — the wizard's prompt label changes to match (defaults to a `TODO`
placeholder if you don't have it yet):

- **JMeter**: a `-J` property value your `.jmx` reads via
  `${__P(environment)}`/`${__P(scenario)}` — not an ID on any external
  system.
- **LoadRunner**: the **scenario** identifier is the full path to the
  `.lrs` file to run. Environments have no identifier — the generated
  script never uses one, so the wizard doesn't ask; only the environment
  `key` matters (it names the results folder).
- **BlazeMeter**: the **scenario** identifier is the real BlazeMeter Test
  ID to start. As with LoadRunner, environments are just a `key`.

Two keys that only differ in punctuation or case (`checkout_smoke` vs
`checkout.smoke`, `qa` vs `QA`) would share a results folder, so `validate`
warns about them.

### Step 7 — Automated jobs

Only asked if generation mode included automated jobs (`automated_only` or
`both`). Same keep-as-is/add-more/start-over pattern as Step 6 when
resuming. For each new job you enter:

- **Job name** (blank to stop adding jobs)
- **Environment key** and **Scenario key** — if you already have catalog
  entries from Step 6, these are presented as numbered choices (not free
  text), and the scenario choices are only the chosen environment's own
  scenarios — so a job can't reference a pair that doesn't exist.
- **Timeout minutes** — same positive-integer prompt as Step 5.

### Step 8 — Pre-run checks

One screen listing the checks applicable to whichever tool you picked in
Step 2 — JMeter sees 2 (`verify_scenario_exists`, `verify_docker_available`);
LoadRunner Professional sees 2 (`verify_controller_access`,
`verify_scenario_exists`); BlazeMeter sees 3 different ones
(`verify_host_reachable`, `verify_project_exists`, `verify_scenario_exists`)
— BlazeMeter's real failure modes don't match LoadRunner's
controller-flavored vocabulary, so it gets its own. Every check offered here
is actually implemented (no dead options that silently do nothing when
selected). Type comma-separated numbers to select specific ones, `all`,
`none`, or just press Enter to keep whatever was already enabled (useful
when resuming).

### After Step 8

The wizard prints a plain-language summary (setup ID, CI/CD, tool, whether
the manual pipeline is enabled, and counts of environments/scenarios/
automated jobs), then runs the same check `validate` would and prints the
result — so you see any outstanding warnings immediately, in the same
terminal session, without a separate command.

## 5. Understanding `customer.yaml`

Full annotated example (`incomplete: false`, i.e. a finished, ready-to-hand-off
setup):

```yaml
incomplete: false                 # false = "this is done"; see section 6

setup:
  id: acme-github-actions-loadrunner-professional-storefront
  generation_mode: both                          # manual_only | automated_only | both

cicd:
  type: github_actions            # github_actions | azure_devops | jenkins

tool:
  type: loadrunner_professional   # loadrunner_professional | blazemeter | jmeter
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
    scenario_ref: checkout_smoke     # must match a key in that environment's scenarios
    timeout_minutes: 90

catalog:
  environments:
    - key: qa                        # letters, digits, _ . - only
      identifier: QA
      scenarios:                     # this environment's own scenarios
        - key: checkout_smoke        # unique within this environment
          identifier: C:\Scenarios\checkout_smoke_qa.lrs
    - key: staging
      identifier: Staging
      scenarios:
        - key: checkout_smoke        # same key, staging's own .lrs
          identifier: C:\Scenarios\checkout_smoke_staging.lrs

pre_run_checks:
  - verify_controller_access
  - verify_scenario_exists

load_profile:
  test_type: load                  # label only; LoadRunner takes load shape from the .lrs
  # JMeter / BlazeMeter also use:
  # users: 20
  # ramp_up_seconds: 60
  # duration_minutes: 10
  # throughput_rps: 0              # 0 = no cap

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
  unsupported `cicd.type` or `tool.type` value. These always block
  `generate`, no matter what.
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
./scripts/run-jmeter.sh --test-case "qa: checkout_smoke"
```

Load values default to `customer.yaml`'s `load_profile`; JMeter and
BlazeMeter scripts accept `--users`, `--ramp-up-seconds`,
`--duration-minutes` and `--throughput-rps` to override them for one run,
and every script accepts `--test-type`. Before doing anything else, the
script checks every value it needs (connection fields, the resolved
catalog identifiers, load values) and stops with one line naming the
field if any is still `TODO`, e.g.
`ERROR: load_profile.users is not set (still TODO). Fill it in customer.yaml and regenerate, or pass it as a flag.`

You can also run it by hand from inside a generated (or already-committed)
setup folder, before ever triggering the real pipeline, since it's just a
plain script:

```bash
cd generated/acme-github-actions-jmeter-storefront
./scripts/run-jmeter.sh --test-case "qa: checkout_smoke"
```

What the script does:

1. Parses `--test-case "<environment>: <scenario>"` (required; BlazeMeter
   also requires `--timeout-minutes`).
2. Resolves it with the generated `resolve_test_case` function, which sets
   both keys, both catalog identifiers and both results-folder slugs at
   once — a pair that isn't defined in the catalog prints
   `Unknown test case: ...` and exits non-zero.
3. Creates `run-output/<environment_slug>_<scenario_slug>/` (all three
   tools use this same per-run folder, with slugs sanitized at generation
   time) — in
   practice this happens just before the tool actually runs, after any
   configured prechecks in step 4 have already passed, so a precheck
   failure leaves no per-run folder behind.
4. Runs the tool.
5. Writes `run-summary.json` into that folder — see "Run Summaries" below.
   This step is skipped if a precheck in step 4 already failed.

Step 4 is where the three tools currently differ:

- **JMeter** — real, working execution, inside a Docker container rather
  than a local install. If `verify_scenario_exists` is in `pre_run_checks`,
  it first checks the configured `test_plan_path` exists on the host
  (`Test plan not found: ...` and exit 1 if not); if
  `verify_docker_available` is configured, it checks `docker` is on `PATH`.
  Then it runs:

  ```bash
  docker run --rm -v "$(pwd):/workspace" -w /workspace <docker_image> \
    -n -t <test_plan_path> \
    -l run-output/<environment_slug>_<scenario_slug>/results.jtl \
    -e -o run-output/<environment_slug>_<scenario_slug>/report \
    -Jenvironment=<resolved environment identifier> -Jscenario=<resolved scenario identifier>
  ```

  The whole working directory is bind-mounted at `/workspace` (not just the
  test plan file), so a `.jmx` referencing CSV data sets or included
  fragments by relative path still resolves the same as a local install
  would, and results written into `run-output/...` land directly on the
  host filesystem since that path is inside the mount. `docker_image`
  defaults to `justb4/jmeter:5.6.3` if left blank.

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

### Run Summaries

After a run is attempted (skipped entirely if a precheck failed first),
every generated script writes one JSON file to
`run-output/<environment_slug>_<scenario_slug>/run-summary.json`:

```json
{
  "tool": "jmeter",
  "run_id": "staging_smoke-test_20260910T143000Z",
  "environment": "staging",
  "scenario": "smoke-test",
  "status": "passed",
  "started_at": "2026-09-10T14:30:00Z",
  "ended_at": "2026-09-10T14:34:12Z",
  "duration_seconds": 252,
  "report_link": "run-output/staging_smoke-test/report/index.html",
  "results_dir": "run-output/staging_smoke-test",
  "artifact_status": "complete",
  "test_type": "load",
  "users": 20,
  "ramp_up_seconds": 60,
  "duration_minutes": 10,
  "throughput_rps": 0
}
```

The load fields are the values the run actually used (after any
override). LoadRunner writes `test_type` and `null` for the four numbers,
so the key set is the same for every tool.

`status` is `passed`, `failed`, or `error` (`error` only occurs for
BlazeMeter, when it times out before reaching a terminal API status —
JMeter/LoadRunner's own exit codes only ever produce `passed`/`failed`).
`run_id` also varies by tool: it's
`<environment_slug>_<scenario_slug>_<UTC timestamp>` for JMeter/LoadRunner,
and BlazeMeter's own API `master_id` for BlazeMeter — so, like
`report_link`, its exact format isn't uniform across tools even though the
field name is. `report_link` is a relative filesystem path for
JMeter/LoadRunner and a BlazeMeter web UI URL for BlazeMeter — don't assume
it's always a URL.
This file is separate from BlazeMeter's own `summary.json`/
`report_link.json` (its raw API report), which are unchanged.

Bad input (missing `--test-case`/`--timeout-minutes` where required, a
pair that isn't in the catalog, or a non-numeric `--timeout-minutes`) is
reported as a plain one-line message on stderr with a non-zero exit code,
not a stack trace.

## 9. CI/CD Platforms — What Gets Generated

All three renderers produce one file for the manual pipeline (if enabled)
and one file per enabled automated job, all of which call the same
`scripts/run-<tool_type>.sh` under the hood with the appropriate
`--test-case` flag — so the generated pipeline logic is
identical across platforms; only the wrapping syntax differs. None of them
install Python or `pipeline-generator` — the script is pure bash and needs
nothing beyond the tool itself (e.g. `jmeter` on `PATH`) at execution time.

### GitHub Actions

Written to `.github/workflows/`:

- `performance-manual.yml` — a `workflow_dispatch` workflow with one
  `test_case` `choice` input listing your catalog's `<environment>:
  <scenario>` pairs, plus the load-profile inputs.
- `performance-automated-<job-name>.yml` — a `workflow_call` reusable
  workflow, one per enabled automated job.

Both check out the repo, run `./scripts/run-<tool_type>.sh --test-case
...`, and upload `run-output/` as a build artifact. For BlazeMeter, both map
repository secrets `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET` into
the run step; the reusable workflow also declares them under
`workflow_call.secrets`, so its caller must pass them (`secrets: inherit`).
Both jobs share a `concurrency` group per setup (`performance-<setup id>`,
never cancelling a running test), so a manual and an automated run of the
same setup can't overlap.

### Azure DevOps

Written to `azure/`:

- `performance-manual.yml` — a pipeline with one `string`-typed
  `test_case` parameter constrained to your catalog's `<environment>:
  <scenario>` pairs, plus the load-profile parameters.
- `performance-automated-<job-name>.yml` — one per enabled automated job.

Both check out the repo, run `./scripts/run-<tool_type>.sh` in a
"Run performance wrapper" step, and publish `run-output/` as a pipeline
artifact. For BlazeMeter, create secret pipeline variables
`BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET`; the step maps them into
its `env:` (Azure never exposes secret variables to scripts on its own).
The automated template takes a `dependsOn` parameter — pass your deploy job
(`parameters: {dependsOn: [deploy]}`), because jobs in one stage otherwise
run in parallel and the test would hit the environment mid-deploy. Azure
doesn't serialize runs by itself: add an **Exclusive lock** check to the
agent pool (or an Environment) to keep two load tests from overlapping.

### Jenkins

Written to `jenkins/` as declarative Jenkinsfiles:

- `Jenkinsfile.performance-manual` — a pipeline with one `TEST_CASE`
  `choice` build parameter listing your catalog's pairs, plus the
  load-profile `string` parameters.
- `Jenkinsfile.performance-automated-<job-name>` — one per enabled
  automated job.

Both `sh` out to `./scripts/run-<tool_type>.sh --test-case ...`, and archive
`run-output/**` as build artifacts. For BlazeMeter, the call is wrapped in
`withCredentials` reading a **Username with password** credential with ID
`blazemeter-api-key` (username = API key ID, password = API key secret).
Both Jenkinsfiles set `disableConcurrentBuilds()`; for LoadRunner also give
the Controller's agent a single executor, since that's what keeps the manual
and automated jobs from overlapping on it.

## 10. Performance Testing Tools

The config schema, wizard prompts, and validation all work end-to-end for
all three tools, and `generate` writes a real, working
`scripts/run-<tool_type>.sh` for each:

- **JMeter and LoadRunner Professional.** The generated script resolves
  the environment/scenario and runs `docker run ... <docker_image> -n -t
  <test_plan_path> ...` or `wlrun -Run -TestPath <scenario_identifier> ...`
  for real, with no further work needed beyond Docker being available for
  JMeter. LoadRunner Professional assumes the CI job runs on
  an agent co-located with the LoadRunner Controller — see
  `docs/superpowers/specs/
  2026-09-09-loadrunner-local-agent-execution-design.md` for the full
  design and why other execution strategies (SSH/WinRM remoting, LoadRunner
  Enterprise's REST API) were rejected. The generated pipelines target that
  agent through `cicd.runner` (wizard Step 2: GitHub `runs-on` labels,
  Azure agent pool, Jenkins agent label) and run the script with bash, so
  the agent needs Git for Windows' bash on `PATH` alongside `wlrun` — see
  Step 2 in section 4 for the exact Windows agent setup.
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
| **LoadRunner Professional** | `none` (runs on a controller-adjacent agent) | optional `wlrun_path` | `verify_controller_access`, `verify_scenario_exists` | Real and complete — runs `wlrun` locally; no remote credentials managed by this script; needs a self-hosted runner (see above). |
| **BlazeMeter** | Remote (`api_token`) | `base_url`, `workspace_id`, `project_id` | `verify_host_reachable`, `verify_project_exists`, `verify_scenario_exists` | Real and complete — drives BlazeMeter's REST API; needs `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET` set; two API-surface details need live-account verification (see above). |
| **JMeter** | `none` (runs in a container on the agent/runner) | `test_plan_path`, optional `docker_image` (default `justb4/jmeter:5.6.3`) | `verify_scenario_exists`, `verify_docker_available` | Real and complete — no remote API or credentials needed, runs via `docker run`; needs Docker installed on the agent/runner (not a local JMeter install). |

## 11. Validating Configs

```bash
pipeline-generator validate --config setups/acme.yaml [--strict]
```

Prints `Validation passed.` if there are no errors or warnings, otherwise
lists errors and warnings separately. Exit code is non-zero if there are any
errors, or (with `--strict`) any warnings at all. This never writes
anything to disk — it's safe to run at any point, as often as you like, to
check a config's current state.

A missing or malformed `--config` file (not found, or not valid YAML) is
reported as a clean one-line message and exit code `1`, not a traceback.

Beyond the schema checks described in section 5 ("Understanding
`customer.yaml`"), `validate` also catches:

- **A structurally wrong section** — e.g. a blank `manual_pipeline:` key
  (parses to `null`), or `catalog.environments` written as a list of plain
  strings instead of mappings. Reported as an error naming the exact
  section, and validation still continues to report other real problems
  in the same pass rather than stopping at the first one.
- **An unrecognized `pre_run_checks` value** — most often a typo (e.g.
  `verify_scenario_exist` missing the `s`). Without this warning, the
  check would be silently dropped at generation time with no trace at all
  in the generated script, not even a `# TODO precheck: ...` comment.
- **A duplicate environment `key`, or a duplicate scenario `key` within
  one environment** — two entries sharing a key make the second one's
  identifier silently unreachable in the generated resolver function.
  (Reusing a scenario key across *different* environments is normal.)
- **An environment with no scenarios** — it can never appear in the
  manual pipeline's dropdown.
- **A setup where neither the manual pipeline nor any automated job is
  enabled** — `generate` would otherwise happily produce a setup with zero
  CI/CD pipeline files and no indication anything is wrong.

## 12. Full Walkthrough Example

Onboarding a fictional customer, Acme Corp, who uses GitHub Actions and
BlazeMeter, from scratch:

```bash
# 1. Run the wizard
pipeline-generator wizard --output setups/acme-bm.yaml
#    Step 1: generation_mode=both
#    Step 2: cicd=github_actions, tool=blazemeter
#            (setup.id is assigned silently here, e.g.
#            github-actions-blazemeter-4f2a9c)
#    Step 3: base_url=https://a.blazemeter.com, workspace_id=12345,
#            project_id=67890
#    Step 4: test_type=load, users=20, ramp-up=60, duration=10,
#            throughput=0
#    Step 5: name="Acme BlazeMeter Manual Run", timeout=180
#    Step 6: add environment qa, then qa's scenario checkout_smoke
#            (identifier = the real BlazeMeter Test ID, e.g. 1234567)
#    Step 7: add one automated job: post-deploy-smoke, env=qa,
#            scenario=checkout_smoke, timeout=60
#    Step 8: enable verify_host_reachable, verify_project_exists,
#            verify_scenario_exists
#    -> wizard prints a summary and validation result, then exits

# 2. Check it's actually ready to hand off
pipeline-generator validate --config setups/acme-bm.yaml
# If it prints only "Validation passed." you're good. If there are
# warnings and the file says incomplete: false, fix them or set
# incomplete: true first (see section 6).

# 3. Generate the real pipeline files
pipeline-generator generate --config setups/acme-bm.yaml --output-dir generated
# -> generated/github-actions-blazemeter-4f2a9c/ now contains
#    customer.yaml, README.md, scripts/run-blazemeter.sh, and
#    .github/workflows/*.yml (the workflow already passes --timeout-minutes
#    60 automatically for the automated job, 180 for the manual pipeline)

# 4. Sanity-check the generated script locally before handing off
cd generated/github-actions-blazemeter-4f2a9c
export BLAZEMETER_API_KEY_ID=... BLAZEMETER_API_KEY_SECRET=...
./scripts/run-blazemeter.sh --test-case "qa: checkout_smoke" --timeout-minutes 60
# -> resolves the qa/checkout_smoke pair to its catalog identifiers, checks jq
#    is available, requires the two env vars above, runs the configured
#    prechecks, then starts the real BlazeMeter test and polls it to
#    completion -- or fails with a specific error (missing secret, host
#    unreachable, project/test not found, or timeout) rather than the old
#    "not implemented yet" message.

# 5. Hand off generated/github-actions-blazemeter-4f2a9c/ to Acme, or commit
#    it into their repo directly -- however you want to distribute it.
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
The job's `environment_ref` doesn't match any `catalog.environments[].key`,
or its `scenario_ref` isn't one of *that environment's* scenarios. If you built the job through the
wizard's Step 7, this shouldn't happen (refs are chosen from the catalog);
it's more likely if you hand-edited the YAML.

**"ERROR: BLAZEMETER_API_KEY_ID must be set" / "... BLAZEMETER_API_KEY_SECRET must be set"**
The generated `scripts/run-blazemeter.sh` needs both env vars set before
it will make any API call. The generated pipelines already map them in, so
this means the secret doesn't exist where the pipeline looks: GitHub
repository secrets (and `secrets: inherit` when calling an automated
workflow), Azure secret pipeline variables, or the Jenkins credential
`blazemeter-api-key` — exact names are in the generated setup README.

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

**"Unknown test case: ..."**
The `--test-case` value passed to `scripts/run-<tool>.sh` isn't an
`<environment>: <scenario>` pair defined in that setup's
`catalog.environments[].scenarios`. Check the value against `customer.yaml`, or regenerate if the
catalog changed after the script was last written.

**"Usage: ./scripts/run-<tool>.sh --test-case '<environment>: <scenario>'" / "... --timeout-minutes <minutes>"**
The script was called without a required flag — `--test-case` for every
tool, plus `--timeout-minutes` for BlazeMeter — check
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
