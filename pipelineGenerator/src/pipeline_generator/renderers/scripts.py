from __future__ import annotations

from pathlib import Path

from pipeline_generator.config.placeholders import TODO_VALUE
from pipeline_generator.config.schema import PRE_RUN_CHECKS
from pipeline_generator.generator.generic_model import GenericPipelinePackage, InputOption
from pipeline_generator.renderers.quoting import safe_filename_component, shell_quote


def _allowed_pre_run_checks(config: dict) -> list[str]:
    """Return only the pre_run_checks values that match the canonical enum.

    config/validator.py does not validate pre_run_checks, so any string could
    be present here. Values are rendered into generated scripts (in comments
    or condition checks), so anything outside the known enum is dropped to
    prevent shell injection via crafted strings (e.g. embedded newlines).
    """
    return [check for check in config.get("pre_run_checks", []) if check in PRE_RUN_CHECKS]


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


def _render_slug_resolvers(package: GenericPipelinePackage) -> str:
    environment_slugs = [
        InputOption(value=item.value, display_name=item.display_name, identifier=safe_filename_component(item.value))
        for item in package.environments
    ]
    scenario_slugs = [
        InputOption(value=item.value, display_name=item.display_name, identifier=safe_filename_component(item.value))
        for item in package.scenarios
    ]
    environment_slug_resolver = _render_resolver_function(
        "resolve_environment_slug", "environment", environment_slugs
    )
    scenario_slug_resolver = _render_resolver_function("resolve_scenario_slug", "scenario", scenario_slugs)
    return f"{environment_slug_resolver}\n\n{scenario_slug_resolver}"


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


def _render_arg_parsing(include_timeout: bool = False) -> str:
    timeout_local = ""
    timeout_case = ""
    timeout_required_check = ""
    timeout_usage = ""
    timeout_numeric_check = ""
    if include_timeout:
        timeout_local = '  local timeout_minutes=""\n'
        timeout_case = '      --timeout-minutes) timeout_minutes="$2"; shift 2 ;;\n'
        timeout_required_check = ' || [ -z "$timeout_minutes" ]'
        timeout_usage = ' --timeout-minutes <minutes>'
        timeout_numeric_check = """
  case "$timeout_minutes" in
    ''|*[!0-9]*)
      echo "ERROR: --timeout-minutes must be a positive integer, got: $timeout_minutes" >&2
      exit 1
      ;;
  esac
"""

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
{timeout_numeric_check}
  local environment_identifier
  local scenario_identifier
  environment_identifier="$(resolve_environment_identifier "$environment_key")"
  scenario_identifier="$(resolve_scenario_identifier "$scenario_key")"
"""


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
