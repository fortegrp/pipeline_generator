# BlazeMeter Real API Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scripts/run-blazemeter.sh` real, working execution (matching JMeter's and LoadRunner Professional's bar), replacing its current template stub that always ends in `exit 1`.

**Architecture:** The generated script talks to BlazeMeter's REST API v4 directly via `curl`/`jq` — no execution-strategy decision needed, since BlazeMeter is a hosted SaaS reachable from anywhere. `tool.connection` stays unchanged (`base_url`/`workspace_id`/`project_id`); scenario catalog entries become real BlazeMeter numeric Test IDs, one per (environment, scenario) combination. Two new `PRE_RUN_CHECKS` values (`verify_host_reachable`, `verify_project_exists`) fit BlazeMeter's actual failure modes, and the wizard's precheck menu becomes tool-aware so each tool only offers checks that apply to it. A new `--timeout-minutes` flag (BlazeMeter-only) bounds the poll loop.

**Tech Stack:** Python 3.9+, pytest, bash (generated scripts), `curl`/`jq` (generated script's runtime dependencies).

**Spec:** `docs/superpowers/specs/2026-09-09-blazemeter-real-api-execution-design.md`

## Global Constraints

- Every config-derived string embedded into a generated script goes through `renderers/quoting.py`'s `shell_quote` (project-wide rule, already followed by every other tool's renderer).
- `pre_run_checks` values are only ever rendered/acted on after passing through `_allowed_pre_run_checks()` in `renderers/scripts.py`, which filters against the `PRE_RUN_CHECKS` enum.
- Every pre-run check gates behind its `pre_run_checks` membership — nothing in a generated script is "unconditionally on" except the `jq`-availability check, which is a hard prerequisite for the script's own operation (not a target-environment validation), justified explicitly in Task 3.
- `results_dir` for BlazeMeter is built from sanitized slugs (`environment_slug`/`scenario_slug`), never raw catalog keys — same path-traversal protection LoadRunner's final review required.
- `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET` are the only secret-carrying values; `customer.yaml` never contains a secret.
- Run `python3 -m pytest -q` from the `pipelineGenerator` directory after every task; it must be green before moving to the next task. Baseline before Task 1: 42 passed.
- No task in this plan touches JMeter's or LoadRunner's *behavior* beyond the one explicitly-scoped JMeter consistency fix in Task 2 — their generated output must otherwise remain byte-for-byte unchanged, verified by their existing tests continuing to pass unmodified.

---

### Task 1: Schema and tool-aware wizard precheck menu

**Files:**
- Modify: `src/pipeline_generator/config/schema.py`
- Modify: `src/pipeline_generator/wizard/flow.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `PRE_RUN_CHECKS` (extended) and `PRE_RUN_CHECKS_BY_TOOL` (new), both consumed by Task 3's `_render_blazemeter_script` (via `_allowed_pre_run_checks`, which already filters against the full `PRE_RUN_CHECKS` enum with no code change needed there) and by this task's own wizard change.

- [ ] **Step 1: Add the two new `PRE_RUN_CHECKS` values and the per-tool mapping**

In `src/pipeline_generator/config/schema.py`, replace:

```python
PRE_RUN_CHECKS = [
    "verify_controller_access",
    "verify_scenario_exists",
    "verify_load_generators_connected",
    "collect_results",
]
```

with:

```python
PRE_RUN_CHECKS = [
    "verify_controller_access",
    "verify_scenario_exists",
    "verify_load_generators_connected",
    "verify_host_reachable",
    "verify_project_exists",
    "collect_results",
]

PRE_RUN_CHECKS_BY_TOOL = {
    "jmeter": ["verify_scenario_exists", "collect_results"],
    "loadrunner_professional": [
        "verify_controller_access",
        "verify_scenario_exists",
        "verify_load_generators_connected",
        "collect_results",
    ],
    "blazemeter": [
        "verify_host_reachable",
        "verify_project_exists",
        "verify_scenario_exists",
        "collect_results",
    ],
}
```

- [ ] **Step 2: Make the wizard's precheck prompt tool-aware**

In `src/pipeline_generator/wizard/flow.py`, add `PRE_RUN_CHECKS_BY_TOOL` to the existing import block (currently):

```python
from pipeline_generator.config.schema import (
    AUTH_TYPES,
    GENERATION_MODES,
    PIPELINE_DESTINATIONS,
    PRE_RUN_CHECKS,
    SUPPORTED_CICD,
    SUPPORTED_TOOLS,
    WORKING_LOCATIONS,
    merged_base_config,
)
```

becomes:

```python
from pipeline_generator.config.schema import (
    AUTH_TYPES,
    GENERATION_MODES,
    PIPELINE_DESTINATIONS,
    PRE_RUN_CHECKS,
    PRE_RUN_CHECKS_BY_TOOL,
    SUPPORTED_CICD,
    SUPPORTED_TOOLS,
    WORKING_LOCATIONS,
    merged_base_config,
)
```

Then replace `_prompt_checks` (currently):

```python
def _prompt_checks(existing: list[str]) -> list[str]:
    return prompt_multi_choice("Select pre-run checks", PRE_RUN_CHECKS, default=existing)
```

with:

```python
def _prompt_checks(existing: list[str], tool_type: str) -> list[str]:
    options = PRE_RUN_CHECKS_BY_TOOL.get(tool_type, PRE_RUN_CHECKS)
    return prompt_multi_choice("Select pre-run checks", options, default=existing)
```

Then update its one call site (currently `config["pre_run_checks"] = _prompt_checks(config.get("pre_run_checks", []))`) to:

```python
    config["pre_run_checks"] = _prompt_checks(config.get("pre_run_checks", []), config["tool"]["type"])
```

- [ ] **Step 3: Manually verify the tool-aware menu**

There is no automated wizard test in this project (confirmed: no `tests/*wizard*` file exists), so verify by hand for both a JMeter and a BlazeMeter setup:

```bash
printf 'n\ngithub_actions\njmeter\nnone\ny\nacme/storefront\n\nplan.jmx\n\nn\nn\ny\nManual Run\n30\nn\nn\n' | \
  python3 -m pipeline_generator.cli wizard --output /tmp/jmeter-check.yaml
```

At the "Select pre-run checks" screen, confirm only 2 options are listed (`verify_scenario_exists`, `collect_results`), not the full 6.

```bash
printf 'n\ngithub_actions\nblazemeter\napi_token\ny\nacme/storefront\n\nhttps://a.blazemeter.com\n12345\n67890\nn\nn\ny\nManual Run\n30\nn\nn\n' | \
  python3 -m pipeline_generator.cli wizard --output /tmp/blazemeter-check.yaml
```

At the "Select pre-run checks" screen, confirm 4 options are listed (`verify_host_reachable`, `verify_project_exists`, `verify_scenario_exists`, `collect_results`), not `verify_controller_access`/`verify_load_generators_connected`. Clean up with `rm /tmp/jmeter-check.yaml /tmp/blazemeter-check.yaml` when done. (If the piped answers don't line up with the wizard's current prompt order/count, run it interactively instead and just watch for the right options at the precheck screen — the exact answer sequence is not the point of this check.)

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (42 — no test code changed in this task, this just confirms nothing broke).

- [ ] **Step 5: Commit**

```bash
git add src/pipeline_generator/config/schema.py src/pipeline_generator/wizard/flow.py
git commit -m "Add BlazeMeter-specific pre-run checks and a tool-aware wizard menu

verify_host_reachable and verify_project_exists join PRE_RUN_CHECKS --
BlazeMeter's real failure modes (host reachability, project existence)
don't map onto the existing LoadRunner/on-prem-flavored vocabulary
(verify_controller_access, verify_load_generators_connected). The
wizard's precheck screen now shows only the checks applicable to the
selected tool via a new PRE_RUN_CHECKS_BY_TOOL mapping; hand-edited YAML
is unrestricted either way, since _allowed_pre_run_checks() still
filters against the full enum."
```

---

### Task 2: Shared script-rendering helpers (slug resolver rename, `--timeout-minutes` support, JMeter consistency fix)

**Files:**
- Modify: `src/pipeline_generator/renderers/scripts.py`
- Test: `tests/test_tool_scripts.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `_render_slug_resolvers` (renamed from `_render_loadrunner_slug_resolvers`) and `_render_arg_parsing(include_timeout: bool = False)`, both consumed by Task 3's `_render_blazemeter_script`.

This task has three parts, all in the same file, done together since they're small and tightly related (a rename, a parameter addition, and a one-function consistency fix) — not because they share a review surface with Task 3's new BlazeMeter logic, which is why it's a separate task from Task 3.

- [ ] **Step 1: Write the failing test for the JMeter consistency fix**

Add to `tests/test_tool_scripts.py` (anywhere among the other `test_render_jmeter_*` tests):

```python
def test_render_jmeter_script_todo_comments_for_unhandled_checks(tmp_path: Path) -> None:
    config = _base_config(
        "jmeter",
        {"test_plan_path": "plan.jmx", "jmeter_bin": ""},
        checks=["verify_scenario_exists", "verify_controller_access", "verify_load_generators_connected"],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "# TODO precheck: verify_scenario_exists" not in content
    assert "# TODO precheck: verify_controller_access" in content
    assert "# TODO precheck: verify_load_generators_connected" in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m pytest -q tests/test_tool_scripts.py::test_render_jmeter_script_todo_comments_for_unhandled_checks -v`
Expected: FAIL — `_render_jmeter_script` currently silently drops any check other than `verify_scenario_exists`.

- [ ] **Step 3: Rename `_render_loadrunner_slug_resolvers` to `_render_slug_resolvers`**

In `src/pipeline_generator/renderers/scripts.py`, change the function definition:

```python
def _render_loadrunner_slug_resolvers(package: GenericPipelinePackage) -> str:
```

to:

```python
def _render_slug_resolvers(package: GenericPipelinePackage) -> str:
```

(the function body is unchanged — only the name). Then update its one existing call site, inside `_render_loadrunner_script`, from:

```python
{_render_loadrunner_slug_resolvers(package)}
```

to:

```python
{_render_slug_resolvers(package)}
```

This is a pure rename with no behavior change — LoadRunner's generated script content is unaffected (the generated bash function is still named `resolve_environment_slug`/`resolve_scenario_slug`; only the private Python function that generates it is renamed).

- [ ] **Step 4: Give `_render_arg_parsing` an `include_timeout` parameter**

Replace the current function:

```python
def _render_arg_parsing() -> str:
    return """  local environment_key=""
  local scenario_key=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --environment) environment_key="$2"; shift 2 ;;
      --scenario) scenario_key="$2"; shift 2 ;;
      *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
  done

  if [ -z "$environment_key" ] || [ -z "$scenario_key" ]; then
    echo "Usage: $0 --environment <key> --scenario <key>" >&2
    exit 1
  fi

  local environment_identifier
  local scenario_identifier
  environment_identifier="$(resolve_environment_identifier "$environment_key")"
  scenario_identifier="$(resolve_scenario_identifier "$scenario_key")"
"""
```

with:

```python
def _render_arg_parsing(include_timeout: bool = False) -> str:
    timeout_local = ""
    timeout_case = ""
    timeout_required_check = ""
    timeout_usage = ""
    if include_timeout:
        timeout_local = '  local timeout_minutes=""\n'
        timeout_case = '      --timeout-minutes) timeout_minutes="$2"; shift 2 ;;\n'
        timeout_required_check = ' || [ -z "$timeout_minutes" ]'
        timeout_usage = ' --timeout-minutes <minutes>'

    return f"""  local environment_key=""
  local scenario_key=""
{timeout_local}  while [ $# -gt 0 ]; do
    case "$1" in
      --environment) environment_key="$2"; shift 2 ;;
      --scenario) scenario_key="$2"; shift 2 ;;
{timeout_case}      *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
  done

  if [ -z "$environment_key" ] || [ -z "$scenario_key" ]{timeout_required_check}; then
    echo "Usage: $0 --environment <key> --scenario <key>{timeout_usage}" >&2
    exit 1
  fi

  local environment_identifier
  local scenario_identifier
  environment_identifier="$(resolve_environment_identifier "$environment_key")"
  scenario_identifier="$(resolve_scenario_identifier "$scenario_key")"
"""
```

`_render_jmeter_script`'s and `_render_loadrunner_script`'s existing calls (`{_render_arg_parsing()}`, no argument) need no changes — `include_timeout` defaults to `False`, and every new piece is an empty string in that case, so the returned text is byte-for-byte identical to today. Do not touch those two call sites in this step.

- [ ] **Step 5: Apply the JMeter consistency fix**

Replace `_render_jmeter_script` (currently):

```python
def _render_jmeter_script(config: dict, package: GenericPipelinePackage) -> str:
    connection = config.get("tool", {}).get("connection", {})
    test_plan_path = connection.get("test_plan_path") or TODO_VALUE
    jmeter_bin = connection.get("jmeter_bin") or "jmeter"
    checks = _allowed_pre_run_checks(config)

    precheck = ""
    if "verify_scenario_exists" in checks:
        precheck = """
  if [ ! -f "$test_plan_path" ]; then
    echo "Test plan not found: $test_plan_path" >&2
    exit 1
  fi
"""

    return f"""#!/usr/bin/env bash
set -euo pipefail

{_render_resolvers(package)}

main() {{
{_render_arg_parsing()}
  mkdir -p run-output

  local test_plan_path={shell_quote(test_plan_path)}
  local jmeter_bin={shell_quote(jmeter_bin)}
{precheck}
  "$jmeter_bin" -n -t "$test_plan_path" -l run-output/results.jtl -e -o run-output/report \\
    -Jenvironment="$environment_identifier" -Jscenario="$scenario_identifier"
}}

if [ "${{BASH_SOURCE[0]:-$0}}" = "$0" ]; then
  main "$@"
fi
"""
```

with:

```python
def _render_jmeter_script(config: dict, package: GenericPipelinePackage) -> str:
    connection = config.get("tool", {}).get("connection", {})
    test_plan_path = connection.get("test_plan_path") or TODO_VALUE
    jmeter_bin = connection.get("jmeter_bin") or "jmeter"
    checks = _allowed_pre_run_checks(config)

    precheck = ""
    if "verify_scenario_exists" in checks:
        precheck = """
  if [ ! -f "$test_plan_path" ]; then
    echo "Test plan not found: $test_plan_path" >&2
    exit 1
  fi
"""

    remaining_checks = [check for check in checks if check != "verify_scenario_exists"]
    precheck_comments = "\n".join(f"  # TODO precheck: {check}" for check in remaining_checks)
    if precheck_comments:
        precheck_comments = f"\n{precheck_comments}\n"

    return f"""#!/usr/bin/env bash
set -euo pipefail

{_render_resolvers(package)}

main() {{
{_render_arg_parsing()}
  mkdir -p run-output

  local test_plan_path={shell_quote(test_plan_path)}
  local jmeter_bin={shell_quote(jmeter_bin)}
{precheck}{precheck_comments}
  "$jmeter_bin" -n -t "$test_plan_path" -l run-output/results.jtl -e -o run-output/report \\
    -Jenvironment="$environment_identifier" -Jscenario="$scenario_identifier"
}}

if [ "${{BASH_SOURCE[0]:-$0}}" = "$0" ]; then
  main "$@"
fi
"""
```

- [ ] **Step 6: Run the tests to confirm the new one passes and nothing else broke**

Run: `python3 -m pytest -q tests/test_tool_scripts.py -v`
Expected: all PASS (16 tests — the file had 15 before this task; 1 new test added, 0 removed). Specifically confirm every `test_render_loadrunner_*` test still passes (the rename in Step 3 must not have broken anything) and every `test_render_jmeter_*` test still passes (Step 5's addition must not have changed JMeter's behavior when no unhandled check is configured).

- [ ] **Step 7: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (43 — 42 baseline + 1 new test).

- [ ] **Step 8: Commit**

```bash
git add src/pipeline_generator/renderers/scripts.py tests/test_tool_scripts.py
git commit -m "Prepare shared script-rendering helpers for real BlazeMeter execution

Three small, related changes: renamed _render_loadrunner_slug_resolvers
to _render_slug_resolvers (BlazeMeter needs the same path-traversal-safe
results_dir LoadRunner already has), gave _render_arg_parsing an
optional include_timeout parameter for BlazeMeter's poll-loop bound
(JMeter/LoadRunner's calls are unaffected -- every new piece defaults to
empty), and fixed a previously-undiscovered instance of the
silently-dropped-pre-run-check bug in _render_jmeter_script (a
hand-authored config with verify_controller_access or
verify_load_generators_connected under tool.type: jmeter now renders a
# TODO precheck comment instead of silent nothing, matching the fix
LoadRunner's final review already required there)."
```

---

### Task 3: Real BlazeMeter script rendering

**Files:**
- Modify: `src/pipeline_generator/renderers/scripts.py`
- Test: `tests/test_tool_scripts.py`

**Interfaces:**
- Consumes: `_render_slug_resolvers`, `_render_arg_parsing(include_timeout=True)` (both from Task 2).
- Produces: nothing new consumed elsewhere — `render_tool_script`'s existing dispatch (`elif tool_type == "blazemeter": content = _render_blazemeter_script(config, package)`) is unchanged; only what that function returns changes, and `_render_template_script` is deleted since nothing calls it after this task.

- [ ] **Step 1: Replace the two old template-based tests with new real-execution tests**

In `tests/test_tool_scripts.py`, delete these two whole functions: `test_render_blazemeter_script_is_a_template` and `test_render_template_script_rejects_pre_run_check_shell_injection`. Replace them (same location in the file) with:

```python
def test_render_blazemeter_script_runs_curl_for_real(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    )
    package = build_generic_package(config)

    outputs = render_tool_script(config, package, tmp_path)

    script_path = tmp_path / "scripts" / "run-blazemeter.sh"
    assert outputs == [str(script_path)]
    assert script_path.exists()
    assert script_path.stat().st_mode & 0o111 == 0o111

    content = script_path.read_text(encoding="utf-8")
    assert "resolve_environment_slug() {" in content
    assert "resolve_scenario_slug() {" in content
    assert "local base_url=https://a.blazemeter.com" in content
    assert "local workspace_id=12345" in content
    assert "local project_id=67890" in content
    assert "command -v jq >/dev/null 2>&1" in content
    assert '-X POST "$base_url/api/v4/tests/$scenario_identifier/start"' in content
    assert "jq -r '.result.id'" in content
    assert '"$base_url/api/v4/masters/$master_id/status"' in content
    assert '"$base_url/api/v4/masters/$master_id/reports/main/summary"' in content
    assert "not implemented in this generated script yet" not in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_blazemeter_script_checks_host_reachable_when_configured(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
        checks=["verify_host_reachable"],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-blazemeter.sh").read_text(encoding="utf-8")

    assert 'if ! curl -s -o /dev/null "$base_url"; then' in content
    assert 'echo "ERROR: cannot reach BlazeMeter host: $base_url" >&2' in content


def test_render_blazemeter_script_omits_host_check_when_not_configured(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
        checks=[],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-blazemeter.sh").read_text(encoding="utf-8")

    assert "cannot reach BlazeMeter host" not in content


def test_render_blazemeter_script_checks_project_exists_when_configured(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
        checks=["verify_project_exists"],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-blazemeter.sh").read_text(encoding="utf-8")

    assert '"$base_url/api/v4/projects/$project_id?workspaceId=$workspace_id"' in content
    assert 'if [ "$project_status" != "200" ]; then' in content


def test_render_blazemeter_script_omits_project_check_when_not_configured(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
        checks=[],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-blazemeter.sh").read_text(encoding="utf-8")

    assert "project_status=" not in content


def test_render_blazemeter_script_checks_scenario_exists_when_configured(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
        checks=["verify_scenario_exists"],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-blazemeter.sh").read_text(encoding="utf-8")

    assert '"$base_url/api/v4/tests/$scenario_identifier"' in content
    assert 'if [ "$test_status" != "200" ]; then' in content


def test_render_blazemeter_script_omits_scenario_check_when_not_configured(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
        checks=[],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-blazemeter.sh").read_text(encoding="utf-8")

    assert "test_status=" not in content


def test_render_blazemeter_script_requires_timeout_minutes_flag(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"
    content = script_path.read_text(encoding="utf-8")

    assert '--timeout-minutes) timeout_minutes="$2"; shift 2 ;;' in content
    assert 'echo "Usage: $0 --environment <key> --scenario <key> --timeout-minutes <minutes>" >&2' in content

    # Calling main without --timeout-minutes must fail fast during arg
    # parsing, before any network call -- safe to actually execute. main's
    # Usage-error branch calls `exit 1` directly, which terminates this
    # whole bash -c process immediately (not just the function), so the
    # process's own exit code IS the check -- there is no shell code after
    # `main ...` in this command line that would ever run.
    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}"; main --environment qa --scenario checkout_smoke'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Usage:" in result.stderr


def test_render_blazemeter_script_todo_comments_for_unhandled_checks(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
        checks=["verify_host_reachable", "verify_project_exists", "verify_scenario_exists", "collect_results"],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-blazemeter.sh").read_text(encoding="utf-8")

    assert "# TODO precheck: verify_host_reachable" not in content
    assert "# TODO precheck: verify_project_exists" not in content
    assert "# TODO precheck: verify_scenario_exists" not in content
    assert "# TODO precheck: collect_results" in content


def test_render_blazemeter_script_sanitizes_results_dir_from_hostile_catalog_key(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    config["catalog"]["environments"] = [{"key": "../../pwn", "name": "Hostile", "identifier": "Hostile"}]
    config["catalog"]["scenarios"] = [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "1234567"}]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "resolve_environment_slug() {" in content

    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}"; resolve_environment_slug "../../pwn"'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    slug = result.stdout.strip()
    assert ".." not in slug
    assert "/" not in slug

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_blazemeter_script_rejects_pre_run_check_shell_injection(tmp_path: Path) -> None:
    malicious_check = "verify_scenario_exists\n  touch /tmp/should-not-exist\n  #"
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
        checks=[malicious_check],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "touch /tmp/should-not-exist" not in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `python3 -m pytest -q tests/test_tool_scripts.py -v`
Expected: FAIL — the new tests reference script content (`resolve_environment_slug`, the real `curl`/`jq` calls, `--timeout-minutes`) that the current `_render_blazemeter_script` (which delegates to `_render_template_script`) does not produce.

- [ ] **Step 3: Delete `_render_template_script` and replace `_render_blazemeter_script`**

In `src/pipeline_generator/renderers/scripts.py`, delete the entire `_render_template_script` function:

```python
def _render_template_script(
    config: dict, package: GenericPipelinePackage, tool_label: str, connection_vars: dict[str, str]
) -> str:
    checks = _allowed_pre_run_checks(config)
    var_lines = "\n".join(f"  local {name.lower()}={shell_quote(value)}" for name, value in connection_vars.items())
    var_names = ", ".join(name.lower() for name in connection_vars)
    precheck_comments = "\n".join(
        f"  # TODO precheck: {check} (requires a {tool_label} API/controller call; not implemented)"
        for check in checks
    )

    return f"""#!/usr/bin/env bash
set -euo pipefail

{_render_resolvers(package)}

main() {{
{_render_arg_parsing()}
  mkdir -p run-output

{var_lines}

{precheck_comments}
  # TODO: this generated script does not yet call the {tool_label} API/controller.
  # Use {var_names}, environment_identifier, and scenario_identifier above to
  # start a {tool_label} test run, poll for completion, and collect results
  # into run-output/.
  echo "ERROR: {tool_label} execution is not implemented in this generated script yet." >&2
  echo "Fill in the API/controller call using the variables above." >&2
  exit 1
}}

if [ "${{BASH_SOURCE[0]:-$0}}" = "$0" ]; then
  main "$@"
fi
"""
```

Then replace `_render_blazemeter_script` (currently):

```python
def _render_blazemeter_script(config: dict, package: GenericPipelinePackage) -> str:
    connection = config.get("tool", {}).get("connection", {})
    return _render_template_script(
        config,
        package,
        "BlazeMeter",
        {
            "BASE_URL": connection.get("base_url") or TODO_VALUE,
            "WORKSPACE_ID": connection.get("workspace_id") or TODO_VALUE,
            "PROJECT_ID": connection.get("project_id") or TODO_VALUE,
        },
    )
```

with:

```python
def _render_blazemeter_script(config: dict, package: GenericPipelinePackage) -> str:
    connection = config.get("tool", {}).get("connection", {})
    base_url = connection.get("base_url") or TODO_VALUE
    workspace_id = connection.get("workspace_id") or TODO_VALUE
    project_id = connection.get("project_id") or TODO_VALUE
    checks = _allowed_pre_run_checks(config)

    host_check = ""
    if "verify_host_reachable" in checks:
        host_check = """
  if ! curl -s -o /dev/null "$base_url"; then
    echo "ERROR: cannot reach BlazeMeter host: $base_url" >&2
    exit 1
  fi
"""

    project_check = ""
    if "verify_project_exists" in checks:
        project_check = """
  project_status=$(curl -s -o /dev/null -w "%{http_code}" -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
    "$base_url/api/v4/projects/$project_id?workspaceId=$workspace_id")
  if [ "$project_status" != "200" ]; then
    echo "ERROR: BlazeMeter project not found in workspace, or inaccessible: project $project_id, workspace $workspace_id (HTTP $project_status)" >&2
    exit 1
  fi
"""

    scenario_check = ""
    if "verify_scenario_exists" in checks:
        scenario_check = """
  test_status=$(curl -s -o /dev/null -w "%{http_code}" -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
    "$base_url/api/v4/tests/$scenario_identifier")
  if [ "$test_status" != "200" ]; then
    echo "ERROR: BlazeMeter test not found or inaccessible: $scenario_identifier (HTTP $test_status)" >&2
    exit 1
  fi
"""

    remaining_checks = [
        check for check in checks
        if check not in {"verify_host_reachable", "verify_project_exists", "verify_scenario_exists"}
    ]
    precheck_comments = "\n".join(f"  # TODO precheck: {check}" for check in remaining_checks)
    if precheck_comments:
        precheck_comments = f"\n{precheck_comments}\n"

    return f"""#!/usr/bin/env bash
set -euo pipefail

{_render_resolvers(package)}

{_render_slug_resolvers(package)}

main() {{
{_render_arg_parsing(include_timeout=True)}
  mkdir -p run-output

  if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq is required to parse BlazeMeter API responses but was not found." >&2
    exit 1
  fi
  : "${{BLAZEMETER_API_KEY_ID:?BLAZEMETER_API_KEY_ID must be set}}"
  : "${{BLAZEMETER_API_KEY_SECRET:?BLAZEMETER_API_KEY_SECRET must be set}}"

  local base_url={shell_quote(base_url)}
  local workspace_id={shell_quote(workspace_id)}
  local project_id={shell_quote(project_id)}
{host_check}{project_check}{scenario_check}{precheck_comments}
  local environment_slug
  local scenario_slug
  environment_slug="$(resolve_environment_slug "$environment_key")"
  scenario_slug="$(resolve_scenario_slug "$scenario_key")"
  local results_dir="run-output/${{environment_slug}}_${{scenario_slug}}"
  mkdir -p "$results_dir"

  local start_response
  start_response="$(curl -s -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
    -X POST "$base_url/api/v4/tests/$scenario_identifier/start")"
  local master_id
  master_id="$(echo "$start_response" | jq -r '.result.id')"
  if [ -z "$master_id" ] || [ "$master_id" = "null" ]; then
    echo "ERROR: BlazeMeter did not return a master id when starting the test. Response: $start_response" >&2
    exit 1
  fi

  # NOTE: the exact status-string vocabulary below (ENDED/ERROR/ABORTED)
  # and the reports/main/summary endpoint used after the loop are our best
  # understanding of the BlazeMeter API v4 as of this writing -- verify
  # both against a live BlazeMeter account before relying on this in
  # production.
  local deadline=$(( $(date +%s) + timeout_minutes * 60 ))
  local status="UNKNOWN"
  while [ "$(date +%s)" -lt "$deadline" ]; do
    status="$(curl -s -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
      "$base_url/api/v4/masters/$master_id/status" | jq -r '.result.status')"
    case "$status" in
      ENDED) break ;;
      ERROR|ABORTED)
        echo "ERROR: BlazeMeter test ended with status $status (master $master_id)" >&2
        exit 1
        ;;
    esac
    sleep 15
  done
  if [ "$status" != "ENDED" ]; then
    echo "ERROR: Timed out after $timeout_minutes minutes waiting for BlazeMeter test to finish (master $master_id, last status: $status)" >&2
    exit 1
  fi

  curl -s -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
    "$base_url/api/v4/masters/$master_id/reports/main/summary" > "$results_dir/summary.json"
  printf '{{"master_id": "%s", "report_url": "%s/app/#/masters/%s/summary"}}' \\
    "$master_id" "$base_url" "$master_id" > "$results_dir/report_link.json"
}}

if [ "${{BASH_SOURCE[0]:-$0}}" = "$0" ]; then
  main "$@"
fi
"""
```

- [ ] **Step 4: Run the tests again to confirm they pass**

Run: `python3 -m pytest -q tests/test_tool_scripts.py -v`
Expected: all PASS (25 tests in this file — 16 before this task, minus the 2 deleted, plus the 11 new ones: 16 - 2 + 11 = 25).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (52 — 43 before this task, minus 2 deleted, plus 11 new: 43 - 2 + 11 = 52).

- [ ] **Step 6: Commit**

```bash
git add src/pipeline_generator/renderers/scripts.py tests/test_tool_scripts.py
git commit -m "Make BlazeMeter's generated script real

Replaces the template stub (which always ended in 'execution is not
implemented yet' / exit 1) with real BlazeMeter API v4 calls via
curl/jq: start a test, poll for completion bounded by a new
--timeout-minutes flag, and download a summary report. Three gated
prechecks (verify_host_reachable, verify_project_exists,
verify_scenario_exists) match BlazeMeter's actual failure modes rather
than the LoadRunner-flavored vocabulary the enum previously only had.
_render_template_script is deleted -- nothing calls it anymore now that
all three tools have their own real renderer function. Status-string
vocabulary and the report endpoint are flagged in a code comment as
best-understanding, pending verification against a live account."
```

---

### Task 4: `--timeout-minutes` in all three CI/CD renderers

**Files:**
- Modify: `src/pipeline_generator/renderers/github_actions.py`
- Modify: `src/pipeline_generator/renderers/azure_devops.py`
- Modify: `src/pipeline_generator/renderers/jenkins.py`
- Test: `tests/test_github_actions_renderer.py`
- Test: `tests/test_azure_devops_renderer.py`
- Test: `tests/test_jenkins_renderer.py`

**Interfaces:**
- Consumes: `package.tool_type` (already available at every call site touched), `package.manual_pipeline.timeout_minutes`/`job.timeout_minutes` (already available at every call site touched) — no new data threaded through anything.
- Produces: nothing consumed elsewhere.

This is one task covering all three files since each edit is the same shape repeated six times (once per manual/automated function per platform) — batch this as a single dispatch rather than three separate tasks.

- [ ] **Step 1: Write the three failing tests**

Add to `tests/test_github_actions_renderer.py`:

```python
def test_render_github_actions_includes_timeout_flag_for_blazemeter(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {
        "type": "blazemeter",
        "connection": {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    }
    package = build_generic_package(config)

    render_github_actions(config, package, tmp_path)

    manual_text = (tmp_path / ".github" / "workflows" / "performance-manual.yml").read_text(encoding="utf-8")
    automated_text = (
        tmp_path / ".github" / "workflows" / "performance-automated-post-deploy-smoke.yml"
    ).read_text(encoding="utf-8")

    assert "--timeout-minutes 120" in manual_text
    assert "--timeout-minutes 60" in automated_text
```

Add to `tests/test_azure_devops_renderer.py`:

```python
def test_render_azure_devops_includes_timeout_flag_for_blazemeter(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {
        "type": "blazemeter",
        "connection": {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    }
    package = build_generic_package(config)

    render_azure_devops(config, package, tmp_path)

    manual_text = (tmp_path / "azure" / "performance-manual.yml").read_text(encoding="utf-8")
    automated_text = (tmp_path / "azure" / "performance-automated-post-deploy-smoke.yml").read_text(encoding="utf-8")

    assert "--timeout-minutes 120" in manual_text
    assert "--timeout-minutes 60" in automated_text
```

Add to `tests/test_jenkins_renderer.py`:

```python
def test_render_jenkins_includes_timeout_flag_for_blazemeter(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {
        "type": "blazemeter",
        "connection": {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    }
    package = build_generic_package(config)

    render_jenkins(config, package, tmp_path)

    manual_text = (tmp_path / "jenkins" / "Jenkinsfile.performance-manual").read_text(encoding="utf-8")
    automated_text = (
        tmp_path / "jenkins" / "Jenkinsfile.performance-automated-post-deploy-smoke"
    ).read_text(encoding="utf-8")

    assert "--timeout-minutes 120" in manual_text
    assert "--timeout-minutes 60" in automated_text
```

- [ ] **Step 2: Run the three new tests to confirm they fail**

Run: `python3 -m pytest -q tests/test_github_actions_renderer.py tests/test_azure_devops_renderer.py tests/test_jenkins_renderer.py -v`
Expected: the 3 new tests FAIL (none of the three renderers emit `--timeout-minutes` yet); all pre-existing tests in these files still PASS.

- [ ] **Step 3: Add the flag to `github_actions.py`**

In `_render_manual_workflow`, add a `timeout_flag` local variable right after the existing `timeout = package.manual_pipeline.timeout_minutes` line, and append `{timeout_flag}` to the invocation. Change:

```python
def _render_manual_workflow(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_options = ", ".join(yaml_dquote(item.value) for item in package.manual_pipeline.inputs[0].options)
    scenario_options = ", ".join(yaml_dquote(item.value) for item in package.manual_pipeline.inputs[1].options)
    timeout = package.manual_pipeline.timeout_minutes
    return f"""name: {yaml_dquote(package.manual_pipeline.name)}
```

to:

```python
def _render_manual_workflow(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_options = ", ".join(yaml_dquote(item.value) for item in package.manual_pipeline.inputs[0].options)
    scenario_options = ", ".join(yaml_dquote(item.value) for item in package.manual_pipeline.inputs[1].options)
    timeout = package.manual_pipeline.timeout_minutes
    timeout_flag = f"\n          --timeout-minutes {timeout}" if package.tool_type == "blazemeter" else ""
    return f"""name: {yaml_dquote(package.manual_pipeline.name)}
```

and further down in the same function, change:

```python
        run: >
          ./scripts/run-{package.tool_type}.sh
          --environment "$ENVIRONMENT"
          --scenario "$SCENARIO"
```

to:

```python
        run: >
          ./scripts/run-{package.tool_type}.sh
          --environment "$ENVIRONMENT"
          --scenario "$SCENARIO"{timeout_flag}
```

In `_render_automated_workflow`, change:

```python
def _render_automated_workflow(job, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    return f"""name: {yaml_dquote(f"Performance Automated Job - {job.name}")}
```

to:

```python
def _render_automated_workflow(job, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    timeout_flag = f"\n          --timeout-minutes {job.timeout_minutes}" if tool_type == "blazemeter" else ""
    return f"""name: {yaml_dquote(f"Performance Automated Job - {job.name}")}
```

and change:

```python
        run: >
          ./scripts/run-{tool_type}.sh
          --environment {shell_quote(job.environment_ref)}
          --scenario {shell_quote(job.scenario_ref)}
```

to:

```python
        run: >
          ./scripts/run-{tool_type}.sh
          --environment {shell_quote(job.environment_ref)}
          --scenario {shell_quote(job.scenario_ref)}{timeout_flag}
```

- [ ] **Step 4: Add the flag to `azure_devops.py`**

In `_render_manual_pipeline`, change:

```python
def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_options = package.manual_pipeline.inputs[0].options
    scenario_options = package.manual_pipeline.inputs[1].options
    environment_values = "\n".join(f"      - {yaml_dquote(item.value)}" for item in environment_options)
    scenario_values = "\n".join(f"      - {yaml_dquote(item.value)}" for item in scenario_options)
    environment_default = yaml_dquote(environment_options[0].value if environment_options else "TODO")
    scenario_default = yaml_dquote(scenario_options[0].value if scenario_options else "TODO")
    return f"""trigger: none
```

to:

```python
def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_options = package.manual_pipeline.inputs[0].options
    scenario_options = package.manual_pipeline.inputs[1].options
    environment_values = "\n".join(f"      - {yaml_dquote(item.value)}" for item in environment_options)
    scenario_values = "\n".join(f"      - {yaml_dquote(item.value)}" for item in scenario_options)
    environment_default = yaml_dquote(environment_options[0].value if environment_options else "TODO")
    scenario_default = yaml_dquote(scenario_options[0].value if scenario_options else "TODO")
    timeout_flag = (
        f"\n          --timeout-minutes {package.manual_pipeline.timeout_minutes}"
        if package.tool_type == "blazemeter"
        else ""
    )
    return f"""trigger: none
```

and change:

```python
      - script: >
          ./scripts/run-{package.tool_type}.sh
          --environment "$ENVIRONMENT"
          --scenario "$SCENARIO"
```

to:

```python
      - script: >
          ./scripts/run-{package.tool_type}.sh
          --environment "$ENVIRONMENT"
          --scenario "$SCENARIO"{timeout_flag}
```

In `_render_automated_job`, change:

```python
def _render_automated_job(job, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    return f"""parameters: []
```

to:

```python
def _render_automated_job(job, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    timeout_flag = f"\n          --timeout-minutes {job.timeout_minutes}" if tool_type == "blazemeter" else ""
    return f"""parameters: []
```

and change:

```python
      - script: >
          ./scripts/run-{tool_type}.sh
          --environment {shell_quote(job.environment_ref)}
          --scenario {shell_quote(job.scenario_ref)}
```

to:

```python
      - script: >
          ./scripts/run-{tool_type}.sh
          --environment {shell_quote(job.environment_ref)}
          --scenario {shell_quote(job.scenario_ref)}{timeout_flag}
```

- [ ] **Step 5: Add the flag to `jenkins.py`**

In `_render_manual_pipeline`, change:

```python
    timeout = package.manual_pipeline.timeout_minutes
    return f"""pipeline {{
```

to:

```python
    timeout = package.manual_pipeline.timeout_minutes
    timeout_flag = f" --timeout-minutes {timeout}" if package.tool_type == "blazemeter" else ""
    return f"""pipeline {{
```

and change:

```python
                sh './scripts/run-{package.tool_type}.sh --environment "$ENVIRONMENT" --scenario "$SCENARIO"'
```

to:

```python
                sh './scripts/run-{package.tool_type}.sh --environment "$ENVIRONMENT" --scenario "$SCENARIO"{timeout_flag}'
```

In `_render_automated_job`, change:

```python
def _render_automated_job(job, tool_type: str) -> str:
    return f"""pipeline {{
```

to:

```python
def _render_automated_job(job, tool_type: str) -> str:
    timeout_flag = f" --timeout-minutes {job.timeout_minutes}" if tool_type == "blazemeter" else ""
    return f"""pipeline {{
```

and change:

```python
                sh './scripts/run-{tool_type}.sh --environment "$ENVIRONMENT" --scenario "$SCENARIO"'
```

to:

```python
                sh './scripts/run-{tool_type}.sh --environment "$ENVIRONMENT" --scenario "$SCENARIO"{timeout_flag}'
```

- [ ] **Step 6: Run the three renderer test files again to confirm everything passes**

Run: `python3 -m pytest -q tests/test_github_actions_renderer.py tests/test_azure_devops_renderer.py tests/test_jenkins_renderer.py -v`
Expected: all PASS. Specifically confirm every pre-existing JMeter-fixture test in these three files is unaffected (their `tool_type` is never `"blazemeter"`, so `timeout_flag` is always `""` for them, producing byte-for-byte identical output to before this task).

- [ ] **Step 7: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (55 — 52 before this task + 3 new tests).

- [ ] **Step 8: Commit**

```bash
git add src/pipeline_generator/renderers/github_actions.py src/pipeline_generator/renderers/azure_devops.py src/pipeline_generator/renderers/jenkins.py tests/test_github_actions_renderer.py tests/test_azure_devops_renderer.py tests/test_jenkins_renderer.py
git commit -m "Pass --timeout-minutes to BlazeMeter's generated script invocation

Each CI/CD renderer already knows the right timeout_minutes value at
every call site (it already renders the platform's own native
timeout field from the same value) -- this just also appends
--timeout-minutes to the ./scripts/run-blazemeter.sh invocation, only
when tool_type is blazemeter. JMeter and LoadRunner Professional's
generated output is completely unaffected."
```

---

### Task 5: Generated README's BlazeMeter caveat

**Files:**
- Modify: `src/pipeline_generator/renderers/readme.py`
- Test: `tests/test_readme_renderer.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing consumed elsewhere.

- [ ] **Step 1: Write the failing test**

In `tests/test_readme_renderer.py`, replace the existing test:

```python
def test_readme_mentions_blazemeter_script_and_todo() -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    )
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)

    assert "scripts/run-blazemeter.sh" in readme
    assert "Fill in the actual API/controller call in `scripts/run-blazemeter.sh`" in readme
```

with:

```python
def test_readme_mentions_blazemeter_secrets_and_verification_caveat() -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    )
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)

    assert "scripts/run-blazemeter.sh" in readme
    assert "BLAZEMETER_API_KEY_ID" in readme
    assert "BLAZEMETER_API_KEY_SECRET" in readme
    assert "verify against a live account" in readme
    assert "Fill in the actual API/controller call" not in readme
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m pytest -q tests/test_readme_renderer.py -v`
Expected: FAIL — `render_setup_readme` currently still prints "Fill in the actual API/controller call ..." for `blazemeter` and says nothing about the two secret env vars.

- [ ] **Step 3: Replace the BlazeMeter branch**

In `src/pipeline_generator/renderers/readme.py`, change:

```python
    if tool_type == "blazemeter":
        todo_lines.append(f"- Fill in the actual API/controller call in `{script_name}` (marked with `# TODO`).")
    elif tool_type == "loadrunner_professional":
```

to:

```python
    if tool_type == "blazemeter":
        todo_lines.append(
            "- Set `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET` as secrets for the generated "
            f"pipeline. The status-string vocabulary and report endpoint in `{script_name}` are our "
            "best understanding of the BlazeMeter API v4 -- verify against a live account before "
            "relying on this in production."
        )
    elif tool_type == "loadrunner_professional":
```

(everything else in the function is unchanged).

- [ ] **Step 4: Run the tests again to confirm they pass**

Run: `python3 -m pytest -q tests/test_readme_renderer.py -v`
Expected: all PASS (3 tests — the file had 3 before this task; the BlazeMeter test was replaced in place, not added, so the count stays 3).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (55 — unchanged from Task 4, since this task replaces a test rather than adding one).

- [ ] **Step 6: Commit**

```bash
git add src/pipeline_generator/renderers/readme.py tests/test_readme_renderer.py
git commit -m "Replace BlazeMeter's generated README TODO with a real-usage caveat

Now that BlazeMeter's script is real (previous tasks), the old
'Fill in the actual API/controller call' line is stale -- there's
nothing left to fill in. Replaced with the two required secret env
var names and the same live-account-verification caveat carried in
the script's own comments."
```

---

### Task 6: Migrate the three BlazeMeter example configs

**Files:**
- Modify: `examples/github-blazemeter/customer.yaml`
- Modify: `examples/azure-blazemeter/customer.yaml`
- Modify: `examples/jenkins-blazemeter/customer.yaml`

**Interfaces:**
- Consumes: the new config shape from Tasks 1-3 (new `PRE_RUN_CHECKS` values, real numeric-Test-ID scenario identifiers).
- Produces: nothing consumed by later tasks — `tests/test_example_configs.py` (already existing, generic over every file under `examples/`) is the verification.

- [ ] **Step 1: Rewrite `examples/github-blazemeter/customer.yaml`**

Replace the entire file with:

```yaml
version: 1
incomplete: false
setup:
  id: github-actions-blazemeter-storefront
  working_location: central_repo
  final_pipeline_destination: stay_in_central_repo
  ci_can_use_central_repo_directly: true
  target_repository: github.com/acme/storefront
  generation_mode: both
cicd:
  type: github_actions
tool:
  type: blazemeter
  auth:
    type: api_token
  connection:
    base_url: https://a.blazemeter.com
    workspace_id: "12345"
    project_id: "67890"
manual_pipeline:
  enabled: true
  name: BlazeMeter Manual Run
  timeout_minutes: 180
automated_jobs:
  - name: pre-prod-baseline
    enabled: true
    environment_ref: staging
    scenario_ref: checkout_baseline_staging
    timeout_minutes: 120
catalog:
  environments:
    - key: staging
      name: Staging
      identifier: Staging
  scenarios:
    - key: checkout_baseline_staging
      name: Checkout Baseline (Staging)
      identifier: "2233445"
pre_run_checks:
  - verify_host_reachable
  - verify_project_exists
  - verify_scenario_exists
  - collect_results
artifacts:
  download_remote_results: true
  fail_on_partial_download: false
readme:
  include_manual_usage: true
  include_automated_usage: true
```

- [ ] **Step 2: Rewrite `examples/azure-blazemeter/customer.yaml`**

Replace the entire file with:

```yaml
version: 1
incomplete: false
setup:
  id: azure-devops-blazemeter-storefront
  working_location: central_repo
  final_pipeline_destination: stay_in_central_repo
  ci_can_use_central_repo_directly: true
  target_repository: dev.azure.com/acme/storefront
  generation_mode: both
cicd:
  type: azure_devops
tool:
  type: blazemeter
  auth:
    type: api_token
  connection:
    base_url: https://a.blazemeter.com
    workspace_id: "12345"
    project_id: "67890"
manual_pipeline:
  enabled: true
  name: Azure BlazeMeter Manual Run
  timeout_minutes: 180
automated_jobs:
  - name: post-deploy-smoke
    enabled: true
    environment_ref: qa
    scenario_ref: qa_smoke_qa
    timeout_minutes: 60
catalog:
  environments:
    - key: qa
      name: QA
      identifier: QA
  scenarios:
    - key: qa_smoke_qa
      name: QA Smoke (QA)
      identifier: "3344556"
pre_run_checks:
  - verify_host_reachable
  - verify_project_exists
  - verify_scenario_exists
  - collect_results
artifacts:
  download_remote_results: true
  fail_on_partial_download: false
readme:
  include_manual_usage: true
  include_automated_usage: true
```

- [ ] **Step 3: Rewrite `examples/jenkins-blazemeter/customer.yaml`**

Same as Step 2's content, except:
- `setup.id: jenkins-blazemeter-storefront`
- `cicd.type: jenkins`
- `setup.final_pipeline_destination: copy_to_customer_repo`
- `setup.ci_can_use_central_repo_directly: false`
- `manual_pipeline.name: Jenkins BlazeMeter Manual Run`

(matching this file's existing divergence from the azure version — check the current file before editing to confirm exactly which fields already differ, rather than assuming; everything else — `tool`, `automated_jobs`, `catalog`, `pre_run_checks`, `artifacts`, `readme` — identical to the azure version above).

- [ ] **Step 4: Run the example-config test suite**

Run: `python3 -m pytest -q tests/test_example_configs.py -v`
Expected: PASS — validates and generates every file under `examples/`, exercising the new shape end-to-end.

- [ ] **Step 5: Manually smoke-test one example's generated output**

```bash
rm -rf /tmp/bm-gen-check
python3 -m pipeline_generator.cli generate --config examples/github-blazemeter/customer.yaml --output-dir /tmp/bm-gen-check
cat /tmp/bm-gen-check/*/scripts/run-blazemeter.sh
rm -rf /tmp/bm-gen-check
```

Confirm the printed script contains real `curl`/`jq` calls (not `"... execution is not implemented in this generated script yet."`), and that `resolve_scenario_identifier` resolves `checkout_baseline_staging` to `2233445`.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (55 — unchanged, no new test code in this task).

- [ ] **Step 7: Commit**

```bash
git add examples/github-blazemeter/customer.yaml examples/azure-blazemeter/customer.yaml examples/jenkins-blazemeter/customer.yaml
git commit -m "Migrate BlazeMeter example configs to real Test IDs and new checks

Scenario catalog identifiers become realistic-looking numeric
BlazeMeter Test IDs (one per environment/scenario combination, same
convention as LoadRunner's per-environment .lrs paths), and
pre_run_checks gain verify_host_reachable/verify_project_exists
alongside the already-present verify_scenario_exists/collect_results."
```

---

### Task 7: Update project documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `docs/current-state-and-readiness-plan.md`
- Modify: `docs/pipeline-generator-user-guide.md`

**Interfaces:**
- Consumes: the final state of Tasks 1-6 (this task only describes what already shipped; do not start Task 7 before Tasks 1-6 are committed).
- Produces: nothing — this is the last task in the plan.

- [ ] **Step 1: Update `CLAUDE.md`**

Replace this passage (search for `` For `blazemeter`, the script remains a template, not a stub: ``):

```
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

with:

```
  environment only names the results folder. `wlrun`'s exit code is known
  to be unreliable on some LoadRunner versions (can return 0 on a failed
  scenario); nonzero is still treated as failure as the best local signal
  available (this results-folder path uses `resolve_environment_slug`/
  `resolve_scenario_slug`, sanitized via `safe_filename_component`, not the
  raw catalog keys — a hostile key otherwise escapes `run-output/`).
  `blazemeter` is also real: it authenticates via `BLAZEMETER_API_KEY_ID`/
  `BLAZEMETER_API_KEY_SECRET` (Basic Auth), optionally checks the host is
  reachable / the project exists / the test exists
  (`verify_host_reachable`/`verify_project_exists`/`verify_scenario_exists`
  — BlazeMeter has its own precheck vocabulary in `PRE_RUN_CHECKS`, distinct
  from LoadRunner's controller-flavored one), starts the test via
  `POST /api/v4/tests/$scenario_identifier/start`, polls
  `GET /api/v4/masters/$master_id/status` bounded by a `--timeout-minutes`
  flag (BlazeMeter-only; the other two tools' generated invocations are
  unaffected), and downloads a summary report on success. The exact
  status-string vocabulary and report endpoint are flagged in the script's
  own comments as best-understanding, pending verification against a live
  account. JMeter and LoadRunner Professional both run locally/on-agent (no
  remote API credentials managed by this script), so their `tool.auth.type`
  is `none`; BlazeMeter's stays `api_token` — see `AUTH_TYPES` in
  `config/schema.py`.
```

Also replace (search for `filling in the BlazeMeter script`):

```
See `docs/current-state-and-readiness-plan.md` for the full known-gaps list
and multi-milestone readiness plan (stricter validation profiles, YAML-safe
renderer output, filling in the BlazeMeter script template) if working on
hardening this project further.
```

with:

```
See `docs/current-state-and-readiness-plan.md` for the full known-gaps list
and multi-milestone readiness plan (stricter validation profiles, YAML-safe
renderer output) if working on hardening this project further — all three
tools' generated scripts are now real, working execution.
```

- [ ] **Step 2: Update `README.md`**

Replace (search for `- BlazeMeter — a real shell script with connection details already filled`):

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

with:

```
  - JMeter — a real, working script that runs `jmeter -n -t ...` against the
    configured test plan.
  - LoadRunner Professional — a real, working script that runs `wlrun -Run
    -TestPath ...` locally, assuming the CI job runs on an agent co-located
    with the LoadRunner Controller.
  - BlazeMeter — a real, working script that authenticates via API key,
    starts a test through BlazeMeter's REST API, polls until it finishes
    (bounded by a `--timeout-minutes` flag), and downloads a summary
    report.
```

Replace (search for `- BlazeMeter gets a template script with connection details filled in and`):

```
- `generate` writes a real, working `scripts/run-jmeter.sh` for JMeter
  setups and `scripts/run-loadrunner_professional.sh` for LoadRunner
  Professional setups (assumes the CI job runs on an agent co-located with
  the LoadRunner Controller)
- BlazeMeter gets a template script with connection details filled in and
  the actual API call left as a `# TODO` — running it prints a clear "not
  implemented yet" error and exits non-zero
```

with:

```
- `generate` writes a real, working `scripts/run-jmeter.sh` for JMeter
  setups, `scripts/run-loadrunner_professional.sh` for LoadRunner
  Professional setups (assumes the CI job runs on an agent co-located with
  the LoadRunner Controller), and `scripts/run-blazemeter.sh` for
  BlazeMeter setups (calls BlazeMeter's REST API directly)
```

Replace (search for `switch (see the user guide for the full catalog convention). For BlazeMeter`):

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
<scenario_identifier> -ResultName run-output/<environment_slug>_
<scenario_slug>` — a scenario's catalog identifier is a full `.lrs` file
path rather than a remote name, since `wlrun` has no native "environment"
switch (see the user guide for the full catalog convention). BlazeMeter is
also real: it authenticates via API key, starts a test through
BlazeMeter's REST API (`POST /api/v4/tests/<id>/start`), polls until it
finishes (bounded by a `--timeout-minutes` flag added only to BlazeMeter's
invocation), and downloads a summary report — see the user guide for the
full precheck vocabulary and the API endpoints' verification status.
```

Replace the "Recommended Next Work" section (search for `## Recommended Next Work`):

```
## Recommended Next Work

- Fill in the real BlazeMeter API call in the generated `run-blazemeter.sh`
  template (`renderers/scripts.py`)
- Add configurable CI/CD runner/agent targeting for LoadRunner Professional
  setups (generated pipelines default to hosted runners that can't reach a
  LoadRunner Controller; today this requires a manual hand-edit after
  generation — see the user guide's section 10 caveat)
- Add a GitLab CI renderer
- Add non-interactive `generate` workflows around completed YAML inputs
```

with:

```
## Recommended Next Work

- Add configurable CI/CD runner/agent targeting for LoadRunner Professional
  setups (generated pipelines default to hosted runners that can't reach a
  LoadRunner Controller; today this requires a manual hand-edit after
  generation — see the user guide's section 10 caveat)
- Verify BlazeMeter's exact status-string vocabulary and report endpoint
  against a live account (flagged as best-understanding in
  `renderers/scripts.py` and the generated setup README)
- Add a GitLab CI renderer
- Add non-interactive `generate` workflows around completed YAML inputs
```

- [ ] **Step 3: Update `docs/current-state-and-readiness-plan.md`**

Replace (search for `for BlazeMeter it's a template` in the "Purpose" section):

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

with:

```
At the current stage, the project is strongest as a generator for CI/CD setup
packages. `pipeline-generator` never executes a performance test itself — its
job ends at `generate`, which now writes a `scripts/run-<tool_type>.sh`
alongside the CI/CD files. That script is real, working execution for all
three supported tools: JMeter, LoadRunner Professional (which assumes the CI
job runs on an agent co-located with the LoadRunner Controller), and
BlazeMeter (which calls BlazeMeter's REST API directly).
```

Replace the "Implemented" list's script bullet (search for `Professional; a filled-in-but-TODO template for BlazeMeter.`):

```
- A generated `scripts/run-<tool_type>.sh` per setup, written alongside the
  CI/CD files — real, working execution for JMeter and LoadRunner
  Professional; a filled-in-but-TODO template for BlazeMeter.
```

with:

```
- A generated `scripts/run-<tool_type>.sh` per setup, written alongside the
  CI/CD files — real, working execution for all three supported tools
  (JMeter, LoadRunner Professional, BlazeMeter).
```

Replace the "Not implemented yet" list (search for `The real BlazeMeter API call in the generated`):

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

with:

```
- Real pre-run checks beyond what's already implemented per tool (JMeter's
  `verify_scenario_exists`; LoadRunner Professional's
  `verify_controller_access`/`verify_scenario_exists`; BlazeMeter's
  `verify_host_reachable`/`verify_project_exists`/`verify_scenario_exists`)
  — every other configured check, for every tool, is currently only a
  `# TODO precheck: ...` comment (LoadRunner's
  `verify_load_generators_connected` needs Controller-side load-generator
  host-status querying with no local CLI equivalent; `collect_results`'
  meaning is still an open question — see below).
```

Replace the "Performance Testing Tools" section (search for `BlazeMeter's generated script is a template, not a stub:`):

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

with:

```
`generate` writes a `scripts/run-<tool_type>.sh` for every setup, and all
three tools are now equally real, working execution. JMeter resolves the
environment/scenario to their catalog identifiers and runs a real
`jmeter -n -t ...` subprocess (no remote API or credentials needed).
LoadRunner Professional does the same resolution and runs a real
`wlrun -Run -TestPath ...` subprocess, assuming the CI job runs on an agent
co-located with the LoadRunner Controller (see
`docs/superpowers/specs/2026-09-09-loadrunner-local-agent-execution-design.md`).
BlazeMeter authenticates via `BLAZEMETER_API_KEY_ID`/
`BLAZEMETER_API_KEY_SECRET`, starts a test through BlazeMeter's REST API v4,
polls until it finishes (bounded by a BlazeMeter-only `--timeout-minutes`
flag), and downloads a summary report (see
`docs/superpowers/specs/2026-09-09-blazemeter-real-api-execution-design.md`
for the design, including which parts of the API surface are flagged as
best-understanding pending verification against a live account).
```

Replace the "Generated Run Script" bullets (search for `- For \*\*BlazeMeter\*\*, it's a template: real, syntactically valid bash with`):

```
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

with:

```
- For **LoadRunner Professional**, it's also real and complete: it resolves
  `--environment`/`--scenario` the same way (a scenario's identifier is a
  full `.lrs` file path), optionally checks `wlrun_path` resolves to a
  runnable command and/or the `.lrs` file exists (`verify_controller_access`
  / `verify_scenario_exists`), then runs `wlrun -Run -TestPath
  <scenario_identifier> -ResultName run-output/<environment_slug>_
  <scenario_slug>` for real.
- For **BlazeMeter**, it's also real and complete: it optionally checks the
  host is reachable / the project exists / the test exists
  (`verify_host_reachable`/`verify_project_exists`/`verify_scenario_exists`),
  then starts a test via `POST /api/v4/tests/<id>/start`, polls
  `GET /api/v4/masters/<id>/status` until it finishes (bounded by
  `--timeout-minutes`), and downloads a summary report.
```

Replace the "Generated Script Execution Flow" step-4 BlazeMeter bullet and the "Current limitation" paragraph (search for `- \*\*BlazeMeter\*\*: print each remaining configured pre-run check`):

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
   - **BlazeMeter**: optionally verify the host is reachable / the project
     exists / the test exists (`verify_host_reachable`/
     `verify_project_exists`/`verify_scenario_exists`), then start, poll,
     and download a summary report for real.

All three tools now call a real remote/local execution path — see
"BlazeMeter and LoadRunner Real Execution" below for the two remaining
known limitations neither script has closed yet (a CI/CD runner-targeting
gap for LoadRunner, and unverified API-surface assumptions for BlazeMeter).
```

Replace the whole "### BlazeMeter Script Is a Template, Not an Adapter — Partially Resolved" section (search for its heading through the end of its "Recommended change" bullet, i.e. up to but not including "### Test Coverage Is Minimal"):

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

with:

```
### BlazeMeter and LoadRunner Real Execution — Resolved

This gap used to be about Python `ToolAdapter` stubs (`adapters/`) that
defined the right shape but raised `NotImplementedError` for every tool. That
whole adapter/runtime subsystem has been deleted; there is no more Python
execution layer at all. In its place, `generate` writes a
`scripts/run-<tool_type>.sh` per setup, and all three are now real:

- **JMeter is real, working execution** — resolved. The generated script
  resolves the environment/scenario and runs a real `jmeter -n -t <plan> -l
  <results> -e -o <report>` subprocess. Nothing left to do here.
- **LoadRunner Professional is also real, working execution** — resolved
  (see `docs/superpowers/specs/
  2026-09-09-loadrunner-local-agent-execution-design.md` for the design).
  It assumes the CI job runs on a dedicated agent co-located with the
  LoadRunner Controller, resolves the environment/scenario the same way
  JMeter does, and runs `wlrun -Run -TestPath <scenario_identifier>
  -ResultName run-output/<environment_slug>_<scenario_slug>` for real. A
  scenario's catalog `identifier` is a full `.lrs` file path rather than a
  remote name, since `wlrun` has no native "environment" parameter —
  customers author one catalog scenario entry per environment/scenario
  combination they have a file for. `wlrun`'s exit code is known to be
  unreliable on some LoadRunner versions/configurations (can return 0 on a
  failed scenario); nonzero is still treated as failure as the best local
  signal available. **Known limitation**: the generated CI/CD pipeline
  files default to hosted runners (`ubuntu-latest`, a Microsoft-hosted
  Azure pool) that can't run `wlrun` — a customer must hand-retarget the
  generated pipeline to a self-hosted, controller-adjacent agent before
  this actually works (see the user guide's section 10 caveat and
  "Recommended Next Work" above for the follow-up).
- **BlazeMeter is also real, working execution** — resolved (see
  `docs/superpowers/specs/
  2026-09-09-blazemeter-real-api-execution-design.md` for the design). It
  authenticates via `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET`,
  optionally checks host reachability / project existence / test existence
  (`verify_host_reachable`/`verify_project_exists`/`verify_scenario_exists`
  — its own precheck vocabulary, distinct from LoadRunner's
  controller-flavored one), starts a test via
  `POST /api/v4/tests/<id>/start`, polls
  `GET /api/v4/masters/<id>/status` bounded by a `--timeout-minutes` flag,
  and downloads a summary report on success. **Known limitation**: the
  exact status-string vocabulary and report endpoint are this design's
  best understanding of the BlazeMeter API v4, not independently verified
  against current live documentation (which sits behind a login-gated API
  explorer) — flagged in the script's own comments and the generated
  setup README; confirm against a real account before production use.
```

Replace the "### 3. Implement Real Pre-Run Checks" Tasks list (search for `- Implement \`verify_controller_access\`/\`verify_scenario_exists\` for`):

```
- Implement `verify_controller_access`/`verify_scenario_exists` for
  BlazeMeter (currently `# TODO precheck: ...` comments only).
```

with:

```
- [x] `verify_host_reachable` is implemented for BlazeMeter (a plain
  network-level `curl` reachability check against `base_url`).
- [x] `verify_project_exists` is implemented for BlazeMeter (an
  authenticated, workspace-scoped `GET /api/v4/projects/<id>` call).
- [x] `verify_scenario_exists` is implemented for BlazeMeter (an
  authenticated `GET /api/v4/tests/<id>` call).
```

Replace "Recommended Implementation Order" item 11 and item 13 (search for `- \[ \] 11. Fill in the real API call in the generated`):

```
- [ ] 11. Fill in the real API call in the generated
      `run-blazemeter.sh` template.
```

with:

```
- [x] 11. Fill in the real API call in the generated
      `run-blazemeter.sh` script (see `docs/superpowers/specs/
      2026-09-09-blazemeter-real-api-execution-design.md`).
```

and replace:

```
- [ ] 13. Replace the remaining `# TODO precheck: ...` comments in the
      BlazeMeter template with real checks (LoadRunner Professional's
      `verify_controller_access`/`verify_scenario_exists` are now real;
      `verify_load_generators_connected` remains a `# TODO precheck: ...`
      comment for LoadRunner too, since it needs Controller-side
      load-generator host-status querying with no local CLI equivalent).
```

with:

```
- [x] 13. Replace the `# TODO precheck: ...` comments with real checks for
      every tool that has an applicable vocabulary (JMeter's
      `verify_scenario_exists`; LoadRunner Professional's
      `verify_controller_access`/`verify_scenario_exists`; BlazeMeter's
      `verify_host_reachable`/`verify_project_exists`/
      `verify_scenario_exists`). `verify_load_generators_connected` remains
      a `# TODO precheck: ...` comment for LoadRunner, since it needs
      Controller-side load-generator host-status querying with no local
      CLI equivalent — there is no BlazeMeter analog for this check at all
      (it isn't in BlazeMeter's precheck vocabulary).
```

Replace the "Definition of Ready" paragraph about BlazeMeter/LoadRunner (search for `The BlazeMeter and LoadRunner Professional generated scripts can be`):

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

with:

```
The BlazeMeter and LoadRunner Professional generated scripts can be
considered ready for executing tests when:

- [x] All three generated scripts can start and run a test for real —
  resolved: JMeter and LoadRunner Professional run their tool directly;
  BlazeMeter drives its REST API. LoadRunner's real-world usability still
  depends on a CI/CD runner-targeting hand-edit (see "Recommended Next
  Work" above); BlazeMeter's API-surface assumptions still need
  verification against a live account (see "BlazeMeter and LoadRunner
  Real Execution" above).
- Failed runs produce clear summary output (JMeter and LoadRunner don't
  write one yet; BlazeMeter now writes `summary.json`/`report_link.json`
  into its per-invocation results folder — see Milestone 2 item 4,
  "Normalize Runtime Output", for making this consistent across all three).
- Timeout and partial artifact cases are handled (LoadRunner and JMeter
  rely entirely on the CI job's own timeout and the tool's own exit code;
  BlazeMeter has its own script-level `--timeout-minutes` poll bound, the
  first of the three tools to have one).
- Secrets and credentials are documented — N/A for JMeter/LoadRunner (they
  manage no remote credentials at all); BlazeMeter's
  `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET` are documented in the
  generated setup README.
- The generated script's real-execution behavior is covered by automated
  tests using mocks or test doubles (still open for all three — see
  "Recommended Implementation Order" item 14).
```

- [ ] **Step 4: Update `docs/pipeline-generator-user-guide.md`**

Replace (search for `For BlazeMeter it's a template —`):

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

with:

```
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
```

Replace the "Step 8 — Pre-run checks" section (search for `One screen listing four checks`):

```
### Step 8 — Pre-run checks

One screen listing four checks (`verify_controller_access`,
`verify_scenario_exists`, `verify_load_generators_connected`,
`collect_results`). Type comma-separated numbers to select specific ones,
`all`, `none`, or just press Enter to keep whatever was already
enabled (useful when resuming).
```

with:

```
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
```

Replace the generated-script Step 4 BlazeMeter bullet (search for `- \*\*BlazeMeter\*\* — a template. The connection details from`):

```
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

with:

```
- **BlazeMeter** — real, working execution. If configured,
  `verify_host_reachable` checks `base_url` responds at all;
  `verify_project_exists` checks the configured `project_id` exists inside
  `workspace_id`; `verify_scenario_exists` checks the configured test ID
  exists — each an authenticated BlazeMeter API call except the first. Then
  it requires `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET` to be set,
  starts the test via `POST /api/v4/tests/<id>/start`, polls
  `GET /api/v4/masters/<id>/status` every 15 seconds until it finishes
  (bounded by a required `--timeout-minutes` flag the generated pipeline
  always passes), and downloads a summary report into
  `run-output/<environment>_<scenario>/summary.json`. See section 10 for
  the two API-surface details flagged as needing verification against a
  live account.
```

Replace the whole section 10 (search for `## 10. Performance Testing Tools` through the end of its table, i.e. up to but not including `## 11. Validating Configs`):

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
  Enterprise's REST API) were rejected. **Important:** the generated CI/CD
  pipeline files themselves currently target a hosted runner/pool by
  default (`ubuntu-latest` for GitHub Actions, a Microsoft-hosted pool for
  Azure DevOps) — none of these can run `wlrun`. Before a LoadRunner
  Professional setup will actually work, you must hand-edit the generated
  pipeline to target a self-hosted agent that's co-located with the
  Controller (Jenkins' `agent any` is closest to workable already, but
  still needs a Windows-capable shell step). This retargeting isn't
  automated yet — see the generated setup README's "Remaining TODOs".
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

with:

```
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
```

Replace the walkthrough example (search for `## 12. Full Walkthrough Example` through the end of its closing ` ``` `, i.e. up to but not including `## 13. Troubleshooting`):

```
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
#    Step 6: add environments (qa), add scenarios (checkout_smoke)
#    Step 7: add one automated job: post-deploy-smoke, env=qa,
#            scenario=checkout_smoke, timeout=60
#    Step 8: enable verify_scenario_exists, collect_results
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
#    .github/workflows/*.yml

# 4. Sanity-check the generated script locally before handing off
cd generated/github-actions-blazemeter-storefront
./scripts/run-blazemeter.sh --environment qa --scenario checkout_smoke
# -> resolves qa/checkout_smoke to their catalog identifiers, then exits
#    with "ERROR: BlazeMeter execution is not implemented in this
#    generated script yet." — this is the template case (section 10);
#    the API/controller call itself still needs to be filled in.

# 5. Hand off generated/github-actions-blazemeter-storefront/ to Acme,
#    or commit it into their repo directly, per whatever
#    final_pipeline_destination you chose in Step 1.
```
```

with:

```
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
```

Replace the troubleshooting entry (search for `\*\*"ERROR: BlazeMeter execution is not implemented in this generated script`):

```
**"ERROR: BlazeMeter execution is not implemented in this generated script
yet."**
You ran the generated `scripts/run-blazemeter.sh`. It's a template
(section 10) — the connection details are filled in, but the actual API
call is left as a `# TODO` in the script for someone to implement.
JMeter's and LoadRunner Professional's generated scripts have no such gap.
```

with:

```
**"ERROR: BLAZEMETER_API_KEY_ID must be set" / "... BLAZEMETER_API_KEY_SECRET must be set"**
The generated `scripts/run-blazemeter.sh` needs both env vars set before
it will make any API call — set them as CI/CD secrets (see the generated
setup README).

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
```

Replace the "Current Limitations" bullet (search for `\*\*No real execution yet for BlazeMeter.\*\*`):

```
- **No real execution yet for BlazeMeter.** JMeter's and LoadRunner
  Professional's generated scripts are real and complete; BlazeMeter's is
  a template whose API call is still a `# TODO` (section 10).
```

with:

```
- **BlazeMeter's exact API surface is unverified against live
  documentation.** The status-string vocabulary and report endpoint are
  this design's best understanding of the BlazeMeter API v4 (section 10)
  — verify against a real account before relying on this in production.
- **LoadRunner Professional's generated pipelines need manual
  runner-retargeting.** They default to hosted runners that can't reach a
  LoadRunner Controller (section 10) — this isn't automated yet.
```

- [ ] **Step 5: Grep-verify no stale claims remain**

Run: `grep -n "not implemented in this generated script yet\|BlazeMeter.*template\|template.*BlazeMeter\|_render_template_script" CLAUDE.md README.md docs/current-state-and-readiness-plan.md docs/pipeline-generator-user-guide.md`

Expected: no output. Also run: `grep -rn "environment_key}_.*scenario_key\|environment_key>_.*scenario_key" CLAUDE.md README.md docs/current-state-and-readiness-plan.md` to confirm the two stale LoadRunner slug references this task also fixed (found while editing the same paragraphs for BlazeMeter) are gone — expected: no output.

- [ ] **Step 6: Run the full suite one more time**

Run: `python3 -m pytest -q`
Expected: PASS (55 — docs changes don't affect tests, this confirms nothing else drifted).

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md README.md docs/current-state-and-readiness-plan.md docs/pipeline-generator-user-guide.md
git commit -m "Update docs: BlazeMeter's script is now real

Reflects Tasks 1-6: BlazeMeter joins JMeter and LoadRunner Professional
as real, working execution -- this project now has zero template-only
tools. Also fixed two stale environment_key/scenario_key references to
LoadRunner's already-shipped slug-sanitization fix, found while editing
the same paragraphs for BlazeMeter. Updates CLAUDE.md, README.md, the
readiness plan, and the user guide, including a rewritten walkthrough
example that no longer demonstrates the removed 'not implemented yet'
error as expected output."
```
