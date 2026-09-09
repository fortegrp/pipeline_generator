# LoadRunner Local-Agent Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scripts/run-loadrunner_professional.sh` real, working execution (matching JMeter's bar), replacing its current template stub that always ends in `exit 1`.

**Architecture:** The generated script assumes the CI job runs on a dedicated agent co-located with the LoadRunner Controller (so `wlrun.exe` is already on the box) and calls `wlrun` directly — no SSH/WinRM remoting, no LoadRunner Enterprise REST API. `tool.connection` shrinks to one optional field (`wlrun_path`); scenario catalog entries become full `.lrs` file paths, one per (environment, scenario) combination, since `wlrun` has no native "environment" parameter.

**Tech Stack:** Python 3.9+, pytest, bash (generated scripts).

**Spec:** `docs/superpowers/specs/2026-09-09-loadrunner-local-agent-execution-design.md`

## Global Constraints

- Every config-derived string embedded into a generated script goes through `renderers/quoting.py`'s `shell_quote` (project-wide rule, already followed by every other tool's renderer).
- `pre_run_checks` values are only ever rendered/acted on after passing through `_allowed_pre_run_checks()` in `renderers/scripts.py`, which filters against the `PRE_RUN_CHECKS` enum — never trust a raw config value directly (this closed a real shell-injection finding earlier in this project's history; the same discipline applies to any new check logic).
- No new remote credentials or secrets are introduced. LoadRunner Professional's `tool.auth.type` becomes `none`, matching JMeter's precedent (`AUTH_TYPES` in `config/schema.py`) — the generated script manages no remote credential of its own.
- Every pre-run check gates behind its `pre_run_checks` membership, same as `verify_scenario_exists` already does for JMeter — nothing in the generated script is "unconditionally on" beyond what the tool invocation itself requires.
- Run `python3 -m pytest -q` from the `pipelineGenerator` directory after every task; it must be green (currently 31 passed) before moving to the next task.
- No task in this plan touches BlazeMeter's script, JMeter's script, or any CI/CD renderer (`github_actions.py`/`azure_devops.py`/`jenkins.py`) — those are unaffected by this design.

---

### Task 1: Config input and validation for `wlrun_path`

**Files:**
- Modify: `src/pipeline_generator/config/validator.py:105-110`
- Modify: `src/pipeline_generator/wizard/flow.py:169-188`
- Test: `tests/test_validation.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: nothing later tasks call directly — `wlrun_path` is read straight off `config["tool"]["connection"]` by Task 2's renderer, the same pattern JMeter's `jmeter_bin` already uses.

- [ ] **Step 1: Write the failing validation test**

Add to `tests/test_validation.py`:

```python
def test_validation_does_not_warn_about_optional_wlrun_path() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-loadrunner-setup"
    config["setup"]["target_repository"] = "https://example.com/repo.git"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "loadrunner_professional"
    config["tool"]["auth"]["type"] = "none"
    config["tool"]["connection"] = {}
    config["catalog"]["environments"] = [{"key": "qa", "name": "QA", "identifier": "QA"}]
    config["catalog"]["scenarios"] = [
        {
            "key": "checkout_smoke_qa",
            "name": "Checkout Smoke (QA)",
            "identifier": "C:\\Scenarios\\checkout_smoke_qa.lrs",
        }
    ]

    result = validate_config(config)

    assert not any("wlrun_path" in warning for warning in result.warnings)
    assert not any("controller_host" in warning for warning in result.warnings)
```

- [ ] **Step 2: Run it and confirm it currently fails**

Run: `python3 -m pytest -q tests/test_validation.py::test_validation_does_not_warn_about_optional_wlrun_path -v`
Expected: FAIL — the current `validator.py` still warns about missing `controller_host`/`controller_results_path` for any `loadrunner_professional` config, so `not any("controller_host" in warning ...)` fails.

- [ ] **Step 3: Remove the stale validator block**

In `src/pipeline_generator/config/validator.py`, delete this block entirely (currently lines 105-110):

```python
    if tool_type == "loadrunner_professional":
        connection = tool.get("connection", {})
        for key in ["controller_host", "controller_results_path"]:
            value = connection.get(key)
            if is_placeholder(value):
                result.warnings.append(f"tool.connection.{key} is missing for LoadRunner Professional.")
```

`wlrun_path` is optional with a code-level default (`"wlrun"`, applied in Task 2's renderer), exactly like JMeter's `jmeter_bin` — which has no equivalent validator block — so no replacement warning logic is needed. The `.lrs` scenario file paths are already covered by the existing generic "catalog identifier missing/placeholder" warning a few lines above this block (`catalog.scenarios.<key>.identifier is missing.`), which applies to every tool already.

- [ ] **Step 4: Run the test again to confirm it passes**

Run: `python3 -m pytest -q tests/test_validation.py -v`
Expected: all tests in the file PASS, including the new one.

- [ ] **Step 5: Replace the wizard's LoadRunner connection prompts**

In `src/pipeline_generator/wizard/flow.py`, replace this block (currently lines 172-188):

```python
    if tool_type == "loadrunner_professional":
        connection["controller_host"] = prompt_text(
            "LoadRunner controller host",
            default=connection.get("controller_host", TODO_VALUE),
        ) or TODO_VALUE
        connection["controller_results_path"] = prompt_text(
            "LoadRunner results path on controller",
            default=connection.get("controller_results_path", TODO_VALUE),
        ) or TODO_VALUE
        connection["domain"] = prompt_text(
            "Optional LoadRunner domain",
            default=connection.get("domain", ""),
        )
        connection["project"] = prompt_text(
            "Optional LoadRunner project",
            default=connection.get("project", ""),
        )
```

with:

```python
    if tool_type == "loadrunner_professional":
        connection["wlrun_path"] = prompt_text(
            "Optional path to the wlrun executable (blank uses PATH)",
            default=connection.get("wlrun_path", ""),
        )
```

This mirrors the existing JMeter block a few lines below (`connection["jmeter_bin"] = prompt_text("Optional path to the jmeter executable (blank uses PATH)", default=connection.get("jmeter_bin", ""))`) exactly in shape.

- [ ] **Step 6: Manually verify the wizard prompt**

There is no automated wizard test in this project yet (confirmed: no `tests/*wizard*` file exists), so verify by hand:

```bash
printf 'n\ngithub_actions\nloadrunner_professional\nusername_password\ny\nacme/storefront\n\n\n\nwlrun\nn\nn\ny\nPerformance Manual Run\n30\nn\nn\n' | \
  python3 -m pipeline_generator.cli wizard --output /tmp/lr-wizard-check.yaml
grep -A2 "connection:" /tmp/lr-wizard-check.yaml
```

Confirm the printed YAML's `tool.connection` contains only `wlrun_path: wlrun` (or is empty if you pressed Enter for blank) — no `controller_host`/`controller_results_path`/`domain`/`project` keys. Clean up with `rm /tmp/lr-wizard-check.yaml` when done. (Exact prompt count/order may need adjusting if the wizard's earlier steps changed since this plan was written — if the piped answers don't line up, run the wizard interactively instead: `python3 -m pipeline_generator.cli wizard --output /tmp/lr-wizard-check.yaml` and answer prompts by hand, watching for the "Optional path to the wlrun executable" prompt in place of the old four LoadRunner prompts.)

- [ ] **Step 7: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (32 tests — 31 existing + 1 new).

- [ ] **Step 8: Commit**

```bash
git add src/pipeline_generator/config/validator.py src/pipeline_generator/wizard/flow.py tests/test_validation.py
git commit -m "Replace LoadRunner's remote-connection config with wlrun_path

controller_host/controller_results_path/domain/project were placeholders
from before an execution strategy was decided. The wizard now prompts for
a single optional wlrun_path (mirroring JMeter's jmeter_bin), and the
validator's stale warning block for the removed fields is deleted."
```

---

### Task 2: Real LoadRunner script rendering

**Files:**
- Modify: `src/pipeline_generator/renderers/scripts.py:160-186` (replaces `_render_loadrunner_script`'s body; `_render_blazemeter_script` and `_render_template_script` are untouched)
- Test: `tests/test_tool_scripts.py`

**Interfaces:**
- Consumes: `config["tool"]["connection"]["wlrun_path"]` (optional, from Task 1), `_allowed_pre_run_checks(config)`, `_render_resolvers(package)`, `_render_arg_parsing()` (all already defined in `scripts.py`), `shell_quote` (from `renderers/quoting.py`).
- Produces: nothing new consumed elsewhere — `render_tool_script`'s existing dispatch (`elif tool_type == "loadrunner_professional": content = _render_loadrunner_script(config, package)`) is unchanged; only what that function returns changes.

- [ ] **Step 1: Replace the old template-based test with new real-execution tests**

In `tests/test_tool_scripts.py`, delete `test_render_loadrunner_professional_script_is_a_template` (the whole function, currently the last function in the file) and replace it with:

```python
def test_render_loadrunner_script_runs_wlrun_for_real(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    package = build_generic_package(config)

    outputs = render_tool_script(config, package, tmp_path)

    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"
    assert outputs == [str(script_path)]
    assert script_path.exists()
    assert script_path.stat().st_mode & 0o111 == 0o111

    content = script_path.read_text(encoding="utf-8")
    assert "resolve_environment_identifier() {" in content
    assert "resolve_scenario_identifier() {" in content
    assert "local wlrun_path=wlrun" in content
    assert 'local results_dir="run-output/${environment_key}_${scenario_key}"' in content
    assert '"$wlrun_path" -Run -TestPath "$scenario_identifier" -ResultName "$results_dir"' in content
    assert "not implemented in this generated script yet" not in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_loadrunner_script_checks_wlrun_availability_when_configured(tmp_path: Path) -> None:
    config = _base_config(
        "loadrunner_professional", {"wlrun_path": "wlrun"}, checks=["verify_controller_access"]
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-loadrunner_professional.sh").read_text(encoding="utf-8")

    assert 'if ! command -v "$wlrun_path" >/dev/null 2>&1; then' in content
    assert 'echo "ERROR: wlrun not found: $wlrun_path" >&2' in content


def test_render_loadrunner_script_omits_wlrun_check_when_not_configured(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"}, checks=[])
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-loadrunner_professional.sh").read_text(encoding="utf-8")

    assert "wlrun not found" not in content


def test_render_loadrunner_script_checks_scenario_exists_when_configured(tmp_path: Path) -> None:
    config = _base_config(
        "loadrunner_professional", {"wlrun_path": "wlrun"}, checks=["verify_scenario_exists"]
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-loadrunner_professional.sh").read_text(encoding="utf-8")

    assert 'if [ ! -f "$scenario_identifier" ]; then' in content
    assert 'echo "Scenario file not found: $scenario_identifier" >&2' in content


def test_render_loadrunner_script_omits_scenario_check_when_not_configured(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"}, checks=[])
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-loadrunner_professional.sh").read_text(encoding="utf-8")

    assert "Scenario file not found" not in content


def test_render_loadrunner_script_quotes_wlrun_path_with_spaces(tmp_path: Path) -> None:
    config = _base_config(
        "loadrunner_professional", {"wlrun_path": "C:\\Program Files\\LoadRunner\\bin\\wlrun.exe"}
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"
    content = script_path.read_text(encoding="utf-8")

    # shlex.quote wraps a value containing spaces in single quotes; it
    # leaves backslashes untouched since they have no special meaning
    # inside single quotes in POSIX shell.
    assert "local wlrun_path='C:\\Program Files\\LoadRunner\\bin\\wlrun.exe'" in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_loadrunner_script_defaults_wlrun_path_when_blank(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": ""})
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-loadrunner_professional.sh").read_text(encoding="utf-8")

    assert "local wlrun_path=wlrun" in content
```

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `python3 -m pytest -q tests/test_tool_scripts.py -v`
Expected: FAIL — the new tests reference script content (`wlrun_path`, `results_dir`, the real `wlrun -Run ...` call) that the current `_render_loadrunner_script` (which delegates to the generic `_render_template_script`) does not produce.

- [ ] **Step 3: Replace `_render_loadrunner_script`'s implementation**

In `src/pipeline_generator/renderers/scripts.py`, replace this function (currently lines 174-186):

```python
def _render_loadrunner_script(config: dict, package: GenericPipelinePackage) -> str:
    connection = config.get("tool", {}).get("connection", {})
    return _render_template_script(
        config,
        package,
        "LoadRunner Professional",
        {
            "CONTROLLER_HOST": connection.get("controller_host") or TODO_VALUE,
            "CONTROLLER_RESULTS_PATH": connection.get("controller_results_path") or TODO_VALUE,
            "DOMAIN": connection.get("domain") or "",
            "PROJECT": connection.get("project") or "",
        },
    )
```

with:

```python
def _render_loadrunner_script(config: dict, package: GenericPipelinePackage) -> str:
    connection = config.get("tool", {}).get("connection", {})
    wlrun_path = connection.get("wlrun_path") or "wlrun"
    checks = _allowed_pre_run_checks(config)

    controller_check = ""
    if "verify_controller_access" in checks:
        controller_check = """
  if ! command -v "$wlrun_path" >/dev/null 2>&1; then
    echo "ERROR: wlrun not found: $wlrun_path" >&2
    exit 1
  fi
"""

    scenario_check = ""
    if "verify_scenario_exists" in checks:
        scenario_check = """
  if [ ! -f "$scenario_identifier" ]; then
    echo "Scenario file not found: $scenario_identifier" >&2
    exit 1
  fi
"""

    return f"""#!/usr/bin/env bash
set -euo pipefail

{_render_resolvers(package)}

main() {{
{_render_arg_parsing()}
  mkdir -p run-output

  local wlrun_path={shell_quote(wlrun_path)}
{controller_check}{scenario_check}
  local results_dir="run-output/${{environment_key}}_${{scenario_key}}"
  mkdir -p "$results_dir"

  # wlrun's exit code is known to be unreliable on some LoadRunner
  # versions/configurations (it can return 0 even when a scenario had
  # errors). We treat nonzero as failure since it is the best signal
  # available locally; check the results directory's own reports for the
  # authoritative pass/fail status.
  "$wlrun_path" -Run -TestPath "$scenario_identifier" -ResultName "$results_dir"
}}

if [ "${{BASH_SOURCE[0]:-$0}}" = "$0" ]; then
  main "$@"
fi
"""
```

`_render_template_script` (used by `_render_blazemeter_script`) and the `TODO_VALUE` import stay in the file — do not remove them, BlazeMeter's script still uses both.

- [ ] **Step 4: Run the tests again to confirm they pass**

Run: `python3 -m pytest -q tests/test_tool_scripts.py -v`
Expected: all PASS (12 tests in this file — the file had 7 before this task; 1 of those, the old template test, was deleted and replaced by 6 new ones, so 7 - 1 + 6 = 12).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pipeline_generator/renderers/scripts.py tests/test_tool_scripts.py
git commit -m "Make LoadRunner Professional's generated script real

Replaces the template stub (which always ended in 'execution is not
implemented yet' / exit 1) with a real wlrun invocation, assuming the CI
job runs on an agent co-located with the LoadRunner Controller. A
scenario's catalog identifier is now expected to be a full .lrs file
path, since wlrun has no native environment parameter the way JMeter's
-J properties do. verify_controller_access and verify_scenario_exists
are both real, gated checks now, matching JMeter's pattern."
```

---

### Task 3: Generated README no longer promises a LoadRunner TODO

**Files:**
- Modify: `src/pipeline_generator/renderers/readme.py:14`
- Test: `tests/test_readme_renderer.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing consumed elsewhere.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_readme_renderer.py`:

```python
def test_readme_mentions_loadrunner_script_without_todo_api_call() -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)

    assert "scripts/run-loadrunner_professional.sh" in readme
    assert "Fill in the actual API/controller call" not in readme
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m pytest -q tests/test_readme_renderer.py -v`
Expected: FAIL — `render_setup_readme` currently still adds the "Fill in the actual API/controller call" TODO line for `loadrunner_professional`.

- [ ] **Step 3: Move `loadrunner_professional` out of the TODO-API-call set**

In `src/pipeline_generator/renderers/readme.py`, change:

```python
    if tool_type in {"blazemeter", "loadrunner_professional"}:
```

to:

```python
    if tool_type == "blazemeter":
```

(The `else` branch's generic "Implement remote tool connectivity details required by the target customer." line now applies to both `jmeter` and `loadrunner_professional`.)

- [ ] **Step 4: Run the tests again to confirm they pass**

Run: `python3 -m pytest -q tests/test_readme_renderer.py -v`
Expected: all PASS (3 tests — 2 existing + 1 new).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pipeline_generator/renderers/readme.py tests/test_readme_renderer.py
git commit -m "Drop LoadRunner from the generated README's TODO-API-call line

Now that LoadRunner Professional's generated script is real (previous
task), leaving it in the same TODO-API-call bucket as BlazeMeter would
print a misleading TODO in every generated LoadRunner setup's README."
```

---

### Task 4: Migrate the three LoadRunner example configs

**Files:**
- Modify: `examples/github-loadrunner/customer.yaml`
- Modify: `examples/azure-loadrunner/customer.yaml`
- Modify: `examples/jenkins-loadrunner/customer.yaml`

**Interfaces:**
- Consumes: the new config shape from Tasks 1-2 (`tool.connection.wlrun_path`, `.lrs`-path scenario identifiers).
- Produces: nothing consumed by later tasks — `tests/test_example_configs.py` (already existing, generic over every file under `examples/`) is the verification, not something this task edits.

- [ ] **Step 1: Rewrite `examples/github-loadrunner/customer.yaml`**

Replace the entire file with:

```yaml
version: 1
incomplete: false
setup:
  id: github-actions-loadrunner-professional-storefront
  working_location: central_repo
  final_pipeline_destination: copy_to_customer_repo
  ci_can_use_central_repo_directly: false
  target_repository: github.com/acme/storefront
  generation_mode: both
cicd:
  type: github_actions
tool:
  type: loadrunner_professional
  auth:
    type: none
  connection:
    wlrun_path: wlrun
manual_pipeline:
  enabled: true
  name: Performance Manual Run
  timeout_minutes: 240
automated_jobs:
  - name: post-deploy-smoke
    enabled: true
    environment_ref: qa
    scenario_ref: checkout_smoke_qa
    timeout_minutes: 90
catalog:
  environments:
    - key: qa
      name: QA
      identifier: QA
    - key: staging
      name: Staging
      identifier: Staging
  scenarios:
    - key: checkout_smoke_qa
      name: Checkout Smoke (QA)
      identifier: C:\Scenarios\checkout_smoke_qa.lrs
    - key: checkout_smoke_staging
      name: Checkout Smoke (Staging)
      identifier: C:\Scenarios\checkout_smoke_staging.lrs
    - key: browse_baseline_qa
      name: Browse Baseline (QA)
      identifier: C:\Scenarios\browse_baseline_qa.lrs
    - key: browse_baseline_staging
      name: Browse Baseline (Staging)
      identifier: C:\Scenarios\browse_baseline_staging.lrs
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

- [ ] **Step 2: Rewrite `examples/jenkins-loadrunner/customer.yaml`**

Same as Step 1's content, except:
- `setup.id: jenkins-loadrunner-professional-storefront`
- `cicd.type: jenkins`

(everything else — `tool`, `manual_pipeline`, `automated_jobs`, `catalog`, `pre_run_checks`, `artifacts`, `readme` — identical to the github version above, matching how these two files were already identical except for `setup.id`/`cicd.type` before this change).

- [ ] **Step 3: Rewrite `examples/azure-loadrunner/customer.yaml`**

Replace the entire file with:

```yaml
version: 1
incomplete: false
setup:
  id: azure-devops-loadrunner-professional-storefront
  working_location: central_repo
  final_pipeline_destination: copy_to_customer_repo
  ci_can_use_central_repo_directly: false
  target_repository: dev.azure.com/acme/storefront
  generation_mode: both
cicd:
  type: azure_devops
tool:
  type: loadrunner_professional
  auth:
    type: none
  connection:
    wlrun_path: wlrun
manual_pipeline:
  enabled: true
  name: Azure Performance Manual Run
  timeout_minutes: 240
automated_jobs:
  - name: release-check
    enabled: true
    environment_ref: prod
    scenario_ref: prod_release_validation
    timeout_minutes: 180
catalog:
  environments:
    - key: prod
      name: Production
      identifier: Production
  scenarios:
    - key: prod_release_validation
      name: Prod Release Validation
      identifier: C:\Scenarios\prod_release_validation.lrs
pre_run_checks:
  - verify_controller_access
  - verify_scenario_exists
  - collect_results
artifacts:
  download_remote_results: true
  fail_on_partial_download: false
readme:
  include_manual_usage: true
  include_automated_usage: true
```

(This example intentionally keeps a single environment/scenario pair — `checkout_smoke_qa`/`checkout_smoke_staging` in the GitHub/Jenkins examples above already exercises the per-environment `.lrs` convention with two environments, so this file doesn't also need to grow a second environment just to prove the same point.)

- [ ] **Step 4: Run the example-config test suite**

Run: `python3 -m pytest -q tests/test_example_configs.py -v`
Expected: PASS — this test validates and generates every file under `examples/`, so it exercises the new shape through `validate_config` and `generate_assets` end-to-end without any test code changes needed.

- [ ] **Step 5: Manually smoke-test one example's generated output**

```bash
rm -rf /tmp/lr-gen-check
python3 -m pipeline_generator.cli generate --config examples/github-loadrunner/customer.yaml --output-dir /tmp/lr-gen-check
cat /tmp/lr-gen-check/*/scripts/run-loadrunner_professional.sh
rm -rf /tmp/lr-gen-check
```

Confirm the printed script contains `wlrun -Run -TestPath` (not `"... execution is not implemented in this generated script yet."`), and that `resolve_scenario_identifier` resolves `checkout_smoke_qa` to `C:\Scenarios\checkout_smoke_qa.lrs`.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add examples/github-loadrunner/customer.yaml examples/azure-loadrunner/customer.yaml examples/jenkins-loadrunner/customer.yaml
git commit -m "Migrate LoadRunner example configs to the wlrun_path shape

Drops controller_host/controller_results_path/domain/project, adds
wlrun_path, reshapes scenario catalogs into per-environment .lrs file
paths, and sets tool.auth.type to none (the generated script manages no
remote credential itself, same as JMeter)."
```

---

### Task 5: Update project documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `docs/current-state-and-readiness-plan.md`
- Modify: `docs/pipeline-generator-user-guide.md`

**Interfaces:**
- Consumes: the final state of Tasks 1-4 (this task only describes what already shipped; do not start Task 5 before Tasks 1-4 are committed).
- Produces: nothing — this is the last task in the plan.

- [ ] **Step 1: Update `CLAUDE.md`**

Replace this passage (search for `` `blazemeter` and `loadrunner_professional`, the script is a template``):

```
`jmeter -n -t <test_plan_path> -l run-output/results.jtl -e -o
  run-output/report -Jenvironment=... -Jscenario=...` for real. For
  `blazemeter` and `loadrunner_professional`, the script is a template, not
  a stub: it's real, syntactically valid bash with the connection details
  (`base_url`/`workspace_id`/`project_id`, or `controller_host`/
  `controller_results_path`/`domain`/`project`) already filled in as
  variables, remaining `pre_run_checks` listed as `# TODO precheck: ...`
  comments, and it ends with
  `echo "ERROR: <Tool> execution is not implemented in this generated
  script yet." >&2` and `exit 1` — same honest not-done-yet stance the old
  Python adapters had, just expressed as shell instead of
  `NotImplementedError`. JMeter runs locally (no remote API/credentials), so
  its `tool.auth.type` is `none` — see `AUTH_TYPES` in `config/schema.py`.
```

with:

```
`jmeter -n -t <test_plan_path> -l run-output/results.jtl -e -o
  run-output/report -Jenvironment=... -Jscenario=...` for real.
  `loadrunner_professional` is also real: it assumes the CI job runs on a
  dedicated agent co-located with the LoadRunner Controller (so
  `wlrun.exe` is already on the box) and runs `wlrun -Run -TestPath
  <scenario_identifier> -ResultName
  run-output/<environment_key>_<scenario_key>` — since `wlrun` has no
  native "environment" parameter, a scenario's catalog `identifier` is a
  full `.lrs` file path (customers author one catalog scenario entry per
  environment/scenario combination they have a file for), and the
  environment only names the results folder. `wlrun`'s exit code is known
  to be unreliable on some LoadRunner versions (can return 0 on a failed
  scenario); nonzero is still treated as failure as the best local signal
  available. For `blazemeter`, the script remains a template, not a stub:
  it's real, syntactically valid bash with the connection details
  (`base_url`/`workspace_id`/`project_id`) already filled in as variables,
  remaining `pre_run_checks` listed as `# TODO precheck: ...` comments, and
  it ends with
  `echo "ERROR: BlazeMeter execution is not implemented in this generated
  script yet." >&2` and `exit 1` — same honest not-done-yet stance the old
  Python adapters had, just expressed as shell instead of
  `NotImplementedError`. JMeter and LoadRunner Professional both run
  locally/on-agent (no remote API credentials managed by this script), so
  their `tool.auth.type` is `none` — see `AUTH_TYPES` in `config/schema.py`.
```

Also replace (search for `filling in the BlazeMeter/LoadRunner Professional script`):

```
See `docs/current-state-and-readiness-plan.md` for the full known-gaps list
and multi-milestone readiness plan (stricter validation profiles, YAML-safe
renderer output, filling in the BlazeMeter/LoadRunner Professional script
templates) if working on hardening this project further.
```

with:

```
See `docs/current-state-and-readiness-plan.md` for the full known-gaps list
and multi-milestone readiness plan (stricter validation profiles, YAML-safe
renderer output, filling in the BlazeMeter script template) if working on
hardening this project further.
```

- [ ] **Step 2: Update `README.md`**

Replace (search for `- BlazeMeter and LoadRunner Professional — a real shell script`):

```
  - JMeter — a real, working script that runs `jmeter -n -t ...` against the
    configured test plan.
  - BlazeMeter and LoadRunner Professional — a real shell script with
    connection details already filled in, but the actual API/controller call
    is left as a `# TODO` for now (it exits 1 with a clear error until
    someone fills that in).
```

with:

```
  - JMeter — a real, working script that runs `jmeter -n -t ...` against the
    configured test plan.
  - LoadRunner Professional — a real, working script that runs `wlrun -Run
    -TestPath ...` locally, assuming the CI job runs on an agent co-located
    with the LoadRunner Controller.
  - BlazeMeter — a real shell script with connection details already filled
    in, but the actual API call is left as a `# TODO` for now (it exits 1
    with a clear error until someone fills that in).
```

Replace (search for `- BlazeMeter and LoadRunner Professional get a template script`):

```
- `generate` writes a real, working `scripts/run-jmeter.sh` for JMeter setups
- BlazeMeter and LoadRunner Professional get a template script with
  connection details filled in and the actual API/controller call left as a
  `# TODO` — running it prints a clear "not implemented yet" error and exits
  non-zero
```

with:

```
- `generate` writes a real, working `scripts/run-jmeter.sh` for JMeter
  setups and `scripts/run-loadrunner_professional.sh` for LoadRunner
  Professional setups (assumes the CI job runs on an agent co-located with
  the LoadRunner Controller)
- BlazeMeter gets a template script with connection details filled in and
  the actual API call left as a `# TODO` — running it prints a clear "not
  implemented yet" error and exits non-zero
```

Replace (search for `For BlazeMeter and LoadRunner Professional it's a template: connection`):

```
Generation is the tool's last step: it never triggers or contacts a
performance test itself. Alongside the CI/CD files and `customer.yaml`,
`generate` writes `scripts/run-<tool_type>.sh` — a real, executable script
that the generated pipeline's "Run performance wrapper" step calls directly
(e.g. `./scripts/run-jmeter.sh --environment "$ENVIRONMENT" --scenario
"$SCENARIO"`). For JMeter this script actually resolves the environment/
scenario to their catalog identifiers and runs `jmeter -n -t ...` for real.
For BlazeMeter and LoadRunner Professional it's a template: connection
details (base URL/workspace/project, or controller host/results path/
domain/project) are filled in, configured pre-run checks are listed as
`# TODO precheck: ...` comments, and it ends with a clear
`echo "ERROR: <Tool> execution is not implemented in this generated script
yet." >&2` and `exit 1` until someone fills in the actual API/controller
call.
```

with:

```
Generation is the tool's last step: it never triggers or contacts a
performance test itself. Alongside the CI/CD files and `customer.yaml`,
`generate` writes `scripts/run-<tool_type>.sh` — a real, executable script
that the generated pipeline's "Run performance wrapper" step calls directly
(e.g. `./scripts/run-jmeter.sh --environment "$ENVIRONMENT" --scenario
"$SCENARIO"`). For JMeter this script actually resolves the environment/
scenario to their catalog identifiers and runs `jmeter -n -t ...` for real.
LoadRunner Professional is also real: it assumes the CI job runs on a
dedicated agent co-located with the LoadRunner Controller, resolves
`--environment`/`--scenario` the same way, and runs `wlrun -Run -TestPath
<scenario_identifier> -ResultName run-output/<environment_key>_
<scenario_key>` — a scenario's catalog identifier is a full `.lrs` file
path rather than a remote name, since `wlrun` has no native "environment"
switch (see the user guide for the full catalog convention). For BlazeMeter
it's a template: connection details (base URL/workspace/project) are
filled in, configured pre-run checks are listed as `# TODO precheck: ...`
comments, and it ends with a clear
`echo "ERROR: BlazeMeter execution is not implemented in this generated
script yet." >&2` and `exit 1` until someone fills in the actual API call.
```

Replace the entire "Recommended Next Work" section:

```
## Recommended Next Work

- Fill in the real BlazeMeter API call in the generated `run-blazemeter.sh`
  template (`renderers/scripts.py`)
- Fill in the real LoadRunner Professional controller call in the generated
  `run-loadrunner_professional.sh` template
- Add a GitLab CI renderer
- Add non-interactive `generate` workflows around completed YAML inputs
```

with:

```
## Recommended Next Work

- Fill in the real BlazeMeter API call in the generated `run-blazemeter.sh`
  template (`renderers/scripts.py`)
- Add a GitLab CI renderer
- Add non-interactive `generate` workflows around completed YAML inputs
```

- [ ] **Step 3: Update `docs/current-state-and-readiness-plan.md`**

Replace (in the "Purpose" section, search for `for BlazeMeter and LoadRunner Professional it's a template with connection`):

```
At the current stage, the project is strongest as a generator for CI/CD setup
packages. `pipeline-generator` never executes a performance test itself — its
job ends at `generate`, which now writes a `scripts/run-<tool_type>.sh`
alongside the CI/CD files. That script is real, working execution for JMeter;
for BlazeMeter and LoadRunner Professional it's a template with connection
details filled in but the actual remote API/controller call still a `# TODO`.
```

with:

```
At the current stage, the project is strongest as a generator for CI/CD setup
packages. `pipeline-generator` never executes a performance test itself — its
job ends at `generate`, which now writes a `scripts/run-<tool_type>.sh`
alongside the CI/CD files. That script is real, working execution for JMeter
and LoadRunner Professional (the latter assumes the CI job runs on an agent
co-located with the LoadRunner Controller); for BlazeMeter it's a template
with connection details filled in but the actual remote API call still a
`# TODO`.
```

Replace the "Implemented" list's LoadRunner bullet (search for `template for BlazeMeter and LoadRunner Professional.`):

```
- A generated `scripts/run-<tool_type>.sh` per setup, written alongside the
  CI/CD files — real, working JMeter execution; a filled-in-but-TODO
  template for BlazeMeter and LoadRunner Professional.
```

with:

```
- A generated `scripts/run-<tool_type>.sh` per setup, written alongside the
  CI/CD files — real, working execution for JMeter and LoadRunner
  Professional; a filled-in-but-TODO template for BlazeMeter.
```

Replace the "Not implemented yet" list (search for `The real LoadRunner Professional controller call`):

```
- The real BlazeMeter API call in the generated `run-blazemeter.sh`
  template's `# TODO` block.
- The real LoadRunner Professional controller call in the generated
  `run-loadrunner_professional.sh` template's `# TODO` block.
- Real pre-run checks beyond JMeter's `verify_scenario_exists` (the
  generated script actually checks the test plan file exists for JMeter;
  every other configured check, for every tool, is currently only a
  `# TODO precheck: ...` comment in the BlazeMeter/LoadRunner templates —
  JMeter has no other checks defined).
```

with:

```
- The real BlazeMeter API call in the generated `run-blazemeter.sh`
  template's `# TODO` block.
- Real pre-run checks beyond JMeter's/LoadRunner Professional's
  `verify_scenario_exists` and LoadRunner Professional's
  `verify_controller_access` (every other configured check, for every
  tool, is currently only a `# TODO precheck: ...` comment in the
  BlazeMeter template, or — for LoadRunner's
  `verify_load_generators_connected` — in its own real script, since it
  needs Controller-side load-generator host-status querying with no local
  CLI equivalent).
```

Replace the "Performance Testing Tools" section (search for `BlazeMeter's and LoadRunner Professional's generated`):

```
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
```

with:

```
`generate` writes a `scripts/run-<tool_type>.sh` for every setup, but the
three tools aren't equally finished. JMeter's and LoadRunner Professional's
generated scripts are both real, working execution: JMeter resolves the
environment/scenario to their catalog identifiers and runs a real
`jmeter -n -t ...` subprocess (no remote API or credentials needed);
LoadRunner Professional does the same resolution and runs a real
`wlrun -Run -TestPath ...` subprocess, assuming the CI job runs on an agent
co-located with the LoadRunner Controller (see
`docs/superpowers/specs/2026-09-09-loadrunner-local-agent-execution-design.md`).
BlazeMeter's generated script is a template, not a stub: real,
syntactically valid bash with connection details already filled in as
variables and configured pre-run checks listed as `# TODO precheck: ...`
comments, but the actual remote API call is left undone — the script
prints a clear `"... execution is not implemented in this generated script
yet."` and exits non-zero until someone fills that part in.
```

Replace the "Generated Run Script" bullets (search for `For **BlazeMeter** and **LoadRunner Professional**, it's a template: real,`):

```
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
```

with:

```
- For **JMeter**, it's real and complete: it resolves `--environment`/
  `--scenario` to their catalog identifiers, optionally checks the test plan
  file exists first (if `verify_scenario_exists` is in `pre_run_checks`),
  then runs `jmeter -n -t <test_plan_path> -l run-output/results.jtl -e -o
  run-output/report -Jenvironment=... -Jscenario=...` for real.
- For **LoadRunner Professional**, it's also real and complete: it resolves
  `--environment`/`--scenario` the same way (a scenario's identifier is a
  full `.lrs` file path), optionally checks `wlrun_path` resolves to a
  runnable command and/or the `.lrs` file exists (`verify_controller_access`
  / `verify_scenario_exists`), then runs `wlrun -Run -TestPath
  <scenario_identifier> -ResultName run-output/<environment_key>_
  <scenario_key>` for real.
- For **BlazeMeter**, it's a template: real, syntactically valid bash with
  connection details already filled in as variables and remaining
  `pre_run_checks` listed as `# TODO precheck: ...` comments, ending with
  `echo "ERROR: BlazeMeter execution is not implemented in this generated
  script yet." >&2` and `exit 1`.
```

Replace the "Generated Script Execution Flow" step-4 bullets and the "Current limitation" paragraph (search for `- **BlazeMeter** / **LoadRunner Professional**: print each remaining`):

```
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
```

with:

```
4. Run the tool:
   - **JMeter**: optionally verify the test plan file exists (if
     `verify_scenario_exists` is configured), then run `jmeter -n -t ...`
     for real.
   - **LoadRunner Professional**: optionally verify `wlrun_path` is
     runnable and/or the resolved `.lrs` scenario file exists (if
     `verify_controller_access`/`verify_scenario_exists` are configured),
     then run `wlrun -Run -TestPath ...` for real.
   - **BlazeMeter**: print each remaining configured pre-run check as a
     `# TODO precheck: ...` comment (they are not executed), then print a
     clear "not implemented in this generated script yet" error and exit 1
     — the API call itself is not yet written.

Current limitation: the BlazeMeter script stops before calling any remote
API — see "BlazeMeter Script Is a Template, Not an Adapter" below for what's
needed to finish it.
```

Replace the whole "BlazeMeter and LoadRunner Professional Scripts Are Templates, Not Adapters — Partially Resolved" section (search for its heading through the end of its "Recommended change" bullet, i.e. up to but not including "### Test Coverage Is Minimal"):

```
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
```

with:

```
### BlazeMeter Script Is a Template, Not an Adapter — Partially Resolved

This gap used to be about Python `ToolAdapter` stubs (`adapters/`) that
defined the right shape but raised `NotImplementedError` for every tool. That
whole adapter/runtime subsystem has been deleted; there is no more Python
execution layer at all. In its place, `generate` writes a
`scripts/run-<tool_type>.sh` per setup:

- **JMeter is real, working execution** — resolved. The generated script
  resolves the environment/scenario and runs a real `jmeter -n -t <plan> -l
  <results> -e -o <report>` subprocess. Nothing left to do here.
- **LoadRunner Professional is also real, working execution** — resolved
  (see `docs/superpowers/specs/
  2026-09-09-loadrunner-local-agent-execution-design.md` for the design).
  It assumes the CI job runs on a dedicated agent co-located with the
  LoadRunner Controller, resolves the environment/scenario the same way
  JMeter does, and runs `wlrun -Run -TestPath <scenario_identifier>
  -ResultName run-output/<environment_key>_<scenario_key>` for real. A
  scenario's catalog `identifier` is a full `.lrs` file path rather than a
  remote name, since `wlrun` has no native "environment" parameter —
  customers author one catalog scenario entry per environment/scenario
  combination they have a file for. `wlrun`'s exit code is known to be
  unreliable on some LoadRunner versions/configurations (can return 0 on a
  failed scenario); nonzero is still treated as failure as the best local
  signal available.
- **BlazeMeter remains unimplemented**, but as a template rather than a
  stub: the generated script is real, syntactically valid bash with
  connection details already filled in as variables and configured
  pre-run checks listed as `# TODO precheck: ...` comments — it just stops
  short of the actual API call, printing a clear `"... execution is not
  implemented in this generated script yet."` and exiting 1.

Risk:

- The generated pipeline calls `./scripts/run-blazemeter.sh` directly, and
  that call will always fail with the "not implemented yet" error until
  someone fills in the template.

Recommended change:

- Fill in the BlazeMeter template, directly in `renderers/scripts.py`'s
  `_render_template_script` (or by hand-editing the generated script for a
  one-off setup). It's API-driven, so no open execution-strategy decision
  blocks it the way LoadRunner's did.
```

Replace the "Milestone 2" intro paragraph (search for `the remaining work here is entirely`):

```
Milestone 2 used to be framed around implementing Python `ToolAdapter`
subclasses. There is no more Python adapter layer — the implementation
surface for everything below is now `renderers/scripts.py`'s
`_render_template_script` (which produces the generated
`scripts/run-<tool_type>.sh`), not a runtime module. JMeter's generated
script is already real and complete (`[x]`, see the Recommended
Implementation Order list below) — the remaining work here is entirely
BlazeMeter and LoadRunner Professional.
```

with:

```
Milestone 2 used to be framed around implementing Python `ToolAdapter`
subclasses. There is no more Python adapter layer — the implementation
surface for everything below is now `renderers/scripts.py` (JMeter and
LoadRunner Professional have their own real renderer functions;
BlazeMeter still uses the generic `_render_template_script` template-stub
helper). JMeter's and LoadRunner Professional's generated scripts are
already real and complete (`[x]`, see the Recommended Implementation
Order list below) — the remaining work here is entirely BlazeMeter.
```

Replace the whole "### 2. Define LoadRunner Execution Strategy" section (search for its heading through the end of its Tasks list, i.e. up to but not including "### 3. Implement Real Pre-Run Checks"):

```
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
```

with:

```
### 2. Define LoadRunner Execution Strategy — Resolved

Resolved: the generated script assumes the CI job runs on a dedicated
Jenkins/Azure self-hosted agent co-located with the LoadRunner Controller
(so `wlrun.exe` is already on the box) and calls `wlrun` directly — no
remoting, no SSH/WinRM, no LoadRunner Enterprise REST API. See
`docs/superpowers/specs/2026-09-09-loadrunner-local-agent-execution-design.md`
for the full design, including the alternatives considered and rejected.
```

Replace the "### 3. Implement Real Pre-Run Checks" Tasks list (search for `- Implement \`verify_controller_access\` in the generated LoadRunner`):

```
- [x] `verify_scenario_exists` is implemented for JMeter (the generated
  script checks the test plan file exists before running).
- Implement `verify_controller_access` in the generated LoadRunner
  Professional script (currently a `# TODO precheck: ...` comment only).
- Implement `verify_scenario_exists` for BlazeMeter/LoadRunner Professional
  (currently a `# TODO precheck: ...` comment only).
- Implement `verify_load_generators_connected` in the generated LoadRunner
  Professional script (currently a `# TODO precheck: ...` comment only).
```

with:

```
- [x] `verify_scenario_exists` is implemented for JMeter (the generated
  script checks the test plan file exists before running).
- [x] `verify_controller_access` is implemented for LoadRunner Professional
  (checks `wlrun_path` resolves to a runnable command).
- [x] `verify_scenario_exists` is implemented for LoadRunner Professional
  (checks the resolved `.lrs` scenario file exists before running).
- Implement `verify_controller_access`/`verify_scenario_exists` for
  BlazeMeter (currently `# TODO precheck: ...` comments only).
- Implement `verify_load_generators_connected` in the generated LoadRunner
  Professional script (currently a `# TODO precheck: ...` comment only —
  needs Controller-side load-generator host-status querying with no local
  CLI equivalent available to `wlrun`).
```

Replace "Recommended Implementation Order" items 12-13 (search for `- \[ \] 12. Decide the LoadRunner Professional remote-execution strategy`):

```
- [ ] 12. Decide the LoadRunner Professional remote-execution strategy and
      fill in the real controller call in the generated
      `run-loadrunner_professional.sh` template.
- [ ] 13. Replace the remaining `# TODO precheck: ...` comments in the
      BlazeMeter/LoadRunner Professional templates with real checks.
```

with:

```
- [x] 12. Decide the LoadRunner Professional execution strategy (a
      dedicated agent co-located with the controller, calling `wlrun`
      directly) and fill in the real call in the generated
      `run-loadrunner_professional.sh` script (see
      `docs/superpowers/specs/
      2026-09-09-loadrunner-local-agent-execution-design.md`).
- [ ] 13. Replace the remaining `# TODO precheck: ...` comments in the
      BlazeMeter template with real checks (LoadRunner Professional's
      `verify_controller_access`/`verify_scenario_exists` are now real;
      `verify_load_generators_connected` remains a `# TODO precheck: ...`
      comment for LoadRunner too, since it needs Controller-side
      load-generator host-status querying with no local CLI equivalent).
```

Replace the "Definition of Ready" paragraph about BlazeMeter/LoadRunner (search for `The BlazeMeter and LoadRunner Professional generated scripts can be`):

```
The BlazeMeter and LoadRunner Professional generated scripts can be
considered ready for executing tests when:

- At least one of the two can start, monitor, and collect artifacts from a
  remote test run for real (JMeter's generated script already does this).
- Failed runs produce clear summary output.
- Timeout and partial artifact cases are handled.
- Secrets and credentials are documented.
- The generated script's real-execution behavior is covered by automated
  tests using mocks or test doubles.
```

with:

```
The BlazeMeter and LoadRunner Professional generated scripts can be
considered ready for executing tests when:

- [x] At least one of the two can start and run a test for real — resolved:
  LoadRunner Professional's generated script now runs `wlrun` directly
  against a controller-adjacent agent. BlazeMeter's remains a template.
- Failed runs produce clear summary output (neither JMeter's nor
  LoadRunner's generated script writes one yet — see Milestone 2 item 4,
  "Normalize Runtime Output").
- Timeout and partial artifact cases are handled (LoadRunner relies
  entirely on the CI job's own timeout and `wlrun`'s own exit code, same as
  JMeter; no script-level timeout/retry logic exists for either).
- Secrets and credentials are documented — N/A for LoadRunner (it manages
  no remote credentials at all, same as JMeter); still open for BlazeMeter.
- The generated script's real-execution behavior is covered by automated
  tests using mocks or test doubles (still open for both — "Recommended
  Implementation Order" item 14).
```

- [ ] **Step 4: Update `docs/pipeline-generator-user-guide.md`**

Replace (search for `For JMeter it's real and complete — it resolves the environment/`):

```
- **`scripts/run-<tool>.sh`** is the one real step every generated pipeline
  calls to do its work (e.g. `./scripts/run-jmeter.sh --environment "$ENV"
  --scenario "$SCENARIO"`). It's a plain bash script with no dependency on
  `pipeline-generator` or Python at all, so it runs the same way whether the
  CI/CD platform's job that calls it happens to have this tool installed or
  not. For JMeter it's real and complete — it resolves the environment/
  scenario to their catalog identifiers and actually runs `jmeter`. For
  BlazeMeter and LoadRunner Professional it's a template — connection
  details are filled in, but the actual API/controller call is left as a
  `# TODO`, so running it today prints a clear error and exits non-zero
  (section 10 has the details). You can also run it by hand from a checkout
  of the generated setup, without going through the CI/CD platform, to test
  it before committing anything.
```

with:

```
- **`scripts/run-<tool>.sh`** is the one real step every generated pipeline
  calls to do its work (e.g. `./scripts/run-jmeter.sh --environment "$ENV"
  --scenario "$SCENARIO"`). It's a plain bash script with no dependency on
  `pipeline-generator` or Python at all, so it runs the same way whether the
  CI/CD platform's job that calls it happens to have this tool installed or
  not. For JMeter and LoadRunner Professional it's real and complete — it
  resolves the environment/scenario to their catalog identifiers and
  actually runs `jmeter`/`wlrun`. For BlazeMeter it's a template —
  connection details are filled in, but the actual API call is left as a
  `# TODO`, so running it today prints a clear error and exits non-zero
  (section 10 has the details). You can also run it by hand from a checkout
  of the generated setup, without going through the CI/CD platform, to test
  it before committing anything.
```

Replace the wizard's Step 4 LoadRunner table (search for `| \`controller_host\` | Required. |`):

```
**LoadRunner Professional:**

| Field | Notes |
|---|---|
| `controller_host` | Required. |
| `controller_results_path` | Required — where results land on the controller (e.g. `C:\Results`). |
| `domain` | Optional. |
| `project` | Optional. |
```

with:

```
**LoadRunner Professional:**

| Field | Notes |
|---|---|
| `wlrun_path` | Optional — path to the `wlrun` executable; blank uses `PATH`. Assumes the CI job runs on an agent co-located with the LoadRunner Controller (see section 10). |

Catalog scenario entries for LoadRunner Professional use a full `.lrs`
scenario file path as their `identifier` (one entry per environment/
scenario combination), rather than a remote name — see section 10 for why.
```

Replace the generated-script Step 4 bullets (search for `- **BlazeMeter** and **LoadRunner Professional** — a template. The`):

```
- **BlazeMeter** and **LoadRunner Professional** — a template. The
  connection details from `tool.connection` (e.g. `base_url`/
  `workspace_id`/`project_id`, or `controller_host`/
  `controller_results_path`/`domain`/`project`) are already filled in as
  shell variables, any configured `pre_run_checks` are listed as
  `# TODO precheck: ...` comments, and the script ends with:

  ```
  ERROR: BlazeMeter execution is not implemented in this generated script yet.
  Fill in the API/controller call using the variables above.
  ```

  (or the equivalent for LoadRunner Professional), then exits 1. See
  section 10 for what's needed to finish either one for real.
```

with:

```
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

- **BlazeMeter** — a template. The connection details from
  `tool.connection` (`base_url`/`workspace_id`/`project_id`) are already
  filled in as shell variables, any configured `pre_run_checks` are listed
  as `# TODO precheck: ...` comments, and the script ends with:

  ```
  ERROR: BlazeMeter execution is not implemented in this generated script yet.
  Fill in the API call using the variables above.
  ```

  then exits 1. See section 10 for what's needed to finish it for real.
```

Replace the whole section 10 (search for `## 10. Performance Testing Tools` through the end of its table, i.e. up to but not including `## 11. Validating Configs`):

```
## 10. Performance Testing Tools

The config schema, wizard prompts, and validation all work end-to-end for
all three tools, and `generate` writes a `scripts/run-<tool_type>.sh` for
each — but they aren't all equally finished:

- **JMeter is real, working execution.** The generated script resolves the
  environment/scenario and runs `jmeter -n -t <test_plan_path> ...` for
  real, with no further work needed.
- **BlazeMeter and LoadRunner Professional are templates, not stubs.** The
  generated script is real, syntactically valid bash — connection details
  are filled in, `pre_run_checks` are listed as `# TODO precheck: ...`
  comments — but the actual API/controller call is left undone: it prints
  `ERROR: <Tool> execution is not implemented in this generated script yet.`
  and exits 1. Finishing either one means editing that `# TODO` block in the
  generated script (or, upstream, `renderers/scripts.py`'s
  `_render_template_script`) to make the real call. This is tracked at the
  top of the project's readiness roadmap (see
  `docs/current-state-and-readiness-plan.md`).

| Tool | Auth model | Connection fields | Generated script |
|---|---|---|---|
| **LoadRunner Professional** | Remote (`username_password`, etc.) | `controller_host`, `controller_results_path`, optional `domain`/`project` | Template — needs a remote-execution strategy decision (WinRM vs. SSH vs. dedicated agent) before the controller call can be filled in. |
| **BlazeMeter** | Remote (`api_token`, etc.) | `base_url`, `workspace_id`, `project_id` | Template — API-driven; the lower-effort of the two templates to finish. |
| **JMeter** | `none` (runs locally) | `test_plan_path`, optional `jmeter_bin` | Real and complete — no remote API or credentials needed, just a local `jmeter` subprocess call. |
```

with:

```
## 10. Performance Testing Tools

The config schema, wizard prompts, and validation all work end-to-end for
all three tools, and `generate` writes a `scripts/run-<tool_type>.sh` for
each — but they aren't all equally finished:

- **JMeter and LoadRunner Professional are real, working execution.** The
  generated script resolves the environment/scenario and runs `jmeter -n -t
  <test_plan_path> ...` or `wlrun -Run -TestPath <scenario_identifier> ...`
  for real, with no further work needed. LoadRunner Professional assumes
  the CI job runs on an agent co-located with the LoadRunner Controller —
  see `docs/superpowers/specs/
  2026-09-09-loadrunner-local-agent-execution-design.md` for the full
  design and why other execution strategies (SSH/WinRM remoting, LoadRunner
  Enterprise's REST API) were rejected.
- **BlazeMeter is a template, not a stub.** The generated script is real,
  syntactically valid bash — connection details are filled in,
  `pre_run_checks` are listed as `# TODO precheck: ...` comments — but the
  actual API call is left undone: it prints
  `ERROR: BlazeMeter execution is not implemented in this generated script
  yet.` and exits 1. Finishing it means editing that `# TODO` block in the
  generated script (or, upstream, `renderers/scripts.py`'s
  `_render_template_script`) to make the real call. This is tracked at the
  top of the project's readiness roadmap (see
  `docs/current-state-and-readiness-plan.md`).

| Tool | Auth model | Connection fields | Generated script |
|---|---|---|---|
| **LoadRunner Professional** | `none` (runs on a controller-adjacent agent) | optional `wlrun_path` | Real and complete — runs `wlrun` locally; no remote credentials managed by this script. |
| **BlazeMeter** | Remote (`api_token`, etc.) | `base_url`, `workspace_id`, `project_id` | Template — API-driven; no execution-strategy decision blocks it. |
| **JMeter** | `none` (runs locally) | `test_plan_path`, optional `jmeter_bin` | Real and complete — no remote API or credentials needed, just a local `jmeter` subprocess call. |
```

Replace the troubleshooting entry (search for `**"ERROR: BlazeMeter execution is not implemented`):

```
**"ERROR: BlazeMeter execution is not implemented in this generated script
yet." / "ERROR: LoadRunner Professional execution is not implemented in
this generated script yet."**
You ran the generated `scripts/run-blazemeter.sh` or
`run-loadrunner_professional.sh`. Both are templates (section 10) — the
connection details are filled in, but the actual API/controller call is
left as a `# TODO` in the script for someone to implement. JMeter's
generated script has no such gap.
```

with:

```
**"ERROR: BlazeMeter execution is not implemented in this generated script
yet."**
You ran the generated `scripts/run-blazemeter.sh`. It's a template
(section 10) — the connection details are filled in, but the actual API
call is left as a `# TODO` in the script for someone to implement.
JMeter's and LoadRunner Professional's generated scripts have no such gap.

**"ERROR: wlrun not found: ..."**
The generated `scripts/run-loadrunner_professional.sh` couldn't find the
configured `wlrun_path` on this machine. LoadRunner Professional's script
assumes it's running on an agent co-located with the LoadRunner Controller
(section 10) — check `wlrun_path` in `customer.yaml`, or that the CI job
is actually running on the right agent.
```

Replace the "Current Limitations" bullet (search for `**No real remote execution yet for two of the three tools.**`):

```
- **No real remote execution yet for two of the three tools.** JMeter's
  generated script is real and complete; BlazeMeter's and LoadRunner
  Professional's are templates whose API/controller call is still a
  `# TODO` (section 10).
```

with:

```
- **No real execution yet for BlazeMeter.** JMeter's and LoadRunner
  Professional's generated scripts are real and complete; BlazeMeter's is
  a template whose API call is still a `# TODO` (section 10).
```

- [ ] **Step 5: Grep-verify no stale claims remain**

Run: `grep -n "controller_host\|controller_results_path\|LoadRunner.*template\|BlazeMeter and LoadRunner" CLAUDE.md README.md docs/current-state-and-readiness-plan.md docs/pipeline-generator-user-guide.md`

Expected: no output (or only lines that are genuinely still about BlazeMeter alone, not LoadRunner — read each match to confirm before treating a nonempty result as done).

- [ ] **Step 6: Run the full suite one more time**

Run: `python3 -m pytest -q`
Expected: PASS (docs changes don't affect tests, but this confirms nothing else drifted).

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md README.md docs/current-state-and-readiness-plan.md docs/pipeline-generator-user-guide.md
git commit -m "Update docs: LoadRunner Professional's script is now real

Reflects Tasks 1-4: LoadRunner Professional joins JMeter as real, working
execution (wlrun locally on a controller-adjacent agent) instead of a
template. BlazeMeter is now the only remaining template. Updates CLAUDE.md,
README.md, the readiness plan, and the user guide accordingly."
```
