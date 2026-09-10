# Normalize Runtime Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all three generated scripts (`run-jmeter.sh`, `run-loadrunner_professional.sh`, `run-blazemeter.sh`) write one consistent `run-summary.json` after attempting a run, so a CI/CD step downstream can read the same schema regardless of which tool ran.

**Architecture:** Three shared bash-generation helpers in `renderers/scripts.py` (`_render_json_escape_helper`, `_render_summary_capture_start`, `_render_summary_write`) get added once and called from all three `_render_*_script` functions. Each tool captures its own exit/terminal-status outcome into two local variables (`run_status` — 0/1 — and `summary_status` — `passed`/`failed`/`error`) without letting `set -e` abort the script before the summary is written, then exits with `run_status` at the very end. JMeter also gains the `results_dir` structure BlazeMeter/LoadRunner already have (fixing its overwrite-on-rerun gap as a side effect).

**Tech Stack:** Python 3.9+, pytest, bash (generated scripts), `sed` (new generated-script runtime dependency for JSON-escaping — available everywhere `bash`/`jmeter`/`wlrun`/`curl` already are).

**Spec:** `docs/superpowers/specs/2026-09-10-normalize-runtime-output-design.md`

## Global Constraints

- Every config-derived string embedded into a generated script goes through `renderers/quoting.py`'s `shell_quote` (existing project-wide rule).
- `run-summary.json` is written only after all prechecks pass and the tool is actually invoked — never for a precheck failure (missing test plan, `wlrun` not found, missing scenario file, BlazeMeter host/project/scenario checks). Those keep exiting immediately with their existing one-line stderr message, unchanged.
- `environment`/`scenario` values embedded into `run-summary.json` MUST go through the new `json_escape` bash helper first — they carry the raw, unsanitized `--environment`/`--scenario` CLI values (catalog keys), unlike `run_id`/`report_link`/`results_dir`, which are built from already-sanitized slugs (`safe_filename_component`) and therefore need no escaping.
- BlazeMeter's existing `summary.json`/`report_link.json` (the raw BlazeMeter API report passthrough) are unchanged, written on the same `ENDED`-only path as today. `run-summary.json` is new, additional, and separate.
- `status` is derived purely from each tool's own exit code or terminal API status — no parsing of `.jtl`/results content. `status` values are exactly `passed` / `failed` / `error` (three values, not two) — `error` is reserved for BlazeMeter's "never reached a terminal status" (timeout) case.
- Unlike the two prior plans in this directory, this plan intentionally changes all three tools' generated script output (JMeter especially — it gains a `results_dir` it didn't have before). Byte-identical output is NOT a constraint here.
- Run `python3 -m pytest -q` from the `pipelineGenerator` directory after every task; it must be green before moving to the next task. Baseline before Task 1: 58 passed.

---

### Task 1: Shared summary helpers + JMeter results_dir and run-summary.json

**Files:**
- Modify: `src/pipeline_generator/renderers/scripts.py`
- Test: `tests/test_tool_scripts.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (for Tasks 2 and 3 to reuse verbatim): `_render_json_escape_helper() -> str`, `_render_summary_capture_start() -> str`, `_render_summary_write(tool_type: str) -> str`, all defined in `scripts.py` near `_render_slug_resolvers`. Every caller must have these local bash variables in scope before calling `_render_summary_write`: `run_id`, `report_link`, `artifact_status`, `summary_status`, `results_dir`, `environment_key`, `scenario_key`, and the three variables `_render_summary_capture_start()` declares (`started_at_iso`, `started_at_epoch`, `started_at_compact`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tool_scripts.py` (add `import json` to the existing imports at the top of the file, alongside the existing `import os`/`import shlex`/`import subprocess`):

```python
def test_json_escape_helper_produces_valid_json_string(tmp_path: Path) -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": ""})
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    hostile = 'back\\slash "and quote"'
    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}"; json_escape {shlex.quote(hostile)}'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    escaped = result.stdout.rstrip("\n")
    assert json.loads(f'"{escaped}"') == hostile


def test_render_jmeter_script_uses_results_dir_and_slug_resolvers(tmp_path: Path) -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": ""})
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "resolve_environment_slug() {" in content
    assert "resolve_scenario_slug() {" in content
    assert "json_escape() {" in content
    assert 'local results_dir="run-output/${environment_slug}_${scenario_slug}"' in content
    assert '-l "$results_dir/results.jtl"' in content
    assert '-o "$results_dir/report"' in content
    assert '> "$results_dir/run-summary.json"' in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_jmeter_script_writes_passing_run_summary(tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "jmeter").write_text("""#!/usr/bin/env bash
logfile=""
outdir=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-l" ]; then logfile="$arg"; fi
  if [ "$prev" = "-o" ]; then outdir="$arg"; fi
  prev="$arg"
done
mkdir -p "$outdir"
echo "<html></html>" > "$outdir/index.html"
touch "$logfile"
exit 0
""")
    (stub_bin / "jmeter").chmod(0o755)

    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": "jmeter"})
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout_smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["tool"] == "jmeter"
    assert summary["status"] == "passed"
    assert summary["artifact_status"] == "complete"
    assert summary["environment"] == "qa"
    assert summary["scenario"] == "checkout_smoke"
    assert summary["results_dir"] == "run-output/qa_checkout_smoke"
    assert summary["report_link"] == "run-output/qa_checkout_smoke/report/index.html"
    assert set(summary.keys()) == {
        "tool", "run_id", "environment", "scenario", "status", "started_at", "ended_at",
        "duration_seconds", "report_link", "results_dir", "artifact_status",
    }


def test_render_jmeter_script_writes_failing_run_summary_and_propagates_exit_code(tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "jmeter").write_text("#!/usr/bin/env bash\nexit 2\n")
    (stub_bin / "jmeter").chmod(0o755)

    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": "jmeter"})
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1

    summary_path = tmp_path / "run-output" / "qa_checkout_smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["artifact_status"] == "incomplete"


def test_render_jmeter_script_no_run_summary_on_precheck_failure(tmp_path: Path) -> None:
    config = _base_config(
        "jmeter",
        {"test_plan_path": "nonexistent-plan.jmx", "jmeter_bin": "jmeter"},
        checks=["verify_scenario_exists"],
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "Test plan not found" in result.stderr
    run_output = tmp_path / "run-output"
    assert not run_output.exists() or not list(run_output.rglob("run-summary.json"))


def test_render_jmeter_script_rerun_with_different_scenario_uses_separate_dirs(tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "jmeter").write_text("""#!/usr/bin/env bash
logfile=""
outdir=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-l" ]; then logfile="$arg"; fi
  if [ "$prev" = "-o" ]; then outdir="$arg"; fi
  prev="$arg"
done
mkdir -p "$outdir"
echo "<html></html>" > "$outdir/index.html"
touch "$logfile"
exit 0
""")
    (stub_bin / "jmeter").chmod(0o755)

    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": "jmeter"})
    config["catalog"]["scenarios"] = [
        {"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"},
        {"key": "checkout_full", "name": "Checkout Full", "identifier": "SC-2"},
    ]
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"

    for scenario in ("checkout_smoke", "checkout_full"):
        result = subprocess.run(
            ["bash", str(script_path), "--environment", "qa", "--scenario", scenario],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr

    assert (tmp_path / "run-output" / "qa_checkout_smoke" / "run-summary.json").exists()
    assert (tmp_path / "run-output" / "qa_checkout_full" / "run-summary.json").exists()
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/test_tool_scripts.py -k "json_escape or results_dir_and_slug or writes_passing_run_summary or writes_failing_run_summary or no_run_summary_on_precheck or rerun_with_different_scenario" -v`
Expected: FAIL — `json_escape: command not found`, `results_dir` assertions fail against the current flat JMeter output, `run-summary.json` never gets created.

- [ ] **Step 3: Add the three shared helpers**

In `src/pipeline_generator/renderers/scripts.py`, add these three functions right after `_render_slug_resolvers` (before `_render_arg_parsing`):

```python
def _render_json_escape_helper() -> str:
    return r"""json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}"""


def _render_summary_capture_start() -> str:
    return """  local started_at_iso
  local started_at_epoch
  local started_at_compact
  started_at_iso="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  started_at_epoch="$(date -u +%s)"
  started_at_compact="$(date -u +%Y%m%dT%H%M%SZ)"
"""


def _render_summary_write(tool_type: str) -> str:
    return f"""  local ended_at_iso
  local ended_at_epoch
  ended_at_iso="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  ended_at_epoch="$(date -u +%s)"
  local duration_seconds=$((ended_at_epoch - started_at_epoch))
  local environment_escaped
  local scenario_escaped
  environment_escaped="$(json_escape "$environment_key")"
  scenario_escaped="$(json_escape "$scenario_key")"
  printf '{{"tool": "{tool_type}", "run_id": "%s", "environment": "%s", "scenario": "%s", "status": "%s", "started_at": "%s", "ended_at": "%s", "duration_seconds": %s, "report_link": "%s", "results_dir": "%s", "artifact_status": "%s"}}' \\
    "$run_id" "$environment_escaped" "$scenario_escaped" "$summary_status" "$started_at_iso" "$ended_at_iso" "$duration_seconds" "$report_link" "$results_dir" "$artifact_status" \\
    > "$results_dir/run-summary.json"
"""
```

`json_escape` doubles backslashes first, then escapes double quotes — the order matters (escaping quotes first would double the backslash the quote-escape itself just inserted).

- [ ] **Step 4: Rewrite `_render_jmeter_script`**

Replace the entire existing `_render_jmeter_script` function body with:

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

{_render_slug_resolvers(package)}

{_render_json_escape_helper()}

main() {{
{_render_arg_parsing()}
  mkdir -p run-output

  local test_plan_path={shell_quote(test_plan_path)}
  local jmeter_bin={shell_quote(jmeter_bin)}
{precheck}{precheck_comments}
  local environment_slug
  local scenario_slug
  environment_slug="$(resolve_environment_slug "$environment_key")"
  scenario_slug="$(resolve_scenario_slug "$scenario_key")"
  local results_dir="run-output/${{environment_slug}}_${{scenario_slug}}"
  mkdir -p "$results_dir"

{_render_summary_capture_start()}
  local run_id="${{environment_slug}}_${{scenario_slug}}_${{started_at_compact}}"
  local report_link="$results_dir/report/index.html"

  local run_status=0
  if ! "$jmeter_bin" -n -t "$test_plan_path" -l "$results_dir/results.jtl" -e -o "$results_dir/report" \\
    -Jenvironment="$environment_identifier" -Jscenario="$scenario_identifier"; then
    run_status=1
  fi

  local summary_status="passed"
  if [ "$run_status" -ne 0 ]; then
    summary_status="failed"
  fi
  local artifact_status="incomplete"
  if [ -f "$results_dir/results.jtl" ] && [ -f "$results_dir/report/index.html" ]; then
    artifact_status="complete"
  fi
{_render_summary_write("jmeter")}
  exit "$run_status"
}}

if [ "${{BASH_SOURCE[0]:-$0}}" = "$0" ]; then
  main "$@"
fi
"""
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_tool_scripts.py -v`
Expected: PASS for the 6 new tests AND every pre-existing test in this file (the existing JMeter tests only do substring/exact-match checks against text that is still present unchanged, e.g. `'"$jmeter_bin" -n -t "$test_plan_path"'` — none of them assert the old flat `run-output/results.jtl` path).

- [ ] **Step 6: Run the full test suite**

Run: `python3 -m pytest -q`
Expected: 64 passed (58 baseline + 6 new).

- [ ] **Step 7: Commit**

```bash
git add src/pipeline_generator/renderers/scripts.py tests/test_tool_scripts.py
git commit -m "feat: add run-summary.json and results_dir to JMeter's generated script"
```

---

### Task 2: LoadRunner run-summary.json

**Files:**
- Modify: `src/pipeline_generator/renderers/scripts.py`
- Test: `tests/test_tool_scripts.py`

**Interfaces:**
- Consumes: `_render_json_escape_helper()`, `_render_summary_capture_start()`, `_render_summary_write(tool_type)` from Task 1, unchanged.
- Produces: nothing new for later tasks (LoadRunner and JMeter don't share tool-specific code beyond the Task 1 helpers).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tool_scripts.py`:

```python
def test_render_loadrunner_script_writes_passing_run_summary(tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "wlrun").write_text("""#!/usr/bin/env bash
resultname=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-ResultName" ]; then resultname="$arg"; fi
  prev="$arg"
done
mkdir -p "$resultname"
echo "result" > "$resultname/results.xml"
exit 0
""")
    (stub_bin / "wlrun").chmod(0o755)

    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout_smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["tool"] == "loadrunner_professional"
    assert summary["status"] == "passed"
    assert summary["artifact_status"] == "complete"
    assert summary["report_link"] == "run-output/qa_checkout_smoke"


def test_render_loadrunner_script_writes_failing_run_summary_and_propagates_exit_code(tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "wlrun").write_text("#!/usr/bin/env bash\nexit 3\n")
    (stub_bin / "wlrun").chmod(0o755)

    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1

    summary_path = tmp_path / "run-output" / "qa_checkout_smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["artifact_status"] == "incomplete"


def test_render_loadrunner_script_no_run_summary_on_precheck_failure(tmp_path: Path) -> None:
    config = _base_config(
        "loadrunner_professional", {"wlrun_path": "wlrun"}, checks=["verify_scenario_exists"]
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"

    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "Scenario file not found" in result.stderr
    run_output = tmp_path / "run-output"
    assert not run_output.exists() or not list(run_output.rglob("run-summary.json"))
```

(`_base_config`'s default scenario catalog entry has `"identifier": "SC-1"`, not a real file, so `verify_scenario_exists` fails naturally without needing a stub.)

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/test_tool_scripts.py -k loadrunner_script_writes_or_loadrunner_script_no_run_summary -v`

If that `-k` expression matches nothing (pytest `-k` uses substring/boolean matching on test names, and these three names don't share one substring), instead run: `python3 -m pytest tests/test_tool_scripts.py -k "loadrunner and (passing_run_summary or failing_run_summary or no_run_summary)" -v`
Expected: FAIL — no `run-summary.json` is ever created by the current LoadRunner script.

- [ ] **Step 3: Rewrite `_render_loadrunner_script`**

Replace the entire existing `_render_loadrunner_script` function body with:

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

    remaining_checks = [check for check in checks if check not in {"verify_controller_access", "verify_scenario_exists"}]
    precheck_comments = "\n".join(f"  # TODO precheck: {check}" for check in remaining_checks)
    if precheck_comments:
        precheck_comments = f"\n{precheck_comments}\n"

    return f"""#!/usr/bin/env bash
set -euo pipefail

{_render_resolvers(package)}

{_render_slug_resolvers(package)}

{_render_json_escape_helper()}

main() {{
{_render_arg_parsing()}
  mkdir -p run-output

  local wlrun_path={shell_quote(wlrun_path)}
{controller_check}{scenario_check}{precheck_comments}
  local environment_slug
  local scenario_slug
  environment_slug="$(resolve_environment_slug "$environment_key")"
  scenario_slug="$(resolve_scenario_slug "$scenario_key")"
  local results_dir="run-output/${{environment_slug}}_${{scenario_slug}}"
  mkdir -p "$results_dir"

{_render_summary_capture_start()}
  local run_id="${{environment_slug}}_${{scenario_slug}}_${{started_at_compact}}"
  local report_link="$results_dir"

  # wlrun's exit code is known to be unreliable on some LoadRunner
  # versions/configurations (it can return 0 even when a scenario had
  # errors). We treat nonzero as failure since it is the best signal
  # available locally; check the results directory's own reports for the
  # authoritative pass/fail status.
  local run_status=0
  if ! "$wlrun_path" -Run -TestPath "$scenario_identifier" -ResultName "$results_dir"; then
    run_status=1
  fi

  local summary_status="passed"
  if [ "$run_status" -ne 0 ]; then
    summary_status="failed"
  fi
  local artifact_status="incomplete"
  if [ -n "$(ls -A "$results_dir" 2>/dev/null)" ]; then
    artifact_status="complete"
  fi
{_render_summary_write("loadrunner_professional")}
  exit "$run_status"
}}

if [ "${{BASH_SOURCE[0]:-$0}}" = "$0" ]; then
  main "$@"
fi
"""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_tool_scripts.py -v`
Expected: PASS for the 3 new tests and every pre-existing LoadRunner test (they check substrings like `'"$wlrun_path" -Run -TestPath "$scenario_identifier" -ResultName "$results_dir"'`, which is still present unchanged).

- [ ] **Step 5: Run the full test suite**

Run: `python3 -m pytest -q`
Expected: 67 passed (64 from Task 1 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add src/pipeline_generator/renderers/scripts.py tests/test_tool_scripts.py
git commit -m "feat: add run-summary.json to LoadRunner Professional's generated script"
```

---

### Task 3: BlazeMeter run-summary.json (all three terminal outcomes)

**Files:**
- Modify: `src/pipeline_generator/renderers/scripts.py`
- Test: `tests/test_tool_scripts.py`

**Interfaces:**
- Consumes: `_render_json_escape_helper()`, `_render_summary_capture_start()`, `_render_summary_write(tool_type)` from Task 1, unchanged.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tool_scripts.py`:

```python
def test_render_blazemeter_script_writes_run_summary_on_ended(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "curl").write_text("""#!/usr/bin/env bash
if [[ "$*" == *"/start"* ]]; then
  echo '{"result": {"id": 999}}'
  exit 0
fi
if [[ "$*" == *"/status"* ]]; then
  echo '{"result": {"status": "ENDED"}}'
  exit 0
fi
if [[ "$*" == *"/summary"* ]]; then
  echo '{}'
  exit 0
fi
exit 0
""")
    (stub_bin / "curl").chmod(0o755)
    (stub_bin / "jq").write_text("""#!/usr/bin/env bash
input="$(cat)"
expr="${@: -1}"
case "$expr" in
  '.result.id')
    echo "$input" | grep -o '"id": *[0-9]*' | grep -o '[0-9]*$'
    ;;
  '.result.status')
    echo "$input" | grep -o '"status": *"[A-Z]*"' | grep -o '"[A-Z]*"$' | tr -d '"'
    ;;
  *)
    exit 1
    ;;
esac
""")
    (stub_bin / "jq").chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["BLAZEMETER_API_KEY_ID"] = "id"
    env["BLAZEMETER_API_KEY_SECRET"] = "secret"

    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke", "--timeout-minutes", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout_smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["tool"] == "blazemeter"
    assert summary["run_id"] == "999"
    assert summary["status"] == "passed"
    assert summary["artifact_status"] == "complete"
    assert summary["report_link"] == "https://a.blazemeter.com/app/#/masters/999/summary"


def test_render_blazemeter_script_writes_run_summary_on_error_status(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "curl").write_text("""#!/usr/bin/env bash
if [[ "$*" == *"/start"* ]]; then
  echo '{"result": {"id": 999}}'
  exit 0
fi
if [[ "$*" == *"/status"* ]]; then
  echo '{"result": {"status": "ERROR"}}'
  exit 0
fi
exit 0
""")
    (stub_bin / "curl").chmod(0o755)
    (stub_bin / "jq").write_text("""#!/usr/bin/env bash
input="$(cat)"
expr="${@: -1}"
case "$expr" in
  '.result.id')
    echo "$input" | grep -o '"id": *[0-9]*' | grep -o '[0-9]*$'
    ;;
  '.result.status')
    echo "$input" | grep -o '"status": *"[A-Z]*"' | grep -o '"[A-Z]*"$' | tr -d '"'
    ;;
  *)
    exit 1
    ;;
esac
""")
    (stub_bin / "jq").chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["BLAZEMETER_API_KEY_ID"] = "id"
    env["BLAZEMETER_API_KEY_SECRET"] = "secret"

    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke", "--timeout-minutes", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "ERROR: BlazeMeter test ended with status ERROR" in result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout_smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["artifact_status"] == "incomplete"


def test_render_blazemeter_script_writes_run_summary_on_timeout(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "curl").write_text("""#!/usr/bin/env bash
if [[ "$*" == *"/start"* ]]; then
  echo '{"result": {"id": 999}}'
  exit 0
fi
exit 0
""")
    (stub_bin / "curl").chmod(0o755)
    (stub_bin / "jq").write_text("""#!/usr/bin/env bash
input="$(cat)"
expr="${@: -1}"
case "$expr" in
  '.result.id')
    echo "$input" | grep -o '"id": *[0-9]*' | grep -o '[0-9]*$'
    ;;
  *)
    exit 1
    ;;
esac
""")
    (stub_bin / "jq").chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["BLAZEMETER_API_KEY_ID"] = "id"
    env["BLAZEMETER_API_KEY_SECRET"] = "secret"

    # --timeout-minutes 0 makes the poll deadline equal to "now", so the
    # while loop's condition is already false on its first check -- the
    # loop body (which would otherwise poll /status and sleep 15 real
    # seconds) never runs, keeping this test fast while still exercising
    # the "never reached a terminal status" branch exactly as a real
    # timeout would reach it.
    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke", "--timeout-minutes", "0"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "Timed out after 0 minutes" in result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout_smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "error"
    assert summary["artifact_status"] == "incomplete"


def test_render_blazemeter_script_no_run_summary_when_master_id_missing(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "curl").write_text("""#!/usr/bin/env bash
echo '<html><body>502 Bad Gateway</body></html>'
exit 0
""")
    (stub_bin / "curl").chmod(0o755)
    (stub_bin / "jq").write_text("#!/usr/bin/env bash\nexit 1\n")
    (stub_bin / "jq").chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["BLAZEMETER_API_KEY_ID"] = "id"
    env["BLAZEMETER_API_KEY_SECRET"] = "secret"

    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke", "--timeout-minutes", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1

    run_output = tmp_path / "run-output"
    assert not run_output.exists() or not list(run_output.rglob("run-summary.json"))
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/test_tool_scripts.py -k "writes_run_summary_on_ended or writes_run_summary_on_error_status or writes_run_summary_on_timeout or no_run_summary_when_master_id_missing" -v`
Expected: FAIL — the current script never writes `run-summary.json`, and its `ERROR`/`ABORTED`/timeout branches all `exit 1` immediately today (which the "on_error_status" and "on_timeout" tests would otherwise already pass for stderr/exit-code alone — they fail specifically on the `run-summary.json` assertions).

- [ ] **Step 3: Rewrite `_render_blazemeter_script`**

Replace the entire existing `_render_blazemeter_script` function body with:

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
  local project_status
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
  local test_status
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

{_render_json_escape_helper()}

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
  master_id="$(echo "$start_response" | jq -r '.result.id' 2>/dev/null)" || master_id=""
  if [ -z "$master_id" ] || [ "$master_id" = "null" ]; then
    echo "ERROR: BlazeMeter did not return a master id when starting the test. Response: $start_response" >&2
    exit 1
  fi

{_render_summary_capture_start()}
  local run_id="$master_id"
  local report_link="$base_url/app/#/masters/$master_id/summary"
  local artifact_status="incomplete"
  local run_status=0

  # NOTE: the exact status-string vocabulary below (ENDED/ERROR/ABORTED)
  # and the reports/main/summary endpoint used after the loop are our best
  # understanding of the BlazeMeter API v4 as of this writing -- verify
  # both against a live BlazeMeter account before relying on this in
  # production.
  local deadline=$(( $(date +%s) + timeout_minutes * 60 ))
  local status="UNKNOWN"
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if ! status="$(curl -s -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
      "$base_url/api/v4/masters/$master_id/status" | jq -r '.result.status' 2>/dev/null)"; then
      echo "WARNING: failed to poll BlazeMeter status (network or parse error); retrying" >&2
      status="UNKNOWN"
      sleep 15
      continue
    fi
    case "$status" in
      ENDED|ERROR|ABORTED) break ;;
    esac
    sleep 15
  done

  local summary_status
  case "$status" in
    ENDED)
      summary_status="passed"
      curl -s -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
        "$base_url/api/v4/masters/$master_id/reports/main/summary" > "$results_dir/summary.json"
      printf '{{"master_id": "%s", "report_url": "%s/app/#/masters/%s/summary"}}' \\
        "$master_id" "$base_url" "$master_id" > "$results_dir/report_link.json"
      artifact_status="complete"
      ;;
    ERROR|ABORTED)
      echo "ERROR: BlazeMeter test ended with status $status (master $master_id)" >&2
      summary_status="failed"
      run_status=1
      ;;
    *)
      echo "ERROR: Timed out after $timeout_minutes minutes waiting for BlazeMeter test to finish (master $master_id, last status: $status)" >&2
      summary_status="error"
      run_status=1
      ;;
  esac

{_render_summary_write("blazemeter")}
  exit "$run_status"
}}

if [ "${{BASH_SOURCE[0]:-$0}}" = "$0" ]; then
  main "$@"
fi
"""
```

Note the `ERROR|ABORTED` and timeout branches no longer `exit 1` inline — they fall through to the shared `_render_summary_write` call and `exit "$run_status"` at the end of `main()`, which preserves the same final exit code (1) and the same stderr message, just after the summary file is written instead of before.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_tool_scripts.py -v`
Expected: PASS for the 4 new tests and every pre-existing BlazeMeter test, including `test_render_blazemeter_script_tolerates_transient_poll_failure` and `test_render_blazemeter_script_shows_raw_response_on_non_json_start_reply` (both exercise code paths this task didn't change: the former reaches `ENDED` exactly as before, the latter still exits before `_render_summary_capture_start()` is ever reached).

- [ ] **Step 5: Run the full test suite**

Run: `python3 -m pytest -q`
Expected: 71 passed (67 from Task 2 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add src/pipeline_generator/renderers/scripts.py tests/test_tool_scripts.py
git commit -m "feat: add run-summary.json to BlazeMeter's generated script for all three terminal outcomes"
```

---

### Task 4: Documentation updates

**Files:**
- Modify: `src/pipeline_generator/renderers/readme.py`
- Test: `tests/test_readme_renderer.py`
- Modify: `CLAUDE.md`
- Modify: `docs/current-state-and-readiness-plan.md`
- Modify: `docs/pipeline-generator-user-guide.md`

**Interfaces:**
- Consumes: nothing code-level from earlier tasks (this task only touches generated-README text and docs).

- [ ] **Step 1: Write the failing README test**

Add to `tests/test_readme_renderer.py`:

```python
def test_readme_mentions_run_summary_json_for_every_tool() -> None:
    for tool_type, connection in (
        ("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": ""}),
        ("loadrunner_professional", {"wlrun_path": "wlrun"}),
        ("blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "1", "project_id": "2"}),
    ):
        config = _base_config(tool_type, connection)
        package = build_generic_package(config)
        readme = render_setup_readme(config, package)
        assert "run-summary.json" in readme
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_readme_renderer.py::test_readme_mentions_run_summary_json_for_every_tool -v`
Expected: FAIL — `render_setup_readme`'s output doesn't mention `run-summary.json` yet.

- [ ] **Step 3: Update `render_setup_readme`'s Files section**

In `src/pipeline_generator/renderers/readme.py`, replace:

```python
    lines.extend(
        [
            "## Files",
            "",
            "- `customer.yaml`: setup source of truth",
            "- generated pipeline files: CI/CD-specific assets",
            f"- `{script_name}`: the script the generated pipeline calls to run the performance test",
            "- this README: setup guidance",
            "",
        ]
    )
```

with:

```python
    lines.extend(
        [
            "## Files",
            "",
            "- `customer.yaml`: setup source of truth",
            "- generated pipeline files: CI/CD-specific assets",
            f"- `{script_name}`: the script the generated pipeline calls to run the performance test",
            "- `run-output/<environment>_<scenario>/run-summary.json`: machine-readable run status "
            "(tool, status, timestamps, duration, report link, artifact status), written after each run",
            "- this README: setup guidance",
            "",
        ]
    )
```

- [ ] **Step 4: Run the test to verify it passes, then the full suite**

Run: `python3 -m pytest tests/test_readme_renderer.py -v`
Expected: PASS for all readme tests, including the new one and the 4 pre-existing ones.

Run: `python3 -m pytest -q`
Expected: 72 passed (71 from Task 3 + 1 new).

- [ ] **Step 5: Update `CLAUDE.md`**

In `CLAUDE.md`, immediately after the existing paragraph ending `` `config/schema.py`. `` (the paragraph describing BlazeMeter's `AUTH_TYPES`, right before the `` `generate` re-validates the config before doing anything `` paragraph), insert a new paragraph:

```markdown
All three tools now also write a normalized
`run-output/<environment_slug>_<scenario_slug>/run-summary.json` after the
tool run is actually attempted (never for a pre-run-check failure, which
still exits immediately with its existing one-line stderr message) — one
shared schema (`tool`, `run_id`, `environment`, `scenario`, `status`
(`passed`/`failed`/`error`), `started_at`/`ended_at`/`duration_seconds`,
`report_link`, `results_dir`, `artifact_status`) produced by shared
`_render_summary_capture_start`/`_render_summary_write` helpers in
`scripts.py`, so a CI/CD step downstream of any of the three
`run-<tool_type>.sh` scripts can read one consistent file regardless of
which tool ran. `environment`/`scenario` are passed through a generated
`json_escape` bash function before embedding, since they carry the raw,
unsanitized `--environment`/`--scenario` CLI values (catalog keys) rather
than the already-sanitized slugs `results_dir` is built from. This also
gave JMeter its own `results_dir` for the first time — it previously wrote
flat into `run-output/`, so a second run silently overwrote the first.
BlazeMeter's own `summary.json`/`report_link.json` (its raw API-report
passthrough) are unchanged and remain separate from `run-summary.json`.
```

- [ ] **Step 6: Update `docs/current-state-and-readiness-plan.md`**

Three edits:

1. In the "Generated Script Execution Flow" section, replace:

```markdown
3. Create `run-output/`.
4. Run the tool:
   - **JMeter**: optionally verify the test plan file exists (if
     `verify_scenario_exists` is configured), then run `jmeter -n -t ...`
     for real.
```

with:

```markdown
3. Create `run-output/`.
4. Run the tool:
   - **JMeter**: optionally verify the test plan file exists (if
     `verify_scenario_exists` is configured), then create
     `run-output/<environment_slug>_<scenario_slug>/` and run
     `jmeter -n -t ...` for real, writing `results.jtl`/`report/` into
     that per-run folder.
```

2. Right after the "All three tools now call a real remote/local execution path — see..." paragraph in that same section, add a new paragraph:

```markdown
5. Write `run-output/<environment_slug>_<scenario_slug>/run-summary.json`
   — one shared schema across all three tools (`tool`, `run_id`,
   `environment`, `scenario`, `status`, `started_at`/`ended_at`/
   `duration_seconds`, `report_link`, `results_dir`, `artifact_status`),
   written once the tool run is attempted and its outcome is known (never
   for a pre-run-check failure). See "Normalize Runtime Output" below.
```

3. Replace the entire `### 4. Normalize Runtime Output` section (heading through its bullet list, i.e. from `### 4. Normalize Runtime Output` up to but not including `## Recommended Implementation Order`) with:

```markdown
### 4. Normalize Runtime Output — Resolved

All three generated scripts now write
`run-output/<environment_slug>_<scenario_slug>/run-summary.json` after
attempting a run, using one shared schema: `tool`, `run_id`, `environment`,
`scenario`, `status` (`passed`/`failed`/`error`), `started_at`/`ended_at`/
`duration_seconds`, `report_link`, `results_dir`, `artifact_status`
(`complete`/`incomplete`). `status` is derived purely from each tool's own
exit code or terminal API status (JMeter/`wlrun` exit code, BlazeMeter's
`ENDED`/`ERROR`/`ABORTED`/timeout) — not from parsing `.jtl`/results
content, matching the existing, documented precedent that `wlrun`'s exit
code is "best local signal available, known to be unreliable on some
versions." `run-summary.json` is written only once prechecks pass and the
tool is actually invoked; a precheck failure still exits immediately with
its existing one-line stderr message and no JSON artifact. This also gave
JMeter a `run-output/<environment_slug>_<scenario_slug>/` folder for the
first time, fixing its previous overwrite-on-rerun gap as a side effect.
BlazeMeter's pre-existing `summary.json`/`report_link.json` (its raw API
report passthrough) are unchanged and remain separate from
`run-summary.json`. See
`docs/superpowers/specs/2026-09-10-normalize-runtime-output-design.md` for
the full design.
```

- [ ] **Step 7: Update `docs/pipeline-generator-user-guide.md`**

Two edits:

1. In section 8 ("Running Performance Tests"), replace the "What the script does:" numbered list:

```markdown
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
```

with:

```markdown
What the script does:

1. Parses `--environment` and `--scenario` (both required; BlazeMeter also
   requires `--timeout-minutes`).
2. Resolves each to its catalog `identifier` using generated shell
   functions (`resolve_environment_identifier`/
   `resolve_scenario_identifier`) — an unrecognized key prints
   `Unknown environment key: ...` / `Unknown scenario key: ...` and exits
   non-zero.
3. Creates `run-output/<environment_slug>_<scenario_slug>/` (all three
   tools now use this same per-run folder, resolved via generated
   `resolve_environment_slug`/`resolve_scenario_slug` functions).
4. Runs the tool.
5. Writes `run-summary.json` into that folder — see "Run Summaries" below.
   This step is skipped if a precheck in step 4 already failed.
```

2. Immediately after the BlazeMeter bullet's paragraph (ending `...verify against a real account before production use.`) and before the "Bad input..." paragraph, insert a new subsection:

```markdown
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
  "artifact_status": "complete"
}
```

`status` is `passed`, `failed`, or `error` (`error` only occurs for
BlazeMeter, when it times out before reaching a terminal API status —
JMeter/LoadRunner's own exit codes only ever produce `passed`/`failed`).
`report_link` is a relative filesystem path for JMeter/LoadRunner and a
BlazeMeter web UI URL for BlazeMeter — don't assume it's always a URL.
This file is separate from BlazeMeter's own `summary.json`/
`report_link.json` (its raw API report), which are unchanged.
```

- [ ] **Step 8: Broad staleness sweep**

Before committing, run a case-insensitive search across the docs this task
touched plus `CLAUDE.md` for any remaining stale claims this task's fixed
list above might have missed — exact-string greps have twice already
missed paragraph-reworded stale references during this project's doc
passes (both the LoadRunner and BlazeMeter documentation tasks needed a
second broader-search round after their first pass):

```bash
grep -rni "doesn't write\|don't write\|flat into run-output\|no summary\|not.*normalized" CLAUDE.md docs/current-state-and-readiness-plan.md docs/pipeline-generator-user-guide.md
```

Fix anything this turns up that still describes JMeter/LoadRunner as not
writing a summary, or JMeter as writing flat into `run-output/` without a
per-run folder.

- [ ] **Step 9: Run the full test suite one final time**

Run: `python3 -m pytest -q`
Expected: 72 passed.

- [ ] **Step 10: Commit**

```bash
git add src/pipeline_generator/renderers/readme.py tests/test_readme_renderer.py CLAUDE.md docs/current-state-and-readiness-plan.md docs/pipeline-generator-user-guide.md
git commit -m "docs: document run-summary.json across CLAUDE.md, readiness plan, user guide, and generated README"
```
