from __future__ import annotations

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
    assert "local test_plan_path=performance/checkout.jmx" in content
    assert "local jmeter_bin=jmeter" in content
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
    # shlex.quote leaves values with no shell-special characters unquoted --
    # none of these three values contain any, so no quotes appear.
    assert "local base_url=https://a.blazemeter.com" in content
    assert "local workspace_id=12345" in content
    assert "local project_id=67890" in content
    assert "# TODO precheck: verify_scenario_exists" in content
    assert "# TODO precheck: collect_results" in content
    assert 'echo "ERROR: BlazeMeter execution is not implemented in this generated script yet." >&2' in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_template_script_rejects_pre_run_check_shell_injection(tmp_path: Path) -> None:
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
    # shlex.quote only adds quotes when a value contains a shell-special
    # character. "lr.acme.local", "DEFAULT", and "ACME" don't, so they come
    # out bare; "C:\Results" contains a backslash, so it comes out quoted.
    assert "local controller_host=lr.acme.local" in content
    assert "local controller_results_path='C:\\Results'" in content
    assert "local domain=DEFAULT" in content
    assert "local project=ACME" in content
    assert (
        'echo "ERROR: LoadRunner Professional execution is not implemented in this generated script yet." >&2'
        in content
    )

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr
