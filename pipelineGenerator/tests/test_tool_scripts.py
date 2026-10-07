from __future__ import annotations

import json
import os
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
                {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]},
                {"key": "staging", "identifier": "env-stg", "scenarios": []},
            ],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 30},
        "automated_jobs": [],
        "load_profile": {
            "test_type": "load",
            "users": 10,
            "ramp_up_seconds": 30,
            "duration_minutes": 5,
            "throughput_rps": 2,
        },
    }


def test_render_jmeter_script_with_precheck(tmp_path: Path) -> None:
    config = _base_config(
        "jmeter",
        {"test_plan_path": "performance/checkout.jmx", "docker_image": ""},
        checks=["verify_scenario_exists"],
    )
    package = build_generic_package(config)

    outputs = render_tool_script(config, package, tmp_path)

    script_path = tmp_path / "scripts" / "run-jmeter.sh"
    assert outputs == [str(script_path)]
    assert script_path.exists()
    assert script_path.stat().st_mode & 0o111 == 0o111

    content = script_path.read_text(encoding="utf-8")
    assert "resolve_test_case() {" in content
    assert 'if [ ! -f "$test_plan_path" ]; then' in content
    assert "local test_plan_path=performance/checkout.jmx" in content
    assert "local docker_image=justb4/jmeter:5.6.3" in content
    assert 'docker run --rm -v "$(pwd):/workspace" -w /workspace "$docker_image" \\' in content
    assert '-n -t "$test_plan_path"' in content
    assert 'if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then' in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_jmeter_script_without_precheck_flag(tmp_path: Path) -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""}, checks=[])
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)

    content = (tmp_path / "scripts" / "run-jmeter.sh").read_text(encoding="utf-8")
    assert "Test plan not found" not in content


def _resolve(script_path: Path, selector: str, variable: str) -> subprocess.CompletedProcess:
    command = f'source {shlex.quote(str(script_path))}; resolve_test_case {shlex.quote(selector)}; echo "${variable}"'
    return subprocess.run(["bash", "-c", command], capture_output=True, text=True)


def test_jmeter_resolver_uses_exact_match_not_glob(tmp_path: Path) -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["environments"] = [
        {"key": "*", "identifier": "should-not-match", "scenarios": [{"key": "*", "identifier": "nope"}]},
        {"key": "staging", "identifier": "env-stg", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]},
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    result = _resolve(script_path, "staging: checkout_smoke", "environment_identifier")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "env-stg"


def test_resolver_handles_adversarial_catalog_keys(tmp_path: Path) -> None:
    # The validator rejects such keys, so this exercises the second line of
    # defense: the generated comparisons must still match literally.
    marker = tmp_path / "should-not-exist"
    adversarial_keys = [
        "qa's staging",
        "east us",
        f"$(touch {marker})",
        f"`touch {marker}`",
    ]
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["environments"] = [
        {"key": key, "identifier": f"env-{i}", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
        for i, key in enumerate(adversarial_keys)
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr

    for i, key in enumerate(adversarial_keys):
        result = _resolve(script_path, f"{key}: checkout_smoke", "environment_identifier")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"env-{i}"

    assert not marker.exists()


def test_resolver_rejects_unknown_test_case(tmp_path: Path) -> None:
    script_path = tmp_path / "scripts" / "run-jmeter.sh"
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    render_tool_script(config, build_generic_package(config), tmp_path)

    result = _resolve(script_path, "qa: nope", "environment_identifier")

    assert result.returncode != 0
    assert "Unknown test case: qa: nope" in result.stderr


def test_resolver_gives_same_scenario_key_its_own_identifier_per_environment(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    config["catalog"]["environments"] = [
        {"key": "qa", "identifier": "QA", "scenarios": [{"key": "checkout_smoke", "identifier": "C:\\qa.lrs"}]},
        {"key": "staging", "identifier": "Staging", "scenarios": [{"key": "checkout_smoke", "identifier": "C:\\stg.lrs"}]},
    ]
    render_tool_script(config, build_generic_package(config), tmp_path)
    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"

    assert _resolve(script_path, "qa: checkout_smoke", "scenario_identifier").stdout.strip() == "C:\\qa.lrs"
    assert _resolve(script_path, "staging: checkout_smoke", "scenario_identifier").stdout.strip() == "C:\\stg.lrs"


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
    assert "resolve_test_case() {" in content
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
    assert 'echo "Usage: $0 --test-case \'<environment>: <scenario>\' --timeout-minutes <minutes> [--test-type LABEL] [--users N]' in content

    # Calling main without --timeout-minutes must fail fast during arg
    # parsing, before any network call -- safe to actually execute. main's
    # Usage-error branch calls `exit 1` directly, which terminates this
    # whole bash -c process immediately (not just the function), so the
    # process's own exit code IS the check -- there is no shell code after
    # `main ...` in this command line that would ever run.
    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}"; main --test-case \"qa: checkout_smoke\"'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Usage:" in result.stderr


def test_render_blazemeter_script_no_todo_comments_for_its_checks(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
        checks=["verify_host_reachable", "verify_project_exists", "verify_scenario_exists"],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    content = (tmp_path / "scripts" / "run-blazemeter.sh").read_text(encoding="utf-8")

    assert "# TODO precheck: verify_host_reachable" not in content
    assert "# TODO precheck: verify_project_exists" not in content
    assert "# TODO precheck: verify_scenario_exists" not in content


def test_render_blazemeter_script_sanitizes_results_dir_from_hostile_catalog_key(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    config["catalog"]["environments"] = [
        {"key": "../../pwn", "identifier": "Hostile", "scenarios": [{"key": "checkout_smoke", "identifier": "1234567"}]}
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "resolve_test_case() {" in content

    result = _resolve(script_path, "../../pwn: checkout_smoke", "environment_slug")
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


def test_render_blazemeter_script_rejects_non_numeric_timeout(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"

    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{script_path}"; main --test-case \"qa: checkout_smoke\" --timeout-minutes abc',
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "ERROR: --timeout-minutes must be a positive integer" in result.stderr


def test_render_blazemeter_script_tolerates_transient_poll_failure(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    call_counter = tmp_path / "poll_calls"
    call_counter.write_text("0")

    # Fake curl: the /start and /summary calls always succeed. The /status
    # call fails (exit 7, simulating a transient network error) on its
    # first invocation, then succeeds with ENDED on every call after that.
    (stub_bin / "curl").write_text(f"""#!/usr/bin/env bash
if [[ "$*" == *"/start"* ]]; then
  echo '{{"result": {{"id": 999}}}}'
  exit 0
fi
if [[ "$*" == *"/status"* ]]; then
  count=$(cat "{call_counter}")
  count=$((count + 1))
  echo "$count" > "{call_counter}"
  if [ "$count" -eq 1 ]; then
    exit 7
  fi
  echo '{{"result": {{"status": "ENDED"}}}}'
  exit 0
fi
if [[ "$*" == *"/summary"* ]]; then
  echo '{{}}'
  exit 0
fi
exit 0
""")
    (stub_bin / "curl").chmod(0o755)

    # Fake jq: only supports the two exact filter expressions this script
    # uses, extracted with grep against the simple flat JSON the fake curl
    # above produces -- no real jq or python dependency needed for the test.
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
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke", "--timeout-minutes", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "WARNING: failed to poll BlazeMeter status" in result.stderr


def test_render_blazemeter_script_shows_raw_response_on_non_json_start_reply(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    # Fake curl returns an HTML error page (e.g. a proxy's 502) instead of
    # JSON -- a routine real-world SaaS/proxy failure mode.
    (stub_bin / "curl").write_text("""#!/usr/bin/env bash
echo '<html><body>502 Bad Gateway</body></html>'
exit 0
""")
    (stub_bin / "curl").chmod(0o755)
    # Fake jq always fails to parse, matching real jq's behavior against
    # non-JSON input.
    (stub_bin / "jq").write_text("""#!/usr/bin/env bash
exit 1
""")
    (stub_bin / "jq").chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["BLAZEMETER_API_KEY_ID"] = "id"
    env["BLAZEMETER_API_KEY_SECRET"] = "secret"

    result = subprocess.run(
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke", "--timeout-minutes", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "ERROR: BlazeMeter did not return a master id" in result.stderr
    assert "502 Bad Gateway" in result.stderr


def test_render_loadrunner_script_runs_wlrun_for_real(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    package = build_generic_package(config)

    outputs = render_tool_script(config, package, tmp_path)

    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"
    assert outputs == [str(script_path)]
    assert script_path.exists()
    assert script_path.stat().st_mode & 0o111 == 0o111

    content = script_path.read_text(encoding="utf-8")
    assert "resolve_test_case() {" in content
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
    config["catalog"]["environments"] = [
        {
            "key": "../../pwn",
            "identifier": "Hostile",
            "scenarios": [{"key": "checkout_smoke", "identifier": "C:\\Scenarios\\checkout_smoke.lrs"}],
        }
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "resolve_test_case() {" in content

    # The slug resolver must map the hostile key to a sanitized value at
    # generation time (safe_filename_component == slugify), not pass it
    # through raw -- this is what closes the run-output/../../pwn escape
    # the final review demonstrated.
    result = _resolve(script_path, "../../pwn: checkout_smoke", "environment_slug")
    assert result.returncode == 0, result.stderr
    slug = result.stdout.strip()
    assert ".." not in slug
    assert "/" not in slug

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_loadrunner_script_no_todo_comments_for_its_checks(tmp_path: Path) -> None:
    config = _base_config(
        "loadrunner_professional",
        {"wlrun_path": "wlrun"},
        checks=["verify_controller_access", "verify_scenario_exists"],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"
    content = script_path.read_text(encoding="utf-8")

    # Both checks are implemented -- real guards, not TODO comments.
    assert "# TODO precheck: verify_controller_access" not in content
    assert "# TODO precheck: verify_scenario_exists" not in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_render_jmeter_script_todo_comments_for_unhandled_checks(tmp_path: Path) -> None:
    config = _base_config(
        "jmeter",
        {"test_plan_path": "plan.jmx", "docker_image": ""},
        checks=["verify_scenario_exists", "verify_controller_access"],
    )
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "# TODO precheck: verify_scenario_exists" not in content
    # verify_controller_access is a valid enum value but not one JMeter's
    # script handles -- it gets a TODO comment instead of silently
    # vanishing.
    assert "# TODO precheck: verify_controller_access" in content

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr


def test_json_escape_helper_produces_valid_json_string(tmp_path: Path) -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
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
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "resolve_test_case() {" in content
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
    (stub_bin / "docker").write_text("""#!/usr/bin/env bash
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
    (stub_bin / "docker").chmod(0o755)

    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["tool"] == "jmeter"
    assert summary["status"] == "passed"
    assert summary["artifact_status"] == "complete"
    assert summary["environment"] == "qa"
    assert summary["scenario"] == "checkout_smoke"
    assert summary["results_dir"] == "run-output/qa_checkout-smoke"
    assert summary["report_link"] == "run-output/qa_checkout-smoke/report/index.html"
    assert set(summary.keys()) == {
        "tool", "run_id", "environment", "scenario", "status", "started_at", "ended_at",
        "duration_seconds", "report_link", "results_dir", "artifact_status",
        "test_type", "users", "ramp_up_seconds", "duration_minutes", "throughput_rps",
    }
    assert summary["test_type"] == "load"
    assert summary["users"] == 10
    assert summary["throughput_rps"] == 2


def test_render_jmeter_script_writes_failing_run_summary_and_propagates_exit_code(tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "docker").write_text("#!/usr/bin/env bash\nexit 2\n")
    (stub_bin / "docker").chmod(0o755)

    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1

    summary_path = tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["artifact_status"] == "incomplete"


def test_render_jmeter_script_no_run_summary_on_precheck_failure(tmp_path: Path) -> None:
    config = _base_config(
        "jmeter",
        {"test_plan_path": "nonexistent-plan.jmx", "docker_image": ""},
        checks=["verify_scenario_exists"],
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    result = subprocess.run(
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke"],
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
    (stub_bin / "docker").write_text("""#!/usr/bin/env bash
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
    (stub_bin / "docker").chmod(0o755)

    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["environments"][0]["scenarios"] = [
        {"key": "checkout_smoke", "identifier": "SC-1"},
        {"key": "checkout_full", "identifier": "SC-2"},
    ]
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"

    for scenario in ("checkout_smoke", "checkout_full"):
        result = subprocess.run(
            ["bash", str(script_path), "--test-case", f"qa: {scenario}"],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr

    assert (tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json").exists()
    assert (tmp_path / "run-output" / "qa_checkout-full" / "run-summary.json").exists()


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
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["tool"] == "loadrunner_professional"
    assert summary["status"] == "passed"
    assert summary["artifact_status"] == "complete"
    assert summary["report_link"] == "run-output/qa_checkout-smoke"


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
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1

    summary_path = tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json"
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
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "Scenario file not found" in result.stderr
    run_output = tmp_path / "run-output"
    assert not run_output.exists() or not list(run_output.rglob("run-summary.json"))


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
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke", "--timeout-minutes", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["tool"] == "blazemeter"
    assert summary["run_id"] == "999"
    assert summary["status"] == "passed"
    assert summary["artifact_status"] == "complete"
    assert summary["report_link"] == "https://a.blazemeter.com/app/#/masters/999/summary"


def test_render_blazemeter_script_writes_run_summary_when_summary_fetch_fails(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    # /start and /status succeed as in test_render_blazemeter_script_writes_run_summary_on_ended,
    # but /reports/main/summary fails (nonzero exit) -- this must not abort the
    # whole script under set -euo pipefail, and run-summary.json must still be
    # written with artifact_status "incomplete" since the summary fetch failed.
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
  exit 22
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
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke", "--timeout-minutes", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "WARNING: failed to fetch BlazeMeter summary report" in result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["artifact_status"] == "incomplete"


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
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke", "--timeout-minutes", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "ERROR: BlazeMeter test ended with status ERROR" in result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json"
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
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke", "--timeout-minutes", "0"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "Timed out after 0 minutes" in result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "error"
    assert summary["artifact_status"] == "incomplete"


def test_render_blazemeter_script_escapes_hostile_base_url_in_run_summary(tmp_path: Path) -> None:
    # A hostile base_url containing an embedded `", "status": "passed", "junk": "`
    # sequence would, if report_link/run_id were spliced into run-summary.json
    # unescaped, produce syntactically valid JSON with a duplicate "status" key --
    # and both json.loads and jq take the LAST value for a duplicate key, so a
    # genuinely FAILED run would be read back as "passed". This proves that
    # injection is closed now that report_link/run_id are run through json_escape.
    hostile_base_url = 'https://a.example.com", "status": "passed", "junk": "'
    config = _base_config(
        "blazemeter", {"base_url": hostile_base_url, "workspace_id": "12345", "project_id": "67890"}
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
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke", "--timeout-minutes", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1, result.stderr

    summary_path = tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"


def test_render_jmeter_script_escapes_embedded_control_characters_in_run_summary(tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "docker").write_text("""#!/usr/bin/env bash
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
    (stub_bin / "docker").chmod(0o755)

    hostile_scenario_key = "smoke\ntest\tcase"
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["environments"][0]["scenarios"] = [
        {"key": hostile_scenario_key, "identifier": "SC-1"}
    ]
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(script_path), "--test-case", f"qa: {hostile_scenario_key}"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    run_output = tmp_path / "run-output"
    summary_files = list(run_output.rglob("run-summary.json"))
    assert len(summary_files) == 1
    summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
    assert summary["scenario"] == hostile_scenario_key


def test_all_three_tools_run_summary_share_same_key_set(tmp_path: Path) -> None:
    # JMeter
    jmeter_dir = tmp_path / "jmeter-setup"
    jmeter_stub_bin = tmp_path / "jmeter-stub-bin"
    jmeter_stub_bin.mkdir()
    (jmeter_stub_bin / "docker").write_text("""#!/usr/bin/env bash
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
    (jmeter_stub_bin / "docker").chmod(0o755)
    jmeter_config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    jmeter_package = build_generic_package(jmeter_config)
    render_tool_script(jmeter_config, jmeter_package, jmeter_dir)
    jmeter_env = dict(os.environ)
    jmeter_env["PATH"] = f"{jmeter_stub_bin}:{jmeter_env['PATH']}"
    jmeter_result = subprocess.run(
        ["bash", str(jmeter_dir / "scripts" / "run-jmeter.sh"), "--test-case", "qa: checkout_smoke"],
        capture_output=True,
        text=True,
        env=jmeter_env,
        cwd=jmeter_dir,
    )
    assert jmeter_result.returncode == 0, jmeter_result.stderr
    jmeter_summary = json.loads(
        (jmeter_dir / "run-output" / "qa_checkout-smoke" / "run-summary.json").read_text(encoding="utf-8")
    )

    # LoadRunner Professional
    loadrunner_dir = tmp_path / "loadrunner-setup"
    loadrunner_stub_bin = tmp_path / "loadrunner-stub-bin"
    loadrunner_stub_bin.mkdir()
    (loadrunner_stub_bin / "wlrun").write_text("""#!/usr/bin/env bash
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
    (loadrunner_stub_bin / "wlrun").chmod(0o755)
    loadrunner_config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    loadrunner_package = build_generic_package(loadrunner_config)
    render_tool_script(loadrunner_config, loadrunner_package, loadrunner_dir)
    loadrunner_env = dict(os.environ)
    loadrunner_env["PATH"] = f"{loadrunner_stub_bin}:{loadrunner_env['PATH']}"
    loadrunner_result = subprocess.run(
        [
            "bash",
            str(loadrunner_dir / "scripts" / "run-loadrunner_professional.sh"),
            "--test-case", "qa: checkout_smoke",
        ],
        capture_output=True,
        text=True,
        env=loadrunner_env,
        cwd=loadrunner_dir,
    )
    assert loadrunner_result.returncode == 0, loadrunner_result.stderr
    loadrunner_summary = json.loads(
        (loadrunner_dir / "run-output" / "qa_checkout-smoke" / "run-summary.json").read_text(encoding="utf-8")
    )

    # BlazeMeter
    blazemeter_dir = tmp_path / "blazemeter-setup"
    blazemeter_stub_bin = tmp_path / "blazemeter-stub-bin"
    blazemeter_stub_bin.mkdir()
    (blazemeter_stub_bin / "curl").write_text("""#!/usr/bin/env bash
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
    (blazemeter_stub_bin / "curl").chmod(0o755)
    (blazemeter_stub_bin / "jq").write_text("""#!/usr/bin/env bash
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
    (blazemeter_stub_bin / "jq").chmod(0o755)
    blazemeter_config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    blazemeter_package = build_generic_package(blazemeter_config)
    render_tool_script(blazemeter_config, blazemeter_package, blazemeter_dir)
    blazemeter_env = dict(os.environ)
    blazemeter_env["PATH"] = f"{blazemeter_stub_bin}:{blazemeter_env['PATH']}"
    blazemeter_env["BLAZEMETER_API_KEY_ID"] = "id"
    blazemeter_env["BLAZEMETER_API_KEY_SECRET"] = "secret"
    blazemeter_result = subprocess.run(
        [
            "bash",
            str(blazemeter_dir / "scripts" / "run-blazemeter.sh"),
            "--test-case", "qa: checkout_smoke", "--timeout-minutes", "1",
        ],
        capture_output=True,
        text=True,
        env=blazemeter_env,
        cwd=blazemeter_dir,
    )
    assert blazemeter_result.returncode == 0, blazemeter_result.stderr
    blazemeter_summary = json.loads(
        (blazemeter_dir / "run-output" / "qa_checkout-smoke" / "run-summary.json").read_text(encoding="utf-8")
    )

    assert set(jmeter_summary.keys()) == set(loadrunner_summary.keys()) == set(blazemeter_summary.keys())


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
        ["bash", str(script_path), "--test-case", "qa: checkout_smoke", "--timeout-minutes", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1

    run_output = tmp_path / "run-output"
    assert not run_output.exists() or not list(run_output.rglob("run-summary.json"))



# --- load profile + TODO guard -------------------------------------------------


def _stub_bin_with(tmp_path: Path, **scripts: str) -> dict:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir(exist_ok=True)
    for name, body in scripts.items():
        (stub_bin / name).write_text(f"#!/usr/bin/env bash\n{body}")
        (stub_bin / name).chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["BLAZEMETER_API_KEY_ID"] = "id"
    env["BLAZEMETER_API_KEY_SECRET"] = "secret"
    return env


def _logging_docker(tmp_path: Path) -> str:
    return f"""echo "$@" > "{tmp_path / 'docker-args'}"
prev=""; logfile=""; outdir=""
for arg in "$@"; do
  if [ "$prev" = "-l" ]; then logfile="$arg"; fi
  if [ "$prev" = "-o" ]; then outdir="$arg"; fi
  prev="$arg"
done
mkdir -p "$outdir"; echo "<html></html>" > "$outdir/index.html"; touch "$logfile"
"""


_FAKE_JQ = """input="$(cat)"
case "${@: -1}" in
  '.result.id') echo "$input" | grep -o '"id": *[0-9]*' | grep -o '[0-9]*$' ;;
  '.result.status') echo "$input" | grep -o '"status": *"[A-Z]*"' | grep -o '"[A-Z]*"$' | tr -d '"' ;;
  *) exit 1 ;;
esac
"""


def _logging_curl(tmp_path: Path) -> str:
    return f"""echo "$@" >> "{tmp_path / 'curl-log'}"
if [[ "$*" == *"/start"* ]]; then echo '{{"result": {{"id": 999}}}}'; exit 0; fi
if [[ "$*" == *"/status"* ]]; then echo '{{"result": {{"status": "ENDED"}}}}'; exit 0; fi
if [[ "$*" == *"/summary"* ]]; then echo '{{}}'; exit 0; fi
exit 0
"""


def _render(tmp_path: Path, config: dict) -> Path:
    package = build_generic_package(config)
    render_tool_script(config, package, tmp_path)
    return tmp_path / "scripts" / f"run-{config['tool']['type']}.sh"


def _run(script_path: Path, args: list[str], env: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script_path), *args], capture_output=True, text=True, env=env, cwd=cwd)


_QA = ["--test-case", "qa: checkout_smoke"]
_BLAZEMETER_CONNECTION = {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}


def test_jmeter_script_passes_load_profile_as_properties(tmp_path: Path) -> None:
    script_path = _render(tmp_path, _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""}))
    env = _stub_bin_with(tmp_path, docker=_logging_docker(tmp_path))

    result = _run(script_path, _QA, env, tmp_path)

    assert result.returncode == 0, result.stderr
    args = (tmp_path / "docker-args").read_text().split()
    for expected in (
        "-Jtest_type=load",
        "-Jusers=10",
        "-Jramp_up_seconds=30",
        "-Jduration_seconds=330",  # JMeter thread lifetime includes ramp-up: 30s + 5min
        "-Jthroughput_rps=2",
        "-Jthroughput_per_minute=120",
    ):
        assert expected in args


def test_jmeter_script_flag_overrides_baked_load_value(tmp_path: Path) -> None:
    script_path = _render(tmp_path, _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""}))
    env = _stub_bin_with(tmp_path, docker=_logging_docker(tmp_path))

    result = _run(script_path, [*_QA, "--users", "50", "--test-type", "stress"], env, tmp_path)

    assert result.returncode == 0, result.stderr
    args = (tmp_path / "docker-args").read_text().split()
    assert "-Jusers=50" in args
    assert "-Jtest_type=stress" in args
    summary = json.loads((tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json").read_text())
    assert summary["users"] == 50
    assert summary["test_type"] == "stress"


def test_jmeter_script_rejects_non_numeric_load_flag(tmp_path: Path) -> None:
    script_path = _render(tmp_path, _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""}))
    env = _stub_bin_with(tmp_path, docker=_logging_docker(tmp_path))

    result = _run(script_path, [*_QA, "--users", "abc"], env, tmp_path)

    assert result.returncode == 1
    assert "load_profile.users must be a whole number" in result.stderr
    assert not (tmp_path / "docker-args").exists()


def test_jmeter_script_stops_on_todo_load_value(tmp_path: Path) -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["load_profile"]["users"] = "TODO"
    script_path = _render(tmp_path, config)
    env = _stub_bin_with(tmp_path, docker=_logging_docker(tmp_path))

    result = _run(script_path, _QA, env, tmp_path)

    assert result.returncode == 1
    assert "load_profile.users is not set (still TODO)" in result.stderr
    assert not (tmp_path / "docker-args").exists()
    assert not (tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json").exists()


def test_jmeter_script_stops_on_todo_test_plan_path(tmp_path: Path) -> None:
    script_path = _render(tmp_path, _base_config("jmeter", {"test_plan_path": "", "docker_image": ""}))
    env = _stub_bin_with(tmp_path, docker=_logging_docker(tmp_path))

    result = _run(script_path, _QA, env, tmp_path)

    assert result.returncode == 1
    assert "tool.connection.test_plan_path is not set (still TODO)" in result.stderr
    assert not (tmp_path / "docker-args").exists()


def test_jmeter_script_stops_on_todo_scenario_identifier(tmp_path: Path) -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["environments"][0]["scenarios"] = [{"key": "checkout_smoke", "identifier": "TODO"}]
    script_path = _render(tmp_path, config)
    env = _stub_bin_with(tmp_path, docker=_logging_docker(tmp_path))

    result = _run(script_path, _QA, env, tmp_path)

    assert result.returncode == 1
    assert "scenario identifier for checkout_smoke is not set" in result.stderr
    assert not (tmp_path / "docker-args").exists()


def test_blazemeter_script_patches_load_profile_before_start(tmp_path: Path) -> None:
    script_path = _render(tmp_path, _base_config("blazemeter", _BLAZEMETER_CONNECTION))
    env = _stub_bin_with(tmp_path, curl=_logging_curl(tmp_path), jq=_FAKE_JQ)

    result = _run(script_path, [*_QA, "--timeout-minutes", "1"], env, tmp_path)

    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "curl-log").read_text().splitlines()
    patch_index = next(i for i, call in enumerate(calls) if "-X PATCH" in call)
    start_index = next(i for i, call in enumerate(calls) if "/start" in call)
    assert patch_index < start_index
    patch = calls[patch_index]
    assert "/api/v4/tests/SC-1" in patch
    assert '"concurrency": 10' in patch
    assert '"rampUp": "30s"' in patch
    assert '"holdFor": "5m"' in patch
    assert '"throughput": 2' in patch


def test_blazemeter_script_omits_throughput_when_uncapped(tmp_path: Path) -> None:
    config = _base_config("blazemeter", _BLAZEMETER_CONNECTION)
    config["load_profile"]["throughput_rps"] = 0
    script_path = _render(tmp_path, config)
    env = _stub_bin_with(tmp_path, curl=_logging_curl(tmp_path), jq=_FAKE_JQ)

    result = _run(script_path, [*_QA, "--timeout-minutes", "1"], env, tmp_path)

    assert result.returncode == 0, result.stderr
    patch = next(call for call in (tmp_path / "curl-log").read_text().splitlines() if "-X PATCH" in call)
    assert "throughput" not in patch


def test_blazemeter_script_stops_on_todo_project_id_before_any_api_call(tmp_path: Path) -> None:
    script_path = _render(tmp_path, _base_config("blazemeter", {**_BLAZEMETER_CONNECTION, "project_id": ""}))
    env = _stub_bin_with(tmp_path, curl=_logging_curl(tmp_path), jq=_FAKE_JQ)

    result = _run(script_path, [*_QA, "--timeout-minutes", "1"], env, tmp_path)

    assert result.returncode == 1
    assert "tool.connection.project_id is not set (still TODO)" in result.stderr
    assert not (tmp_path / "curl-log").exists()


def test_blazemeter_run_summary_includes_load_profile(tmp_path: Path) -> None:
    script_path = _render(tmp_path, _base_config("blazemeter", _BLAZEMETER_CONNECTION))
    env = _stub_bin_with(tmp_path, curl=_logging_curl(tmp_path), jq=_FAKE_JQ)

    result = _run(script_path, [*_QA, "--timeout-minutes", "1"], env, tmp_path)

    assert result.returncode == 0, result.stderr
    summary = json.loads((tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json").read_text())
    assert summary["test_type"] == "load"
    assert summary["duration_minutes"] == 5


def test_loadrunner_script_accepts_only_test_type(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    script_path = _render(tmp_path, config)
    content = script_path.read_text(encoding="utf-8")

    assert "--test-type" in content
    assert "--users" not in content
    assert "-Jusers" not in content


def test_loadrunner_run_summary_has_test_type_but_no_load_numbers(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    script_path = _render(tmp_path, config)
    env = _stub_bin_with(
        tmp_path,
        wlrun='prev=""; for a in "$@"; do [ "$prev" = "-ResultName" ] && mkdir -p "$a" && echo r > "$a/results.xml"; prev="$a"; done\n',
    )

    result = _run(script_path, [*_QA, "--test-type", "soak"], env, tmp_path)

    assert result.returncode == 0, result.stderr
    summary = json.loads((tmp_path / "run-output" / "qa_checkout-smoke" / "run-summary.json").read_text())
    assert summary["test_type"] == "soak"
    # Same key set as the other tools (one shared schema), but LoadRunner's
    # load shape comes from the .lrs, so the numbers are null.
    assert summary["users"] is None
    assert summary["throughput_rps"] is None


def test_loadrunner_script_stops_on_todo_scenario_identifier(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    config["catalog"]["environments"][0]["scenarios"] = [{"key": "checkout_smoke", "identifier": "TODO"}]
    script_path = _render(tmp_path, config)
    env = _stub_bin_with(tmp_path, wlrun=f'touch "{tmp_path / "wlrun-called"}"\n')

    result = _run(script_path, _QA, env, tmp_path)

    assert result.returncode == 1
    assert "scenario identifier for checkout_smoke is not set" in result.stderr
    assert not (tmp_path / "wlrun-called").exists()


def test_jmeter_script_rejects_leading_zero_load_flag(tmp_path: Path) -> None:
    # bash arithmetic would read 08/09 as (invalid) octal, and "08" is not valid JSON.
    script_path = _render(tmp_path, _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""}))
    env = _stub_bin_with(tmp_path, docker=_logging_docker(tmp_path))

    result = _run(script_path, [*_QA, "--users", "08"], env, tmp_path)

    assert result.returncode == 1
    assert "load_profile.users must be a whole number" in result.stderr
    assert not (tmp_path / "docker-args").exists()
