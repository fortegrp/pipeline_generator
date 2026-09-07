from __future__ import annotations

from pathlib import Path

from pipeline_generator.config.loader import load_config, save_config
from pipeline_generator.config.placeholders import TODO_VALUE
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
from pipeline_generator.wizard.id_builder import build_setup_id
from pipeline_generator.wizard.prompts import prompt_bool, prompt_choice, prompt_positive_int, prompt_text


def run_wizard(output_path: Path, resume: bool = False) -> dict:
    existing = load_config(output_path) if resume and output_path.exists() else None
    config = merged_base_config(existing)

    print("Performance automation wizard")
    print("Leave fields blank when you want to keep TODO placeholders and finish later.")

    config["setup"]["working_location"] = prompt_choice(
        "Working location",
        WORKING_LOCATIONS,
        default=config["setup"]["working_location"],
    )
    save_config(output_path, config)

    config["setup"]["final_pipeline_destination"] = prompt_choice(
        "Final pipeline destination",
        PIPELINE_DESTINATIONS,
        default=config["setup"]["final_pipeline_destination"],
    )
    config["setup"]["ci_can_use_central_repo_directly"] = prompt_bool(
        "Can the CI/CD system consume files directly from the central repo?",
        default=bool(config["setup"]["ci_can_use_central_repo_directly"]),
    )
    config["setup"]["target_repository"] = prompt_text(
        "Target repository identity",
        default=config["setup"]["target_repository"],
    ) or TODO_VALUE
    config["setup"]["generation_mode"] = prompt_choice(
        "Generation mode",
        GENERATION_MODES,
        default=config["setup"]["generation_mode"],
    )
    save_config(output_path, config)

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
    config["tool"]["auth"]["type"] = prompt_choice(
        "Authentication option",
        AUTH_TYPES,
        default=(
            config["tool"]["auth"]["type"]
            if config["tool"]["auth"]["type"] in AUTH_TYPES
            else AUTH_TYPES[0]
        ),
    )
    save_config(output_path, config)

    generated_id = build_setup_id(
        config["cicd"]["type"],
        config["tool"]["type"],
        config["setup"]["target_repository"],
    )
    config["setup"]["id"] = prompt_text(
        "Suggested setup ID",
        default=generated_id,
        allow_blank=False,
    )
    save_config(output_path, config)

    _prompt_connection(config)
    save_config(output_path, config)

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
        save_config(output_path, config)
    else:
        config["manual_pipeline"]["enabled"] = False

    if prompt_bool("Add environments now?", default=bool(config["catalog"]["environments"])):
        config["catalog"]["environments"] = _prompt_catalog_items("environment")
        save_config(output_path, config)

    if prompt_bool("Add scenarios now?", default=bool(config["catalog"]["scenarios"])):
        config["catalog"]["scenarios"] = _prompt_catalog_items("scenario")
        save_config(output_path, config)

    if config["setup"]["generation_mode"] in {"automated_only", "both"} and prompt_bool(
        "Add automated jobs now?",
        default=bool(config["automated_jobs"]),
    ):
        config["automated_jobs"] = _prompt_automated_jobs(config)
        save_config(output_path, config)
    elif config["setup"]["generation_mode"] == "manual_only":
        config["automated_jobs"] = []

    config["pre_run_checks"] = _prompt_checks(config.get("pre_run_checks", []))
    config["readme"]["include_manual_usage"] = config["manual_pipeline"]["enabled"]
    config["readme"]["include_automated_usage"] = bool(config["automated_jobs"])
    config["incomplete"] = _is_incomplete(config)
    save_config(output_path, config)
    return config


def _prompt_connection(config: dict) -> None:
    tool_type = config["tool"]["type"]
    connection = config["tool"]["connection"]
    if tool_type == "loadrunner_professional":
        connection["controller_host"] = prompt_text(
            "LoadRunner controller host",
            default=connection.get("controller_host", TODO_VALUE),
        ) or TODO_VALUE
        connection["controller_results_path"] = prompt_text(
            "LoadRunner results path on controller",
            default=connection.get("controller_results_path", TODO_VALUE),
        ) or TODO_VALUE
        connection["domain"] = prompt_text(
            "Optional LoadRunner domain",
            default=connection.get("domain", ""),
        )
        connection["project"] = prompt_text(
            "Optional LoadRunner project",
            default=connection.get("project", ""),
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


def _prompt_catalog_items(kind: str) -> list[dict]:
    items: list[dict] = []
    print(f"Enter {kind}s. Leave key blank to finish.")
    while True:
        key = prompt_text(f"{kind} key", allow_blank=True)
        if not key:
            break
        name = prompt_text(f"{kind} display name", default=key)
        identifier = prompt_text(f"{kind} remote identifier", default=TODO_VALUE) or TODO_VALUE
        items.append({"key": key, "name": name, "identifier": identifier})
    return items


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


def _prompt_checks(existing: list[str]) -> list[str]:
    checks: list[str] = []
    print("Select pre-run checks. Answer yes/no for each.")
    for check in PRE_RUN_CHECKS:
        checks.append(check) if prompt_bool(f"Enable {check}?", default=check in existing) else None
    return checks


def _is_incomplete(config: dict) -> bool:
    values_to_check = [
        config["setup"]["id"],
        config["setup"]["target_repository"],
        config["cicd"]["type"],
        config["tool"]["type"],
        config["tool"]["auth"]["type"],
    ]
    return any(value in {"", TODO_VALUE, None} for value in values_to_check)
