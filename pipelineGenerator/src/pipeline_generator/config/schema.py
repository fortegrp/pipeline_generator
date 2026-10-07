from __future__ import annotations

from copy import deepcopy

from pipeline_generator.config.placeholders import TODO_VALUE

DEFAULT_JMETER_DOCKER_IMAGE = "justb4/jmeter:5.6.3"

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

PRE_RUN_CHECKS = (
    "verify_controller_access",
    "verify_scenario_exists",
    "verify_host_reachable",
    "verify_project_exists",
    "verify_docker_available",
)

PRE_RUN_CHECKS_BY_TOOL = {
    "jmeter": ("verify_scenario_exists", "verify_docker_available"),
    "loadrunner_professional": (
        "verify_controller_access",
        "verify_scenario_exists",
    ),
    "blazemeter": (
        "verify_host_reachable",
        "verify_project_exists",
        "verify_scenario_exists",
    ),
}

LOAD_PROFILE_FIELDS = ("users", "ramp_up_seconds", "duration_minutes", "throughput_rps")
LOAD_PROFILE_MINIMUMS = {"users": 1, "ramp_up_seconds": 0, "duration_minutes": 1, "throughput_rps": 0}
# LoadRunner Professional is deliberately absent: wlrun has no CLI for
# Vusers/schedule, so its load shape always comes from the .lrs itself.
LOAD_PROFILE_TOOLS = ("jmeter", "blazemeter")
# test_type reaches YAML, Groovy and shell as free text, so keep it a short,
# single-line label.
TEST_TYPE_PATTERN = r"[A-Za-z0-9 _.-]{0,64}"
LOAD_PROFILE_LABELS = {
    "test_type": "Test type label (e.g. load, stress, soak, spike)",
    "users": "Number of users",
    "ramp_up_seconds": "Ramp-up (seconds)",
    "duration_minutes": "Duration at full load (minutes)",
    "throughput_rps": "Target throughput (requests/second, 0 = no cap)",
}


REQUIRED_FIELD_PATHS = (
    "setup.id",
    "cicd.type",
    "tool.type",
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
        "incomplete": True,
        "setup": {
            "id": TODO_VALUE,
            "generation_mode": "both",
        },
        "cicd": {
            "type": TODO_VALUE,
        },
        "tool": {
            "type": TODO_VALUE,
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
        "load_profile": {
            "test_type": "load",
            **{name: TODO_VALUE for name in LOAD_PROFILE_FIELDS},
        },
        "pre_run_checks": [],
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

