from __future__ import annotations

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
            f'source "{script_path}"; main --environment qa --scenario checkout_smoke --timeout-minutes abc',
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
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke", "--timeout-minutes", "1"],
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
        ["bash", str(script_path), "--environment", "qa", "--scenario", "checkout_smoke", "--timeout-minutes", "1"],
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
