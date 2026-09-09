from __future__ import annotations

import shlex
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


def test_resolver_handles_adversarial_catalog_keys(tmp_path: Path) -> None:
    marker = tmp_path / "should-not-exist"
    adversarial_keys = [
        "qa's staging",
        "east us",
        f"$(touch {marker})",
        f"`touch {marker}`",
    ]
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": ""})
    config["catalog"]["environments"] = [
        {"key": key, "name": f"Env {i}", "identifier": f"env-{i}"} for i, key in enumerate(adversarial_keys)
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr

    for i, key in enumerate(adversarial_keys):
        # shlex.quote here only protects the *test's* shell -c string; it has
        # nothing to do with the production shell_quote already baked into
        # the sourced script. This exercises exactly what the generated
        # `[ "$1" = '...' ]` comparison does with a hostile key -- it must
        # match literally rather than executing $(...) or backticks.
        command = f"source {shlex.quote(str(script_path))}; resolve_environment_identifier {shlex.quote(key)}"
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"env-{i}"

    assert not marker.exists()


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
    assert 'local results_dir="run-output/${environment_slug}_${scenario_slug}"' in content
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


def test_render_loadrunner_script_sanitizes_results_dir_from_hostile_catalog_key(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    config["catalog"]["environments"] = [{"key": "../../pwn", "name": "Hostile", "identifier": "Hostile"}]
    config["catalog"]["scenarios"] = [
        {"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "C:\\Scenarios\\checkout_smoke.lrs"}
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "resolve_environment_slug() {" in content
    assert "resolve_scenario_slug() {" in content

    # The slug resolver must map the hostile key to a sanitized value at
    # generation time (safe_filename_component == slugify), not pass it
    # through raw -- this is what closes the run-output/../../pwn escape
    # the final review demonstrated.
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


def test_render_loadrunner_script_todo_comments_for_unhandled_checks(tmp_path: Path) -> None:
    config = _base_config(
        "loadrunner_professional",
        {"wlrun_path": "wlrun"},
        checks=["verify_controller_access", "verify_scenario_exists", "verify_load_generators_connected", "collect_results"],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"
    content = script_path.read_text(encoding="utf-8")

    # The two implemented checks get real guards, not TODO comments.
    assert "# TODO precheck: verify_controller_access" not in content
    assert "# TODO precheck: verify_scenario_exists" not in content
    # The two unimplemented checks get TODO comments instead of silently
    # vanishing.
    assert "# TODO precheck: verify_load_generators_connected" in content
    assert "# TODO precheck: collect_results" in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr
