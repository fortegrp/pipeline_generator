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

WORKING_LOCATION_HINTS = {
    "central_repo": "Setup files are authored and maintained in this generator's own repo.",
    "customer_repo": "Setup files are authored directly inside the customer's repository.",
}

PIPELINE_DESTINATION_HINTS = {
    "stay_in_central_repo": "Generated pipeline files stay in this central repo; the customer repo references them from there.",
    "copy_to_customer_repo": "Generated pipeline files are copied into the customer's own repository.",
}

GENERATION_MODE_HINTS = {
    "manual_only": "Only generate the on-demand pipeline performance engineers trigger by hand.",
    "automated_only": "Only generate the reusable automated job DevOps wires into their own pipelines.",
    "both": "Generate both the manual pipeline and the automated job.",
}


def _section(step: int, title: str) -> None:
    print(f"\n[Step {step}/{TOTAL_STEPS}] {title}")


def run_wizard(output_path: Path, resume: bool = False) -> dict:
    existing = load_config(output_path) if resume and output_path.exists() else None
    config = merged_base_config(existing)

    print("Performance automation wizard")
    print("Leave fields blank when you want to keep TODO placeholders and finish later.")

    _section(1, "Setup basics")
    config["setup"]["working_location"] = prompt_choice(
        "Working location",
        WORKING_LOCATIONS,
        default=config["setup"]["working_location"],
        descriptions=WORKING_LOCATION_HINTS,
    )
    config["setup"]["final_pipeline_destination"] = prompt_choice(
        "Final pipeline destination",
        PIPELINE_DESTINATIONS,
        default=config["setup"]["final_pipeline_destination"],
        descriptions=PIPELINE_DESTINATION_HINTS,
    )
    config["setup"]["ci_can_use_central_repo_directly"] = prompt_bool(
        "Can the CI/CD system consume files directly from the central repo?",
        default=bool(config["setup"]["ci_can_use_central_repo_directly"]),
        hint="If yes, generated files can be referenced straight from the central repo without copying them anywhere.",
    )
    config["setup"]["target_repository"] = prompt_text(
        "Target repository identity",
        default=config["setup"]["target_repository"],
    ) or TODO_VALUE
    config["setup"]["generation_mode"] = prompt_choice(
        "Generation mode",
        GENERATION_MODES,
        default=config["setup"]["generation_mode"],
        descriptions=GENERATION_MODE_HINTS,
    )
    save_config(output_path, config)

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

    _section(3, "Setup identifier")
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

    _section(4, "Tool connection details")
    _prompt_connection(config)
    save_config(output_path, config)

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

    _section(6, "Environments and scenarios")
    config["catalog"]["environments"] = _prompt_catalog_section("environment", config["catalog"]["environments"])
    config["catalog"]["scenarios"] = _prompt_catalog_section("scenario", config["catalog"]["scenarios"])
    save_config(output_path, config)

    _section(7, "Automated jobs")
    if config["setup"]["generation_mode"] in {"automated_only", "both"}:
        config["automated_jobs"] = _prompt_automated_jobs_section(config)
    elif config["setup"]["generation_mode"] == "manual_only":
        config["automated_jobs"] = []
    save_config(output_path, config)

    _section(8, "Pre-run checks")
    config["pre_run_checks"] = _prompt_checks(config.get("pre_run_checks", []))
    config["readme"]["include_manual_usage"] = config["manual_pipeline"]["enabled"]
    config["readme"]["include_automated_usage"] = bool(config["automated_jobs"])
    config["incomplete"] = _is_incomplete(config)
    save_config(output_path, config)

    _print_summary(config)
    print("\n" + validate_config(config).to_console())

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


def _prompt_catalog_section(kind: str, existing: list[dict]) -> list[dict]:
    if existing:
        print(f"Existing {kind}s: {', '.join(item['key'] for item in existing)}")
        action = prompt_choice(
            f"What do you want to do with {kind}s?",
            ["keep as-is", "add more", "start over"],
            default="keep as-is",
        )
        if action == "keep as-is":
            return existing
        if action == "start over":
            return _prompt_catalog_items(kind)
        return existing + _prompt_catalog_items(kind)
    if prompt_bool(f"Add {kind}s now?", default=False):
        return _prompt_catalog_items(kind)
    return existing


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
    if existing:
        print(f"Existing automated jobs: {', '.join(job['name'] for job in existing)}")
        action = prompt_choice(
            "What do you want to do with automated jobs?",
            ["keep as-is", "add more", "start over"],
            default="keep as-is",
        )
        if action == "keep as-is":
            return existing
        if action == "start over":
            return _prompt_automated_jobs(config)
        return existing + _prompt_automated_jobs(config)
    if prompt_bool("Add automated jobs now?", default=False):
        return _prompt_automated_jobs(config)
    return existing


def _prompt_checks(existing: list[str]) -> list[str]:
    return prompt_multi_choice("Select pre-run checks", PRE_RUN_CHECKS, default=existing)


def _print_summary(config: dict) -> None:
    setup = config["setup"]
    print("\nSetup summary")
    print(f"  ID: {setup['id']}")
    print(f"  CI/CD: {config['cicd']['type']}")
    print(f"  Tool: {config['tool']['type']}")
    print(f"  Target repository: {setup['target_repository']}")
    print(f"  Manual pipeline: {'enabled' if config['manual_pipeline']['enabled'] else 'disabled'}")
    print(f"  Environments: {len(config['catalog']['environments'])}")
    print(f"  Scenarios: {len(config['catalog']['scenarios'])}")
    print(f"  Automated jobs: {len(config['automated_jobs'])}")


def _is_incomplete(config: dict) -> bool:
    values_to_check = [
        config["setup"]["id"],
        config["setup"]["target_repository"],
        config["cicd"]["type"],
        config["tool"]["type"],
        config["tool"]["auth"]["type"],
    ]
    return any(value in {"", TODO_VALUE, None} for value in values_to_check)
