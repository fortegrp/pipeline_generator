from __future__ import annotations

from pathlib import Path
from typing import Callable

from pipeline_generator.config.loader import load_config, save_config
from pipeline_generator.config.placeholders import TODO_VALUE
from pipeline_generator.config.schema import (
    GENERATION_MODES,
    PRE_RUN_CHECKS,
    PRE_RUN_CHECKS_BY_TOOL,
    SUPPORTED_CICD,
    SUPPORTED_TOOLS,
    merged_base_config,
    required_field_values,
)
from pipeline_generator.config.validator import validate_config
from pipeline_generator.wizard.id_builder import build_setup_id
from pipeline_generator.wizard.prompts import (
    prompt_bool,
    prompt_choice,
    prompt_multi_choice,
    prompt_positive_int,
    prompt_text,
)

TOTAL_STEPS = 8

GENERATION_MODE_HINTS = {
    "manual_only": (
        "A human triggers this on demand (e.g. a button, GitHub's workflow_dispatch), "
        "picking environment and scenario each time it runs."
    ),
    "automated_only": (
        "No on-demand pipeline; instead generate reusable job(s) that someone else's "
        "pipeline calls automatically, each with a fixed environment/scenario."
    ),
    "both": "Generate both: an on-demand manual pipeline, and automated job(s) for other pipelines to call.",
}


def _section(step: int, title: str) -> None:
    print(f"\n[Step {step}/{TOTAL_STEPS}] {title}")


def _step_setup_basics(config: dict, output_path: Path) -> None:
    _section(1, "What should this setup generate?")
    print(
        "A performance pipeline can be triggered two different ways: manually by a "
        "person, or automatically as part of a pipeline someone else owns. Pick "
        "which one(s) you want generated -- this also decides which later wizard "
        "steps apply."
    )
    config["setup"]["generation_mode"] = prompt_choice(
        "Generation mode",
        GENERATION_MODES,
        default=config["setup"]["generation_mode"],
        descriptions=GENERATION_MODE_HINTS,
    )
    save_config(output_path, config)


def _step_cicd_and_tool(config: dict, output_path: Path) -> None:
    _section(2, "CI/CD platform and performance tool")
    config["cicd"]["type"] = prompt_choice(
        "CI/CD platform",
        SUPPORTED_CICD,
        default=config["cicd"]["type"] if config["cicd"]["type"] in SUPPORTED_CICD else SUPPORTED_CICD[0],
    )
    config["tool"]["type"] = prompt_choice(
        "Performance tool",
        SUPPORTED_TOOLS,
        default=config["tool"]["type"] if config["tool"]["type"] in SUPPORTED_TOOLS else SUPPORTED_TOOLS[0],
    )
    save_config(output_path, config)


def _step_setup_identifier(config: dict, output_path: Path) -> None:
    _section(3, "Setup identifier")
    generated_id = build_setup_id(
        config["cicd"]["type"],
        config["tool"]["type"],
    )
    config["setup"]["id"] = prompt_text(
        "Suggested setup ID",
        default=generated_id,
        allow_blank=False,
    )
    save_config(output_path, config)


def _step_connection(config: dict, output_path: Path) -> None:
    _section(4, "Tool connection details")
    _prompt_connection(config)
    save_config(output_path, config)


def _step_manual_pipeline(config: dict, output_path: Path) -> None:
    _section(5, "Manual pipeline")
    if config["setup"]["generation_mode"] in {"manual_only", "both"}:
        config["manual_pipeline"]["enabled"] = prompt_bool(
            "Generate manual pipeline?",
            default=bool(config["manual_pipeline"]["enabled"]),
        )
        config["manual_pipeline"]["name"] = prompt_text(
            "Manual pipeline name",
            default=config["manual_pipeline"]["name"],
        ) or "Performance Manual Run"
        config["manual_pipeline"]["timeout_minutes"] = prompt_positive_int(
            "Manual pipeline timeout minutes",
            default=int(config["manual_pipeline"]["timeout_minutes"]),
        )
    else:
        config["manual_pipeline"]["enabled"] = False
    save_config(output_path, config)


def _step_catalog(config: dict, output_path: Path) -> None:
    _section(6, "Environments and scenarios")
    config["catalog"]["environments"] = _prompt_catalog_section("environment", config["catalog"]["environments"])
    config["catalog"]["scenarios"] = _prompt_catalog_section("scenario", config["catalog"]["scenarios"])
    save_config(output_path, config)


def _step_automated_jobs(config: dict, output_path: Path) -> None:
    _section(7, "Automated jobs")
    if config["setup"]["generation_mode"] in {"automated_only", "both"}:
        config["automated_jobs"] = _prompt_automated_jobs_section(config)
    elif config["setup"]["generation_mode"] == "manual_only":
        config["automated_jobs"] = []
    save_config(output_path, config)


def _step_checks_and_finalize(config: dict, output_path: Path) -> None:
    _section(8, "Pre-run checks")
    config["pre_run_checks"] = _prompt_checks(config.get("pre_run_checks", []), config["tool"]["type"])
    config["readme"]["include_manual_usage"] = config["manual_pipeline"]["enabled"]
    config["readme"]["include_automated_usage"] = bool(config["automated_jobs"])
    config["incomplete"] = _is_incomplete(config)
    save_config(output_path, config)


def run_wizard(output_path: Path, resume: bool = False) -> dict:
    existing = load_config(output_path) if resume and output_path.exists() else None
    config = merged_base_config(existing)

    print("Performance automation wizard")
    print("Leave fields blank when you want to keep TODO placeholders and finish later.")

    _step_setup_basics(config, output_path)
    _step_cicd_and_tool(config, output_path)
    _step_setup_identifier(config, output_path)
    _step_connection(config, output_path)
    _step_manual_pipeline(config, output_path)
    _step_catalog(config, output_path)
    _step_automated_jobs(config, output_path)
    _step_checks_and_finalize(config, output_path)

    _print_summary(config)
    print("\n" + validate_config(config).to_console())

    return config


def _prompt_connection(config: dict) -> None:
    tool_type = config["tool"]["type"]
    connection = config["tool"]["connection"]
    if tool_type == "loadrunner_professional":
        connection["wlrun_path"] = prompt_text(
            "Optional path to the wlrun executable (blank uses PATH)",
            default=connection.get("wlrun_path", ""),
        )
    elif tool_type == "blazemeter":
        connection["base_url"] = prompt_text(
            "BlazeMeter base URL",
            default=connection.get("base_url", "https://a.blazemeter.com"),
        ) or TODO_VALUE
        connection["workspace_id"] = prompt_text(
            "BlazeMeter workspace ID",
            default=connection.get("workspace_id", TODO_VALUE),
        ) or TODO_VALUE
        connection["project_id"] = prompt_text(
            "BlazeMeter project ID",
            default=connection.get("project_id", TODO_VALUE),
        ) or TODO_VALUE
    elif tool_type == "jmeter":
        connection["test_plan_path"] = prompt_text(
            "Path to the JMeter test plan (.jmx) in the target repository",
            default=connection.get("test_plan_path", TODO_VALUE),
        ) or TODO_VALUE
        connection["jmeter_bin"] = prompt_text(
            "Optional path to the jmeter executable (blank uses PATH)",
            default=connection.get("jmeter_bin", ""),
        )


def _prompt_catalog_items(kind: str) -> list[dict]:
    items: list[dict] = []
    print(f"Enter {kind}s. Leave key blank to finish.")
    while True:
        key = prompt_text(f"{kind} key", allow_blank=True)
        if not key:
            break
        identifier = prompt_text(f"{kind} remote identifier", default=TODO_VALUE) or TODO_VALUE
        items.append({"key": key, "identifier": identifier})
    return items


def _prompt_resumable_list(
    label: str, existing: list[dict], item_names: list[str], collect: Callable[[], list[dict]]
) -> list[dict]:
    if existing:
        print(f"Existing {label}: {', '.join(item_names)}")
        action = prompt_choice(
            f"What do you want to do with {label}?",
            ["keep as-is", "add more", "start over"],
            default="keep as-is",
        )
        if action == "keep as-is":
            return existing
        if action == "start over":
            return collect()
        return existing + collect()
    if prompt_bool(f"Add {label} now?", default=False):
        return collect()
    return existing


def _prompt_catalog_section(kind: str, existing: list[dict]) -> list[dict]:
    return _prompt_resumable_list(
        f"{kind}s", existing, [item["key"] for item in existing], lambda: _prompt_catalog_items(kind)
    )


def _prompt_automated_jobs(config: dict) -> list[dict]:
    jobs: list[dict] = []
    environment_keys = [item["key"] for item in config["catalog"]["environments"]]
    scenario_keys = [item["key"] for item in config["catalog"]["scenarios"]]
    print("Enter automated jobs. Leave name blank to finish.")
    while True:
        name = prompt_text("Automated job name", allow_blank=True)
        if not name:
            break
        if environment_keys:
            environment_ref = prompt_choice("Environment key", environment_keys, default=environment_keys[0])
        else:
            environment_ref = prompt_text("Environment key", default=TODO_VALUE) or TODO_VALUE
        if scenario_keys:
            scenario_ref = prompt_choice("Scenario key", scenario_keys, default=scenario_keys[0])
        else:
            scenario_ref = prompt_text("Scenario key", default=TODO_VALUE) or TODO_VALUE
        timeout_minutes = prompt_positive_int("Timeout minutes", default=240)
        jobs.append(
            {
                "name": name,
                "enabled": True,
                "environment_ref": environment_ref,
                "scenario_ref": scenario_ref,
                "timeout_minutes": timeout_minutes,
            }
        )
    return jobs


def _prompt_automated_jobs_section(config: dict) -> list[dict]:
    existing = config["automated_jobs"]
    return _prompt_resumable_list(
        "automated jobs", existing, [job["name"] for job in existing], lambda: _prompt_automated_jobs(config)
    )


def _prompt_checks(existing: list[str], tool_type: str) -> list[str]:
    options = PRE_RUN_CHECKS_BY_TOOL.get(tool_type, PRE_RUN_CHECKS)
    return prompt_multi_choice("Select pre-run checks", options, default=existing)


def _print_summary(config: dict) -> None:
    setup = config["setup"]
    print("\nSetup summary")
    print(f"  ID: {setup['id']}")
    print(f"  CI/CD: {config['cicd']['type']}")
    print(f"  Tool: {config['tool']['type']}")
    print(f"  Manual pipeline: {'enabled' if config['manual_pipeline']['enabled'] else 'disabled'}")
    print(f"  Environments: {len(config['catalog']['environments'])}")
    print(f"  Scenarios: {len(config['catalog']['scenarios'])}")
    print(f"  Automated jobs: {len(config['automated_jobs'])}")


def _is_incomplete(config: dict) -> bool:
    values_to_check = [value for _, value in required_field_values(config)]
    return any(value in {"", TODO_VALUE, None} for value in values_to_check)
