from __future__ import annotations

from copy import deepcopy

from pipeline_generator.config.placeholders import TODO_VALUE

SUPPORTED_CICD = (
    "github_actions",
    "azure_devops",
    "jenkins",
)

SUPPORTED_TOOLS = (
    "loadrunner_professional",
    "blazemeter",
    "jmeter",
)

GENERATION_MODES = (
    "manual_only",
    "automated_only",
    "both",
)

AUTH_TYPES = (
    "api_token",
    "username_password",
    "service_account",
    "network_vpn_manual_setup",
    "none",
)

WORKING_LOCATIONS = (
    "central_repo",
    "customer_repo",
)

PIPELINE_DESTINATIONS = (
    "stay_in_central_repo",
    "copy_to_customer_repo",
)

PRE_RUN_CHECKS = (
    "verify_controller_access",
    "verify_scenario_exists",
    "verify_load_generators_connected",
    "verify_host_reachable",
    "verify_project_exists",
    "collect_results",
)

PRE_RUN_CHECKS_BY_TOOL = {
    "jmeter": ("verify_scenario_exists", "collect_results"),
    "loadrunner_professional": (
        "verify_controller_access",
        "verify_scenario_exists",
        "verify_load_generators_connected",
        "collect_results",
    ),
    "blazemeter": (
        "verify_host_reachable",
        "verify_project_exists",
        "verify_scenario_exists",
        "collect_results",
    ),
}


REQUIRED_FIELD_PATHS = (
    "setup.id",
    "setup.target_repository",
    "cicd.type",
    "tool.type",
    "tool.auth.type",
)


def required_field_values(config: dict) -> list[tuple[str, object]]:
    """Resolve each dotted path in REQUIRED_FIELD_PATHS against config.

    The single source of truth for which fields a "complete" (non-draft)
    config must have filled in -- both validator.py's error/warning split
    and the wizard's own incomplete-flag computation read from this same
    list, so the two can't silently drift apart from each other.
    """
    resolved: list[tuple[str, object]] = []
    for path in REQUIRED_FIELD_PATHS:
        value: object = config
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        resolved.append((path, value))
    return resolved


def base_config() -> dict:
    return {
        "version": 1,
        "incomplete": True,
        "setup": {
            "id": TODO_VALUE,
            "working_location": "central_repo",
            "final_pipeline_destination": "copy_to_customer_repo",
            "ci_can_use_central_repo_directly": False,
            "target_repository": TODO_VALUE,
            "generation_mode": "both",
        },
        "cicd": {
            "type": TODO_VALUE,
        },
        "tool": {
            "type": TODO_VALUE,
            "auth": {
                "type": TODO_VALUE,
            },
            "connection": {},
        },
        "manual_pipeline": {
            "enabled": True,
            "name": "Performance Manual Run",
            "timeout_minutes": 240,
        },
        "automated_jobs": [],
        "catalog": {
            "environments": [],
            "scenarios": [],
        },
        "pre_run_checks": [],
        "artifacts": {
            "download_remote_results": True,
            "fail_on_partial_download": False,
        },
        "readme": {
            "include_manual_usage": True,
            "include_automated_usage": True,
        },
    }


def merged_base_config(existing: dict | None) -> dict:
    config = base_config()
    if not existing:
        return config

    def merge(base: dict, incoming: dict) -> dict:
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                merge(base[key], value)
            else:
                base[key] = deepcopy(value)
        return base

    return merge(config, existing)

