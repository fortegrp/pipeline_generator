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


def _render_loadrunner_slug_resolvers(package: GenericPipelinePackage) -> str:
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

{_render_loadrunner_slug_resolvers(package)}

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
