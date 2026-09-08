# Generator-Only Tool Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `pipeline-generator`'s `run`/`runtime`/`adapters` subsystem entirely and replace it with a real (JMeter) or template (BlazeMeter/LoadRunner Professional) shell script that `generate` writes alongside the CI/CD files, which the generated pipeline calls directly — `pipeline-generator` never executes or contacts anything after generation time.

**Architecture:** `generate_assets` gains a new renderer call, `render_tool_script`, that writes `scripts/run-<tool_type>.sh` per setup. The script always takes `--environment <key> --scenario <key>` and resolves the key to its catalog `identifier` itself via generated shell functions using exact string comparison (never `case`/glob matching, since catalog keys are config-controlled data). The three CI/CD renderers change their "run the test" step to call this script instead of `pipeline-generator run`, and drop the now-unnecessary Python setup/install steps.

**Tech Stack:** Python 3.9+, PyYAML, pytest, bash (generated scripts only — no new Python dependency).

**Spec:** `docs/superpowers/specs/2026-09-08-generator-only-tool-scripts-design.md`

## Global Constraints

- No Python code may execute or contact a remote system or the real test tool, ever, at any point after `generate` finishes writing files.
- Every config-controlled string embedded in generated shell/YAML/Groovy text must go through the existing `renderers/quoting.py` helpers (`shell_quote`, `yaml_dquote`, `groovy_squote`) — no raw f-string interpolation of catalog/job values into generated output.
- Key→identifier resolution inside generated scripts uses exact string comparison (`[ "$1" = '...' ]`), never a `case` statement, since catalog keys are arbitrary config data and `case` patterns treat `*`, `?`, `[`, `]` as glob metacharacters.
- `tests/test_example_configs.py` and `tests/test_generate_assets_path_safety.py` must keep passing unmodified in behavior (only exact-match text may need small additive assertions, per task).
- Run `pytest` after every task; all tests must pass before moving to the next task.

---

### Task 1: Extend the generic model with identifier and automated-job refs

**Files:**
- Modify: `src/pipeline_generator/generator/generic_model.py` (all of it, 42 lines)
- Modify: `src/pipeline_generator/generator/context.py` (all of it, 72 lines)
- Test: `tests/test_generic_model.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `InputOption.identifier: str`; `GenericPipelinePackage.tool_type: str`, `.environments: list[InputOption]`, `.scenarios: list[InputOption]`; `AutomatedJobSpec.environment_ref: str`, `.scenario_ref: str`. All later tasks (2 onward) rely on these exact names.

This is needed because `render_tool_script` (Task 3) must build a key→identifier lookup for every catalog entry regardless of whether a manual pipeline exists, and because the CI/CD renderers (Tasks 6-8) need to know which tool's script to call and which environment/scenario key an automated job resolves to — none of which the current generic model exposes.

- [ ] **Step 1: Write the failing test**

Create `tests/test_generic_model.py`:

```python
from pipeline_generator.generator.context import build_generic_package


def _config() -> dict:
    return {
        "setup": {"id": "generic-model-test", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "tool": {"type": "jmeter", "connection": {}},
        "catalog": {
            "environments": [{"key": "qa", "name": "QA", "identifier": "env-qa"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 60},
        "automated_jobs": [
            {
                "name": "nightly",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 45,
            }
        ],
    }


def test_build_generic_package_carries_identifiers_and_tool_type() -> None:
    package = build_generic_package(_config())

    assert package.tool_type == "jmeter"
    assert package.environments == [package.environments[0]]
    assert package.environments[0].value == "qa"
    assert package.environments[0].identifier == "env-qa"
    assert package.scenarios[0].identifier == "SC-1"

    job = package.automated_jobs[0]
    assert job.environment_ref == "qa"
    assert job.scenario_ref == "checkout_smoke"
    assert job.run_command == [
        "./scripts/run-jmeter.sh",
        "--environment",
        "qa",
        "--scenario",
        "checkout_smoke",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generic_model.py -v`
Expected: FAIL with `AttributeError` or `TypeError` (e.g. `InputOption.__init__() missing 1 required positional argument: 'identifier'`), since `build_generic_package` doesn't pass `identifier` yet and `GenericPipelinePackage` has no `tool_type`/`environments`/`scenarios` fields.

- [ ] **Step 3: Replace `generic_model.py` with this exact content**

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InputOption:
    value: str
    display_name: str
    identifier: str


@dataclass
class PipelineInput:
    key: str
    label: str
    kind: str
    options: list[InputOption]


@dataclass
class ManualPipelineSpec:
    name: str
    inputs: list[PipelineInput]
    timeout_minutes: int
    run_command: list[str]


@dataclass
class AutomatedJobSpec:
    name: str
    timeout_minutes: int
    environment_ref: str
    scenario_ref: str
    fixed_arguments: dict[str, str]
    run_command: list[str]


@dataclass
class GenericPipelinePackage:
    setup_id: str
    cicd_type: str
    tool_type: str
    manual_pipeline: ManualPipelineSpec | None = None
    automated_jobs: list[AutomatedJobSpec] = field(default_factory=list)
    environments: list[InputOption] = field(default_factory=list)
    scenarios: list[InputOption] = field(default_factory=list)
```

- [ ] **Step 4: Replace `context.py` with this exact content**

```python
from __future__ import annotations

from pipeline_generator.generator.generic_model import AutomatedJobSpec, GenericPipelinePackage, InputOption, ManualPipelineSpec, PipelineInput


def build_generic_package(config: dict) -> GenericPipelinePackage:
    setup = config["setup"]
    cicd_type = config["cicd"]["type"]
    tool_type = config["tool"]["type"]
    environments = [
        InputOption(value=item["key"], display_name=item["name"], identifier=item["identifier"])
        for item in config["catalog"]["environments"]
    ]
    scenarios = [
        InputOption(value=item["key"], display_name=item["name"], identifier=item["identifier"])
        for item in config["catalog"]["scenarios"]
    ]

    manual_pipeline = None
    if setup["generation_mode"] in {"manual_only", "both"} and config["manual_pipeline"]["enabled"]:
        manual_pipeline = ManualPipelineSpec(
            name=config["manual_pipeline"]["name"],
            inputs=[
                PipelineInput("environment", "Environment", "dropdown", environments),
                PipelineInput("scenario", "Scenario", "dropdown", scenarios),
            ],
            timeout_minutes=int(config["manual_pipeline"]["timeout_minutes"]),
            run_command=[
                f"./scripts/run-{tool_type}.sh",
                "--environment",
                "${environment}",
                "--scenario",
                "${scenario}",
            ],
        )

    automated_jobs = []
    if setup["generation_mode"] in {"automated_only", "both"}:
        for job in config["automated_jobs"]:
            if not job.get("enabled", True):
                continue
            automated_jobs.append(
                AutomatedJobSpec(
                    name=job["name"],
                    timeout_minutes=int(job.get("timeout_minutes", 240)),
                    environment_ref=job["environment_ref"],
                    scenario_ref=job["scenario_ref"],
                    fixed_arguments={
                        "job": job["name"],
                        "environment": job["environment_ref"],
                        "scenario": job["scenario_ref"],
                    },
                    run_command=[
                        f"./scripts/run-{tool_type}.sh",
                        "--environment",
                        job["environment_ref"],
                        "--scenario",
                        job["scenario_ref"],
                    ],
                )
            )

    return GenericPipelinePackage(
        setup_id=setup["id"],
        cicd_type=cicd_type,
        tool_type=tool_type,
        manual_pipeline=manual_pipeline,
        automated_jobs=automated_jobs,
        environments=environments,
        scenarios=scenarios,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_generic_model.py -v`
Expected: PASS

- [ ] **Step 6: Run the full existing suite — it will fail; that's expected here**

Run: `pytest -v`
Expected: Several failures in `tests/test_github_actions_renderer.py`, `tests/test_azure_devops_renderer.py`, `tests/test_jenkins_renderer.py` with `KeyError: 'identifier'` — their hand-written config fixtures don't include an `identifier` field yet. This is expected; Tasks 6-8 fix these fixtures as part of updating those renderers. Do not fix them now — commit this task as-is.

- [ ] **Step 7: Commit**

```bash
git add src/pipeline_generator/generator/generic_model.py src/pipeline_generator/generator/context.py tests/test_generic_model.py
git commit -m "feat: carry catalog identifiers and tool refs through the generic model"
```

---

### Task 2: Remove the run command, runtime/, and adapters/

**Files:**
- Modify: `src/pipeline_generator/cli.py:1-127` (full file)
- Delete: `src/pipeline_generator/runtime/` (entire directory: `__init__.py`, `artifacts.py`, `main.py`, `orchestrator.py`, `prechecks.py`, `summary.py`)
- Delete: `src/pipeline_generator/adapters/` (entire directory: `__init__.py`, `base.py`, `blazemeter.py`, `jmeter.py`, `loadrunner_professional.py`)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing (pure removal). `cli.py` keeps `build_parser`, `_blocks_action`, and `main` for `wizard`/`validate`/`generate` only.

- [ ] **Step 1: Delete the two directories**

```bash
rm -rf src/pipeline_generator/runtime src/pipeline_generator/adapters
```

- [ ] **Step 2: Replace `cli.py` with this exact content**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline_generator.config.loader import load_config
from pipeline_generator.config.validator import ValidationResult, validate_config
from pipeline_generator.generator.service import generate_assets
from pipeline_generator.wizard.flow import run_wizard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline-generator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    wizard_parser = subparsers.add_parser("wizard", help="Create or resume a setup YAML interactively.")
    wizard_parser.add_argument("--output", type=Path, required=True, help="Path to the YAML file to create or update.")
    wizard_parser.add_argument("--resume", action="store_true", help="Resume from an existing YAML draft if present.")

    validate_parser = subparsers.add_parser("validate", help="Validate a setup YAML file.")
    validate_parser.add_argument("--config", type=Path, required=True)
    validate_parser.add_argument("--strict", action="store_true", help="Treat warnings as errors.")

    generate_parser = subparsers.add_parser("generate", help="Generate CI/CD files and README from a setup YAML file.")
    generate_parser.add_argument("--config", type=Path, required=True)
    generate_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("generated"),
        help="Directory where generated setup packages are created.",
    )

    return parser


def _blocks_action(result: ValidationResult, config: dict, action: str) -> bool:
    print(result.to_console())
    if result.errors:
        return True
    if result.warnings and not config.get("incomplete", False):
        print(
            f"This setup is marked complete (incomplete: false) but has warnings above. "
            f"Fix them, or set incomplete: true in the config to {action} as a draft anyway."
        )
        return True
    return False


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "wizard":
        if args.output.exists() and not args.resume:
            print(
                f"{args.output} already exists. Pass --resume to continue editing it, "
                "or choose a different --output path to start a new setup."
            )
            return 1
        try:
            config = run_wizard(args.output, resume=args.resume)
        except (EOFError, KeyboardInterrupt):
            if args.output.exists():
                print(f"\nWizard cancelled. Progress up to the last completed step was saved to {args.output}.")
            else:
                print("\nWizard cancelled before any progress was saved.")
            return 130
        print(f"\nSaved setup draft to {args.output}")
        print(json.dumps({"setup_id": config["setup"]["id"], "incomplete": config["incomplete"]}, indent=2))
        print(f"\nNext step: pipeline-generator generate --config {args.output} --output-dir generated")
        return 0

    if args.command == "validate":
        config = load_config(args.config)
        result = validate_config(config)
        print(result.to_console())
        if result.errors or (args.strict and result.warnings):
            return 1
        return 0

    if args.command == "generate":
        config = load_config(args.config)
        result = validate_config(config)
        if _blocks_action(result, config, "generate"):
            return 1
        outputs = generate_assets(config, args.output_dir)
        for output in outputs:
            print(output)
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Verify the CLI still works and `run` is gone**

Run: `pip install -e . && pipeline-generator --help`
Expected: usage line shows only `{wizard,validate,generate}` — no `run`.

- [ ] **Step 4: Run the full suite**

Run: `pytest -v`
Expected: same pre-existing `KeyError: 'identifier'` failures from Task 1, no new failures (nothing currently imports `runtime`/`adapters` except the deleted `cli.py` code).

- [ ] **Step 5: Commit**

```bash
git add -A src/pipeline_generator/cli.py src/pipeline_generator/runtime src/pipeline_generator/adapters
git commit -m "feat: remove the run command and runtime/adapter execution layer"
```

---

### Task 3: Add renderers/scripts.py with resolver generation and a real JMeter script

**Files:**
- Create: `src/pipeline_generator/renderers/scripts.py`
- Test: `tests/test_tool_scripts.py` (new)

**Interfaces:**
- Consumes: `GenericPipelinePackage.tool_type/environments/scenarios` (Task 1), `renderers.quoting.shell_quote`, `config.placeholders.TODO_VALUE`.
- Produces: `render_tool_script(config: dict, package: GenericPipelinePackage, setup_dir: Path) -> list[str]` — Task 5 calls this from `generate_assets`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_scripts.py`:

```python
import subprocess
from pathlib import Path

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.scripts import render_tool_script


def _base_config(tool_type: str, connection: dict, checks: list[str] | None = None) -> dict:
    return {
        "setup": {"id": "script-test-setup", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "tool": {"type": tool_type, "connection": connection},
        "pre_run_checks": checks or [],
        "catalog": {
            "environments": [
                {"key": "qa", "name": "QA", "identifier": "env-qa"},
                {"key": "staging", "name": "Staging", "identifier": "env-stg"},
            ],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 30},
        "automated_jobs": [],
    }


def test_render_jmeter_script_with_precheck(tmp_path: Path) -> None:
    config = _base_config(
        "jmeter",
        {"test_plan_path": "performance/checkout.jmx", "jmeter_bin": ""},
        checks=["verify_scenario_exists"],
    )
    package = build_generic_package(config)

    outputs = render_tool_script(config, package, tmp_path)

    script_path = tmp_path / "scripts" / "run-jmeter.sh"
    assert outputs == [str(script_path)]
    assert script_path.exists()
    assert script_path.stat().st_mode & 0o111 == 0o111

    content = script_path.read_text(encoding="utf-8")
    assert "resolve_environment_identifier() {" in content
    assert "resolve_scenario_identifier() {" in content
    assert 'if [ ! -f "$test_plan_path" ]; then' in content
    assert "local test_plan_path='performance/checkout.jmx'" in content
    assert "local jmeter_bin='jmeter'" in content
    assert '"$jmeter_bin" -n -t "$test_plan_path"' in content
    assert 'if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then' in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_jmeter_script_without_precheck_flag(tmp_path: Path) -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": ""}, checks=[])
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)

    content = (tmp_path / "scripts" / "run-jmeter.sh").read_text(encoding="utf-8")
    assert "Test plan not found" not in content


def test_jmeter_resolver_uses_exact_match_not_glob(tmp_path: Path) -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": ""})
    config["catalog"]["environments"] = [
        {"key": "*", "name": "Wildcard", "identifier": "should-not-match"},
        {"key": "staging", "name": "Staging", "identifier": "env-stg"},
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}"; resolve_environment_identifier staging'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "env-stg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tool_scripts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline_generator.renderers.scripts'`

- [ ] **Step 3: Create `src/pipeline_generator/renderers/scripts.py` with this exact content**

```python
from __future__ import annotations

from pathlib import Path

from pipeline_generator.config.placeholders import TODO_VALUE
from pipeline_generator.generator.generic_model import GenericPipelinePackage, InputOption
from pipeline_generator.renderers.quoting import shell_quote


def render_tool_script(config: dict, package: GenericPipelinePackage, setup_dir: Path) -> list[str]:
    tool_type = config["tool"]["type"]
    scripts_dir = setup_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_path = scripts_dir / f"run-{tool_type}.sh"

    if tool_type == "jmeter":
        content = _render_jmeter_script(config, package)
    elif tool_type == "blazemeter":
        content = _render_blazemeter_script(config, package)
    elif tool_type == "loadrunner_professional":
        content = _render_loadrunner_script(config, package)
    else:  # pragma: no cover
        raise ValueError(f"Unsupported tool: {tool_type}")

    script_path.write_text(content, encoding="utf-8")
    script_path.chmod(0o755)
    return [str(script_path)]


def _render_resolver_function(function_name: str, kind: str, options: list[InputOption]) -> str:
    lines = [f"{function_name}() {{"]
    for option in options:
        lines.append(
            f'  if [ "$1" = {shell_quote(option.value)} ]; then echo {shell_quote(option.identifier)}; return; fi'
        )
    lines.append(f'  echo "Unknown {kind} key: $1" >&2')
    lines.append("  exit 1")
    lines.append("}")
    return "\n".join(lines)


def _render_resolvers(package: GenericPipelinePackage) -> str:
    environment_resolver = _render_resolver_function(
        "resolve_environment_identifier", "environment", package.environments
    )
    scenario_resolver = _render_resolver_function("resolve_scenario_identifier", "scenario", package.scenarios)
    return f"{environment_resolver}\n\n{scenario_resolver}"


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


def _render_jmeter_script(config: dict, package: GenericPipelinePackage) -> str:
    connection = config.get("tool", {}).get("connection", {})
    test_plan_path = connection.get("test_plan_path") or TODO_VALUE
    jmeter_bin = connection.get("jmeter_bin") or "jmeter"
    checks = config.get("pre_run_checks", [])

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


def _render_template_script(
    config: dict, package: GenericPipelinePackage, tool_label: str, connection_vars: dict[str, str]
) -> str:
    checks = config.get("pre_run_checks", [])
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tool_scripts.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/pipeline_generator/renderers/scripts.py tests/test_tool_scripts.py
git commit -m "feat: generate a real JMeter run script with exact-match key resolution"
```

---

### Task 4: Add BlazeMeter and LoadRunner Professional template scripts

**Files:**
- Test: `tests/test_tool_scripts.py` (append to existing file)

`_render_blazemeter_script`/`_render_loadrunner_script`/`_render_template_script` already exist from Task 3 (they were written together with the JMeter renderer since all three share `_render_resolvers`/`_render_arg_parsing`). This task only adds the tests proving the template scripts behave as designed — no production code changes.

**Interfaces:**
- Consumes: `render_tool_script` (Task 3), `_base_config` helper already in `tests/test_tool_scripts.py`.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tool_scripts.py`:

```python
def test_render_blazemeter_script_is_a_template(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
        checks=["verify_scenario_exists", "collect_results"],
    )
    package = build_generic_package(config)

    outputs = render_tool_script(config, package, tmp_path)

    script_path = tmp_path / "scripts" / "run-blazemeter.sh"
    assert outputs == [str(script_path)]
    assert script_path.stat().st_mode & 0o111 == 0o111

    content = script_path.read_text(encoding="utf-8")
    assert "local base_url='https://a.blazemeter.com'" in content
    assert "local workspace_id='12345'" in content
    assert "local project_id='67890'" in content
    assert "# TODO precheck: verify_scenario_exists" in content
    assert "# TODO precheck: collect_results" in content
    assert 'echo "ERROR: BlazeMeter execution is not implemented in this generated script yet." >&2' in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_loadrunner_professional_script_is_a_template(tmp_path: Path) -> None:
    config = _base_config(
        "loadrunner_professional",
        {
            "controller_host": "lr.acme.local",
            "controller_results_path": "C:\\Results",
            "domain": "DEFAULT",
            "project": "ACME",
        },
    )
    package = build_generic_package(config)

    outputs = render_tool_script(config, package, tmp_path)

    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"
    assert outputs == [str(script_path)]

    content = script_path.read_text(encoding="utf-8")
    assert "local controller_host='lr.acme.local'" in content
    assert "local controller_results_path='C:\\Results'" in content
    assert "local domain='DEFAULT'" in content
    assert "local project='ACME'" in content
    assert (
        'echo "ERROR: LoadRunner Professional execution is not implemented in this generated script yet." >&2'
        in content
    )

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_tool_scripts.py -v`
Expected: PASS (5 tests total in this file)

- [ ] **Step 3: Commit**

```bash
git add tests/test_tool_scripts.py
git commit -m "test: cover the BlazeMeter and LoadRunner Professional template scripts"
```

---

### Task 5: Wire render_tool_script into generate_assets

**Files:**
- Modify: `src/pipeline_generator/generator/service.py:1-40` (full file)
- Modify: `tests/test_example_configs.py:20-23`

**Interfaces:**
- Consumes: `render_tool_script` (Task 3).
- Produces: `generate_assets`'s returned list now always includes the script path.

- [ ] **Step 1: Write the failing assertion**

In `tests/test_example_configs.py`, change:

```python
    outputs = generate_assets(config, tmp_path)
    assert outputs
    for output in outputs:
        assert Path(output).exists()
```

to:

```python
    outputs = generate_assets(config, tmp_path)
    assert outputs
    for output in outputs:
        assert Path(output).exists()
    assert any("scripts" in Path(output).parts for output in outputs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_example_configs.py -v`
Expected: FAIL (all 9 parametrized cases) — `assert any(...)` is `False`, no script was generated yet.

- [ ] **Step 3: Modify `generator/service.py`**

Replace the full file with:

```python
from __future__ import annotations

from pathlib import Path

from pipeline_generator.config.loader import save_config
from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.azure_devops import render_azure_devops
from pipeline_generator.renderers.github_actions import render_github_actions
from pipeline_generator.renderers.jenkins import render_jenkins
from pipeline_generator.renderers.readme import render_setup_readme
from pipeline_generator.renderers.scripts import render_tool_script
from pipeline_generator.text_utils import slugify


def generate_assets(config: dict, output_dir: Path) -> list[str]:
    package = build_generic_package(config)
    # setup.id comes straight from the config file, which this tool's own
    # customer_repo/central_repo model expects to be editable by less-trusted
    # collaborators -- slugify it so a value like "../../etc" or an absolute
    # path can't write outside output_dir.
    setup_dir = output_dir / slugify(package.setup_id)
    setup_dir.mkdir(parents=True, exist_ok=True)

    save_config(setup_dir / "customer.yaml", config)
    outputs = [str(setup_dir / "customer.yaml")]

    outputs.extend(render_tool_script(config, package, setup_dir))

    if package.cicd_type == "github_actions":
        outputs.extend(render_github_actions(config, package, setup_dir))
    elif package.cicd_type == "azure_devops":
        outputs.extend(render_azure_devops(config, package, setup_dir))
    elif package.cicd_type == "jenkins":
        outputs.extend(render_jenkins(config, package, setup_dir))
    else:  # pragma: no cover
        raise ValueError(f"Unsupported renderer: {package.cicd_type}")

    readme_path = setup_dir / "README.md"
    readme_path.write_text(render_setup_readme(config, package), encoding="utf-8")
    outputs.append(str(readme_path))

    return outputs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_example_configs.py -v`
Expected: PASS (9 cases) — note `tests/test_generate_assets_path_safety.py` should also still pass unmodified, since it already asserts generically over every path in `outputs`.

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: only the Task 1-carried-over `KeyError: 'identifier'` failures remain, in the three CI/CD renderer test files (fixed in Tasks 6-8).

- [ ] **Step 6: Commit**

```bash
git add src/pipeline_generator/generator/service.py tests/test_example_configs.py
git commit -m "feat: generate a tool script alongside every setup's CI/CD files"
```

---

### Task 6: Update the GitHub Actions renderer to call the generated script

**Files:**
- Modify: `src/pipeline_generator/renderers/github_actions.py` (full file, 122 lines)
- Modify: `tests/test_github_actions_renderer.py` (full file, 118 lines)

**Interfaces:**
- Consumes: `package.tool_type`, `job.environment_ref`, `job.scenario_ref` (Task 1).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Replace `tests/test_github_actions_renderer.py` with this exact content (tests will fail until Step 2)**

```python
import re
from pathlib import Path

import yaml

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.github_actions import render_github_actions
from pipeline_generator.renderers.quoting import shell_quote


def _config() -> dict:
    return {
        "setup": {"id": "gha-test-setup", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "jmeter_bin": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": "qa", "name": "QA", "identifier": "env-qa"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 120},
        "automated_jobs": [
            {
                "name": "post-deploy-smoke",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 60,
            }
        ],
    }


def test_render_github_actions_writes_valid_workflows(tmp_path: Path) -> None:
    config = _config()
    package = build_generic_package(config)

    outputs = render_github_actions(config, package, tmp_path)

    manual_path = tmp_path / ".github" / "workflows" / "performance-manual.yml"
    automated_path = tmp_path / ".github" / "workflows" / "performance-automated-post-deploy-smoke.yml"
    assert str(manual_path) in outputs
    assert str(automated_path) in outputs

    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)
    assert manual_doc["name"] == "Performance Manual Run"
    assert manual_doc["jobs"]["run-performance-test"]["timeout-minutes"] == 120
    assert '"qa"' in manual_text
    assert '"checkout_smoke"' in manual_text
    # The build-triggerer-controlled input must be delivered via env:, never
    # spliced directly into the run: shell text (workflow_dispatch's `choice`
    # restriction is only enforced by GitHub's UI, not its dispatch API).
    step = manual_doc["jobs"]["run-performance-test"]["steps"][1]
    assert step["env"] == {
        "ENVIRONMENT": "${{ github.event.inputs.environment }}",
        "SCENARIO": "${{ github.event.inputs.scenario }}",
    }
    assert "./scripts/run-jmeter.sh" in manual_text
    assert '--environment "$ENVIRONMENT"' in manual_text
    assert '--scenario "$SCENARIO"' in manual_text
    assert "github.event.inputs" not in step["run"]
    assert "pipeline-generator" not in manual_text

    automated_text = automated_path.read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)
    assert automated_doc["jobs"]["post-deploy-smoke"]["timeout-minutes"] == 60
    assert "./scripts/run-jmeter.sh" in automated_text
    assert "--environment qa" in automated_text
    assert "--scenario checkout_smoke" in automated_text
    assert "pipeline-generator" not in automated_text


def test_render_github_actions_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = 'qa" evil: true'
    nasty_job_name = 'weird "job"; rm -rf / : ../../etc'
    nasty_pipeline_name = 'My "Perf" Pipeline: v2'
    config = {
        "setup": {"id": "gha-adversarial", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "jmeter_bin": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": nasty_env_value, "name": "QA", "identifier": "env-nasty"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": nasty_pipeline_name, "timeout_minutes": 30},
        "automated_jobs": [
            {
                "name": nasty_job_name,
                "enabled": True,
                "environment_ref": nasty_env_value,
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 15,
            }
        ],
    }
    package = build_generic_package(config)

    outputs = render_github_actions(config, package, tmp_path)

    # A hostile job name must never escape the intended output directory or
    # produce filesystem-unsafe filenames.
    for output in outputs:
        filename = Path(output).name
        assert "/" not in filename
        assert ".." not in filename
        assert " " not in filename

    manual_path = tmp_path / ".github" / "workflows" / "performance-manual.yml"
    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)  # raises if the escaping broke YAML syntax
    assert manual_doc["name"] == nasty_pipeline_name
    # PyYAML's default resolver reads the bare "on:" key as boolean True.
    assert nasty_env_value in manual_doc[True]["workflow_dispatch"]["inputs"]["environment"]["options"]

    workflows_dir = tmp_path / ".github" / "workflows"
    automated_files = [p for p in workflows_dir.iterdir() if p.name.startswith("performance-automated-")]
    assert len(automated_files) == 1
    automated_text = automated_files[0].read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)  # raises if the escaping broke YAML syntax

    assert automated_doc["name"] == f"Performance Automated Job - {nasty_job_name}"
    job_id = next(iter(automated_doc["jobs"]))
    assert re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", job_id)
    assert shell_quote(nasty_env_value) in automated_text
```

- [ ] **Step 2: Replace `src/pipeline_generator/renderers/github_actions.py` with this exact content**

```python
from __future__ import annotations

import re
from pathlib import Path

from pipeline_generator.generator.generic_model import GenericPipelinePackage
from pipeline_generator.renderers.quoting import safe_filename_component, shell_quote, yaml_dquote


def render_github_actions(config: dict, package: GenericPipelinePackage, setup_dir: Path) -> list[str]:
    workflow_dir = setup_dir / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []

    if package.manual_pipeline:
        manual_path = workflow_dir / "performance-manual.yml"
        manual_path.write_text(_render_manual_workflow(package), encoding="utf-8")
        outputs.append(str(manual_path))

    if package.automated_jobs:
        for job in package.automated_jobs:
            automated_path = workflow_dir / f"performance-automated-{safe_filename_component(job.name)}.yml"
            automated_path.write_text(_render_automated_workflow(job, package.tool_type), encoding="utf-8")
            outputs.append(str(automated_path))

    return outputs


def _safe_job_id(value: str) -> str:
    """Sanitize a job name into a valid GitHub Actions job id.

    Job ids must start with a letter or underscore and contain only
    alphanumerics, `-`, or `_` (https://docs.github.com/actions).
    """
    text = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    if not text or not re.match(r"[A-Za-z_]", text[0]):
        text = f"job_{text}"
    return text


def _render_manual_workflow(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_options = ", ".join(yaml_dquote(item.value) for item in package.manual_pipeline.inputs[0].options)
    scenario_options = ", ".join(yaml_dquote(item.value) for item in package.manual_pipeline.inputs[1].options)
    timeout = package.manual_pipeline.timeout_minutes
    return f"""name: {yaml_dquote(package.manual_pipeline.name)}

on:
  workflow_dispatch:
    inputs:
      environment:
        description: Select environment
        required: true
        type: choice
        options: [{environment_options}]
      scenario:
        description: Select scenario
        required: true
        type: choice
        options: [{scenario_options}]

jobs:
  run-performance-test:
    runs-on: ubuntu-latest
    timeout-minutes: {timeout}
    steps:
      - uses: actions/checkout@v4
      - name: Run performance wrapper
        env:
          ENVIRONMENT: ${{{{ github.event.inputs.environment }}}}
          SCENARIO: ${{{{ github.event.inputs.scenario }}}}
        run: >
          ./scripts/run-{package.tool_type}.sh
          --environment "$ENVIRONMENT"
          --scenario "$SCENARIO"
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: performance-results
          path: run-output/
"""


def _render_automated_workflow(job, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    return f"""name: {yaml_dquote(f"Performance Automated Job - {job.name}")}

on:
  workflow_call:

jobs:
  {job_id}:
    runs-on: ubuntu-latest
    timeout-minutes: {job.timeout_minutes}
    steps:
      - uses: actions/checkout@v4
      - name: Run performance wrapper
        run: >
          ./scripts/run-{tool_type}.sh
          --environment {shell_quote(job.environment_ref)}
          --scenario {shell_quote(job.scenario_ref)}
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: {yaml_dquote(f"performance-results-{job.name}")}
          path: run-output/
"""
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/test_github_actions_renderer.py -v`
Expected: PASS (2 tests)

- [ ] **Step 4: Commit**

```bash
git add src/pipeline_generator/renderers/github_actions.py tests/test_github_actions_renderer.py
git commit -m "feat: call the generated tool script from GitHub Actions workflows"
```

---

### Task 7: Update the Azure DevOps renderer to call the generated script

**Files:**
- Modify: `src/pipeline_generator/renderers/azure_devops.py` (full file, 119 lines)
- Modify: `tests/test_azure_devops_renderer.py` (full file, 113 lines)

**Interfaces:**
- Consumes: `package.tool_type`, `job.environment_ref`, `job.scenario_ref` (Task 1).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Replace `tests/test_azure_devops_renderer.py` with this exact content**

```python
import re
from pathlib import Path

import yaml

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.azure_devops import render_azure_devops
from pipeline_generator.renderers.quoting import shell_quote


def _config() -> dict:
    return {
        "setup": {"id": "azure-test-setup", "generation_mode": "both"},
        "cicd": {"type": "azure_devops"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "jmeter_bin": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": "qa", "name": "QA", "identifier": "env-qa"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 120},
        "automated_jobs": [
            {
                "name": "post-deploy-smoke",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 60,
            }
        ],
    }


def test_render_azure_devops_writes_valid_pipelines(tmp_path: Path) -> None:
    config = _config()
    package = build_generic_package(config)

    outputs = render_azure_devops(config, package, tmp_path)

    manual_path = tmp_path / "azure" / "performance-manual.yml"
    automated_path = tmp_path / "azure" / "performance-automated-post-deploy-smoke.yml"
    assert str(manual_path) in outputs
    assert str(automated_path) in outputs

    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)
    assert manual_doc["jobs"][0]["timeoutInMinutes"] == 120
    assert manual_doc["parameters"][0]["name"] == "environment"
    assert "qa" in manual_text
    # The parameter value must be delivered via env:, never spliced directly
    # into the script: text.
    run_step = manual_doc["jobs"][0]["steps"][1]
    assert run_step["env"] == {
        "ENVIRONMENT": "${{ parameters.environment }}",
        "SCENARIO": "${{ parameters.scenario }}",
    }
    assert "./scripts/run-jmeter.sh" in manual_text
    assert '--environment "$ENVIRONMENT"' in manual_text
    assert '--scenario "$SCENARIO"' in manual_text
    assert "parameters.environment" not in run_step["script"]
    assert "pipeline-generator" not in manual_text

    automated_text = automated_path.read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)
    assert automated_doc["jobs"][0]["timeoutInMinutes"] == 60
    # job identifiers get hyphens sanitized to underscores.
    assert automated_doc["jobs"][0]["job"] == "post_deploy_smoke"
    assert "./scripts/run-jmeter.sh" in automated_text
    assert "--environment qa" in automated_text
    assert "--scenario checkout_smoke" in automated_text
    assert "pipeline-generator" not in automated_text


def test_render_azure_devops_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = 'qa" evil: true'
    nasty_job_name = 'weird "job"; rm -rf / : ../../etc'
    config = {
        "setup": {"id": "azure-adversarial", "generation_mode": "both"},
        "cicd": {"type": "azure_devops"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "jmeter_bin": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": nasty_env_value, "name": "QA", "identifier": "env-nasty"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 30},
        "automated_jobs": [
            {
                "name": nasty_job_name,
                "enabled": True,
                "environment_ref": nasty_env_value,
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 15,
            }
        ],
    }
    package = build_generic_package(config)

    outputs = render_azure_devops(config, package, tmp_path)

    for output in outputs:
        filename = Path(output).name
        assert "/" not in filename
        assert ".." not in filename
        assert " " not in filename

    manual_path = tmp_path / "azure" / "performance-manual.yml"
    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)  # raises if the escaping broke YAML syntax
    environment_param = next(p for p in manual_doc["parameters"] if p["name"] == "environment")
    assert nasty_env_value in environment_param["values"]

    azure_dir = tmp_path / "azure"
    automated_files = [p for p in azure_dir.iterdir() if p.name.startswith("performance-automated-")]
    assert len(automated_files) == 1
    automated_text = automated_files[0].read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)  # raises if the escaping broke YAML syntax

    job_id = automated_doc["jobs"][0]["job"]
    assert re.match(r"^[A-Za-z0-9_]+$", job_id)
    assert not job_id[0].isdigit()
    assert shell_quote(nasty_env_value) in automated_text
```

- [ ] **Step 2: Replace `src/pipeline_generator/renderers/azure_devops.py` with this exact content**

```python
from __future__ import annotations

import re
from pathlib import Path

from pipeline_generator.generator.generic_model import GenericPipelinePackage
from pipeline_generator.renderers.quoting import safe_filename_component, shell_quote, yaml_dquote


def render_azure_devops(config: dict, package: GenericPipelinePackage, setup_dir: Path) -> list[str]:
    azure_dir = setup_dir / "azure"
    azure_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []

    if package.manual_pipeline:
        manual_path = azure_dir / "performance-manual.yml"
        manual_path.write_text(_render_manual_pipeline(package), encoding="utf-8")
        outputs.append(str(manual_path))

    if package.automated_jobs:
        for job in package.automated_jobs:
            automated_path = azure_dir / f"performance-automated-{safe_filename_component(job.name)}.yml"
            automated_path.write_text(_render_automated_job(job, package.tool_type), encoding="utf-8")
            outputs.append(str(automated_path))

    return outputs


def _safe_job_id(value: str) -> str:
    """Sanitize a job name into a valid Azure Pipelines job id (`[A-Za-z0-9_]`, no leading digit)."""
    text = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not text or text[0].isdigit():
        text = f"job_{text}"
    return text


def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_options = package.manual_pipeline.inputs[0].options
    scenario_options = package.manual_pipeline.inputs[1].options
    environment_values = "\n".join(f"      - {yaml_dquote(item.value)}" for item in environment_options)
    scenario_values = "\n".join(f"      - {yaml_dquote(item.value)}" for item in scenario_options)
    environment_default = yaml_dquote(environment_options[0].value if environment_options else "TODO")
    scenario_default = yaml_dquote(scenario_options[0].value if scenario_options else "TODO")
    return f"""trigger: none
pr: none

parameters:
  - name: environment
    displayName: Environment
    type: string
    default: {environment_default}
    values:
{environment_values}
  - name: scenario
    displayName: Scenario
    type: string
    default: {scenario_default}
    values:
{scenario_values}

jobs:
  - job: run_performance_test
    timeoutInMinutes: {package.manual_pipeline.timeout_minutes}
    pool:
      vmImage: ubuntu-latest
    steps:
      - checkout: self
      - script: >
          ./scripts/run-{package.tool_type}.sh
          --environment "$ENVIRONMENT"
          --scenario "$SCENARIO"
        env:
          ENVIRONMENT: ${{{{ parameters.environment }}}}
          SCENARIO: ${{{{ parameters.scenario }}}}
        displayName: Run performance wrapper
      - task: PublishPipelineArtifact@1
        condition: always()
        inputs:
          targetPath: run-output
          artifact: performance-results
"""


def _render_automated_job(job, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    return f"""parameters: []

jobs:
  - job: {job_id}
    timeoutInMinutes: {job.timeout_minutes}
    pool:
      vmImage: ubuntu-latest
    steps:
      - checkout: self
      - script: >
          ./scripts/run-{tool_type}.sh
          --environment {shell_quote(job.environment_ref)}
          --scenario {shell_quote(job.scenario_ref)}
        displayName: Run performance wrapper
      - task: PublishPipelineArtifact@1
        condition: always()
        inputs:
          targetPath: run-output
          artifact: {yaml_dquote(f"performance-results-{job.name}")}
"""
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/test_azure_devops_renderer.py -v`
Expected: PASS (2 tests)

- [ ] **Step 4: Commit**

```bash
git add src/pipeline_generator/renderers/azure_devops.py tests/test_azure_devops_renderer.py
git commit -m "feat: call the generated tool script from Azure DevOps pipelines"
```

---

### Task 8: Update the Jenkins renderer to call the generated script

**Files:**
- Modify: `src/pipeline_generator/renderers/jenkins.py` (full file, 110 lines)
- Modify: `tests/test_jenkins_renderer.py` (full file, 100 lines)

**Interfaces:**
- Consumes: `package.tool_type`, `job.environment_ref`, `job.scenario_ref` (Task 1).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Replace `tests/test_jenkins_renderer.py` with this exact content**

```python
from pathlib import Path

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.jenkins import render_jenkins
from pipeline_generator.renderers.quoting import groovy_squote


def _config() -> dict:
    return {
        "setup": {"id": "jenkins-test-setup", "generation_mode": "both"},
        "cicd": {"type": "jenkins"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "jmeter_bin": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": "qa", "name": "QA", "identifier": "env-qa"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 120},
        "automated_jobs": [
            {
                "name": "post-deploy-smoke",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 60,
            }
        ],
    }


def test_render_jenkins_writes_manual_and_automated_jenkinsfiles(tmp_path: Path) -> None:
    config = _config()
    package = build_generic_package(config)

    outputs = render_jenkins(config, package, tmp_path)

    manual_path = tmp_path / "jenkins" / "Jenkinsfile.performance-manual"
    automated_path = tmp_path / "jenkins" / "Jenkinsfile.performance-automated-post-deploy-smoke"
    assert str(manual_path) in outputs
    assert str(automated_path) in outputs

    manual_content = manual_path.read_text(encoding="utf-8")
    assert "./scripts/run-jmeter.sh" in manual_content
    assert '--environment "$ENVIRONMENT" --scenario "$SCENARIO"' in manual_content
    assert "'qa'," in manual_content
    assert "'checkout_smoke'," in manual_content
    assert "timeout(time: 120, unit: 'MINUTES')" in manual_content
    assert "pipeline-generator" not in manual_content

    automated_content = automated_path.read_text(encoding="utf-8")
    assert "ENVIRONMENT = 'qa'" in automated_content
    assert "SCENARIO = 'checkout_smoke'" in automated_content
    assert './scripts/run-jmeter.sh --environment "$ENVIRONMENT" --scenario "$SCENARIO"' in automated_content
    assert "timeout(time: 60, unit: 'MINUTES')" in automated_content
    assert "pipeline-generator" not in automated_content


def test_render_jenkins_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = "qa'; rm -rf / #"
    nasty_job_name = "weird'job\"; rm -rf / \\ ../../etc"
    config = {
        "setup": {"id": "jenkins-adversarial", "generation_mode": "both"},
        "cicd": {"type": "jenkins"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "jmeter_bin": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": nasty_env_value, "name": "QA", "identifier": "env-nasty"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 30},
        "automated_jobs": [
            {
                "name": nasty_job_name,
                "enabled": True,
                "environment_ref": nasty_env_value,
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 15,
            }
        ],
    }
    package = build_generic_package(config)

    outputs = render_jenkins(config, package, tmp_path)

    # A hostile job name must never escape the intended output directory.
    for output in outputs:
        filename = Path(output).name
        assert "/" not in filename
        assert ".." not in filename
        assert " " not in filename

    manual_path = tmp_path / "jenkins" / "Jenkinsfile.performance-manual"
    manual_content = manual_path.read_text(encoding="utf-8")
    # The hostile environment value must appear only inside a properly
    # escaped single-quoted Groovy string, never able to close the `choice`
    # literal's quote early.
    assert groovy_squote(nasty_env_value) in manual_content
    assert '--environment "$ENVIRONMENT" --scenario "$SCENARIO"' in manual_content

    jenkins_dir = tmp_path / "jenkins"
    automated_files = [p for p in jenkins_dir.iterdir() if p.name.startswith("Jenkinsfile.performance-automated-")]
    assert len(automated_files) == 1
    automated_content = automated_files[0].read_text(encoding="utf-8")
    # environment_ref (the adversarial value here) must be delivered via the
    # environment{} block, Groovy-escaped, never spliced directly into the
    # sh command text.
    assert f"ENVIRONMENT = {groovy_squote(nasty_env_value)}" in automated_content
    assert './scripts/run-jmeter.sh --environment "$ENVIRONMENT" --scenario "$SCENARIO"' in automated_content
```

- [ ] **Step 2: Replace `src/pipeline_generator/renderers/jenkins.py` with this exact content**

```python
from __future__ import annotations

from pathlib import Path

from pipeline_generator.generator.generic_model import GenericPipelinePackage
from pipeline_generator.renderers.quoting import groovy_squote, safe_filename_component


def render_jenkins(config: dict, package: GenericPipelinePackage, setup_dir: Path) -> list[str]:
    jenkins_dir = setup_dir / "jenkins"
    jenkins_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []

    if package.manual_pipeline:
        manual_path = jenkins_dir / "Jenkinsfile.performance-manual"
        manual_path.write_text(_render_manual_pipeline(package), encoding="utf-8")
        outputs.append(str(manual_path))

    if package.automated_jobs:
        for job in package.automated_jobs:
            automated_path = jenkins_dir / f"Jenkinsfile.performance-automated-{safe_filename_component(job.name)}"
            automated_path.write_text(_render_automated_job(job, package.tool_type), encoding="utf-8")
            outputs.append(str(automated_path))

    return outputs


def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_choices = "\n".join(
        f"                {groovy_squote(item.value)}," for item in package.manual_pipeline.inputs[0].options
    )
    scenario_choices = "\n".join(
        f"                {groovy_squote(item.value)}," for item in package.manual_pipeline.inputs[1].options
    )
    timeout = package.manual_pipeline.timeout_minutes
    return f"""pipeline {{
    agent any
    parameters {{
        choice(
            name: 'ENVIRONMENT',
            choices: [
{environment_choices}
            ],
            description: 'Select environment'
        )
        choice(
            name: 'SCENARIO',
            choices: [
{scenario_choices}
            ],
            description: 'Select scenario'
        )
    }}
    options {{
        timeout(time: {timeout}, unit: 'MINUTES')
    }}
    stages {{
        stage('Run performance wrapper') {{
            steps {{
                // Build parameters are exposed as shell environment variables by
                // Jenkins; referencing them here (rather than Groovy-interpolating
                // ${{params.X}} into the command text) avoids splicing a
                // build-triggerer-controlled value directly into the shell script.
                sh './scripts/run-{package.tool_type}.sh --environment "$ENVIRONMENT" --scenario "$SCENARIO"'
            }}
        }}
    }}
    post {{
        always {{
            archiveArtifacts artifacts: 'run-output/**', allowEmptyArchive: true
        }}
    }}
}}
"""


def _render_automated_job(job, tool_type: str) -> str:
    return f"""pipeline {{
    agent any
    environment {{
        ENVIRONMENT = {groovy_squote(job.environment_ref)}
        SCENARIO = {groovy_squote(job.scenario_ref)}
    }}
    options {{
        timeout(time: {job.timeout_minutes}, unit: 'MINUTES')
    }}
    stages {{
        stage('Run performance wrapper') {{
            steps {{
                sh './scripts/run-{tool_type}.sh --environment "$ENVIRONMENT" --scenario "$SCENARIO"'
            }}
        }}
    }}
    post {{
        always {{
            archiveArtifacts artifacts: 'run-output/**', allowEmptyArchive: true
        }}
    }}
}}
"""
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/test_jenkins_renderer.py -v`
Expected: PASS (2 tests)

- [ ] **Step 4: Commit**

```bash
git add src/pipeline_generator/renderers/jenkins.py tests/test_jenkins_renderer.py
git commit -m "feat: call the generated tool script from Jenkinsfiles"
```

---

### Task 9: Full regression verification

**Files:** none (verification only)

**Interfaces:** none.

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass (existing suite plus everything added in Tasks 1-8), zero failures.

- [ ] **Step 2: Confirm `run` is gone from the CLI**

Run: `pipeline-generator --help`
Expected: only `wizard`, `validate`, `generate` listed.

- [ ] **Step 3: Generate every example config and inspect the output**

Run:
```bash
rm -rf /tmp/generator-only-check
for cfg in examples/*/customer.yaml; do
  pipeline-generator generate --config "$cfg" --output-dir /tmp/generator-only-check
done
find /tmp/generator-only-check -name "run-*.sh"
```
Expected: one `scripts/run-<tool>.sh` per generated setup (9 total), each executable (`ls -l` shows `x` bits set).

- [ ] **Step 4: Confirm no generated output references the removed command**

Run: `grep -rl "pipeline-generator run\|pipeline-generator\." /tmp/generator-only-check || echo "none found"`
Expected: `none found`.

- [ ] **Step 5: Syntax-check every generated JMeter script**

Run:
```bash
find /tmp/generator-only-check -name "run-jmeter.sh" -exec bash -n {} \; && echo "all valid"
```
Expected: `all valid`, no syntax errors printed.

- [ ] **Step 6: Clean up**

Run: `rm -rf /tmp/generator-only-check`

No commit for this task — it's verification only, with no file changes.

---

### Task 10: Update documentation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/pipeline-generator-user-guide.md`
- Modify: `docs/current-state-and-readiness-plan.md`

**Interfaces:** none — documentation only.

This task has no fixed line numbers to target precisely, since the exact current line numbers may have drifted from earlier edits in this session; instead, grep for the patterns below in each file and replace every match's surrounding context.

- [ ] **Step 1: Update `README.md`**

Search for and update every reference to: `pipeline-generator run`, `--dry-run`, "Provides a runtime wrapper skeleton for", and the CLI Commands section's `run` entry. Replace the framing with: `pipeline-generator` has three commands (`wizard`, `validate`, `generate`); it never executes a performance test itself; `generate` writes a `scripts/run-<tool>.sh` per setup that the generated CI/CD pipeline calls directly (real for JMeter, a template with TODOs for BlazeMeter/LoadRunner Professional). Update the Quick Start section to remove the `pipeline-generator run --dry-run` examples. Update the Output Structure section to show a `scripts/run-<tool>.sh` file alongside the CI/CD files.

- [ ] **Step 2: Update `CLAUDE.md`**

Remove the `runtime/` and `adapters/` bullets from the Architecture section (they no longer exist). Add a `renderers/scripts.py` bullet describing: writes `scripts/run-<tool>.sh`, real for JMeter, a TODO template for BlazeMeter/LoadRunner Professional; every catalog key is resolved to its identifier inside the generated script via exact-match shell comparisons (never `case`, to avoid glob-pattern matching against config-controlled catalog keys). Remove the `run` subcommand from the Commands section's CLI examples. Update the paragraph describing `generate`/`run`'s shared warning-blocking behavior (`_blocks_action`) to reflect that only `generate` exists now.

- [ ] **Step 3: Update `docs/pipeline-generator-user-guide.md`**

Rewrite the `run` bullet in the "What This Tool Is For" mental model (Section 1) and the entire "Running Performance Tests" section (Section 8) to describe the generated script instead of a `run` command. Remove `--dry-run` from the Quick Start and CLI Commands sections. Update Section 9 ("CI/CD Platforms — What Gets Generated") to mention the `scripts/run-<tool>.sh` file each platform's step calls. Update Section 10 ("Performance Testing Tools") to describe the script-based real/template split instead of the Python-adapter stub framing. Update the Troubleshooting section's `run`-related entries (e.g. "adapter scaffolded but not implemented yet") to describe the generated script's own `ERROR: ... is not implemented in this generated script yet.` message instead.

- [ ] **Step 4: Update `docs/current-state-and-readiness-plan.md`**

Update the "Implemented"/"Not implemented yet" lists, the "CLI Behavior" section's `Run` subsection, the "Runtime Flow" section, and the "Adapter Implementations Are Stubs" gap section to describe the script-generation model instead of the Python runtime/adapter model. Mark the JMeter script as real/working (not a stub) and BlazeMeter/LoadRunner Professional scripts as templates needing their API/controller call filled in.

- [ ] **Step 5: Verify no stale references remain**

Run: `grep -rn "pipeline-generator run\|adapters/\|runtime/\|NotImplementedError" README.md CLAUDE.md docs/pipeline-generator-user-guide.md docs/current-state-and-readiness-plan.md`
Expected: no matches (or only matches inside code blocks that are intentionally historical/removed-feature callouts — review each hit by hand).

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md docs/pipeline-generator-user-guide.md docs/current-state-and-readiness-plan.md
git commit -m "docs: describe generated tool scripts instead of the removed run command"
```
