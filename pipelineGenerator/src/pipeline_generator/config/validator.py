from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from pipeline_generator.config.placeholders import is_placeholder
from pipeline_generator.config.schema import (
    AUTH_TYPES,
    GENERATION_MODES,
    PRE_RUN_CHECKS,
    SUPPORTED_CICD,
    SUPPORTED_TOOLS,
    required_field_values,
)


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_console(self) -> str:
        lines: list[str] = []
        if not self.errors and not self.warnings:
            return "Validation passed."
        if self.errors:
            lines.append("Errors:")
            lines.extend(f"- {item}" for item in self.errors)
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {item}" for item in self.warnings)
        return "\n".join(lines)


def _as_dict(value: object, path: str, result: ValidationResult) -> dict:
    """Coerce a config section to a dict, recording an error and falling back
    to {} on a type mismatch (including an explicit `null` in the YAML)
    rather than letting every later .get() call on it crash with an
    AttributeError.
    """
    if isinstance(value, dict):
        return value
    result.errors.append(f"{path} must be a mapping, got: {value!r}")
    return {}


def _as_list_of_dicts(value: object, path: str, result: ValidationResult) -> list[dict]:
    """Coerce a config section to a list of dicts, recording an error for the
    section itself if it isn't a list at all, and for any entry within it
    that isn't a mapping -- rather than crashing on the first .get() call
    against a non-dict entry.
    """
    if not isinstance(value, list):
        result.errors.append(f"{path} must be a list, got: {value!r}")
        return []
    items: list[dict] = []
    for index, item in enumerate(value):
        if isinstance(item, dict):
            items.append(item)
        else:
            result.errors.append(f"{path}[{index}] must be a mapping, got: {item!r}")
    return items


def validate_config(config: dict) -> ValidationResult:
    result = ValidationResult()
    incomplete = bool(config.get("incomplete", False))

    setup = _as_dict(config.get("setup", {}), "setup", result)
    cicd = _as_dict(config.get("cicd", {}), "cicd", result)
    tool = _as_dict(config.get("tool", {}), "tool", result)
    catalog = _as_dict(config.get("catalog", {}), "catalog", result)
    manual_pipeline = _as_dict(config.get("manual_pipeline", {}), "manual_pipeline", result)
    automated_jobs = _as_list_of_dicts(config.get("automated_jobs", []), "automated_jobs", result)
    auth = _as_dict(tool.get("auth", {}), "tool.auth", result)

    for path, value in required_field_values(config):
        if is_placeholder(value):
            target = result.warnings if incomplete else result.errors
            target.append(f"{path} is missing.")

    cicd_type = cicd.get("type")
    if not is_placeholder(cicd_type) and cicd_type not in SUPPORTED_CICD:
        result.errors.append(f"Unsupported cicd.type: {cicd_type}")

    tool_type = tool.get("type")
    if not is_placeholder(tool_type) and tool_type not in SUPPORTED_TOOLS:
        result.errors.append(f"Unsupported tool.type: {tool_type}")

    auth_type = auth.get("type")
    if not is_placeholder(auth_type) and auth_type not in AUTH_TYPES:
        result.errors.append(f"Unsupported tool.auth.type: {auth_type}")

    generation_mode = setup.get("generation_mode")
    if generation_mode not in GENERATION_MODES:
        result.errors.append(f"Unsupported setup.generation_mode: {generation_mode}")

    environments = _as_list_of_dicts(catalog.get("environments", []), "catalog.environments", result)
    scenarios = _as_list_of_dicts(catalog.get("scenarios", []), "catalog.scenarios", result)
    if not environments:
        result.warnings.append("No environments are defined in catalog.environments.")
    if not scenarios:
        result.warnings.append("No scenarios are defined in catalog.scenarios.")

    env_keys = {item.get("key") for item in environments}
    scenario_keys = {item.get("key") for item in scenarios}

    env_key_counts = Counter(item.get("key") for item in environments if not is_placeholder(item.get("key")))
    for key, count in env_key_counts.items():
        if count > 1:
            result.warnings.append(
                f"catalog.environments has {count} entries with the duplicate key '{key}' -- "
                "only the first is ever reachable; the others are silently unselectable."
            )

    scenario_key_counts = Counter(item.get("key") for item in scenarios if not is_placeholder(item.get("key")))
    for key, count in scenario_key_counts.items():
        if count > 1:
            result.warnings.append(
                f"catalog.scenarios has {count} entries with the duplicate key '{key}' -- "
                "only the first is ever reachable; the others are silently unselectable."
            )

    for item in environments:
        key = item.get("key")
        display_key = "unknown" if is_placeholder(key) else key
        if is_placeholder(item.get("identifier")):
            result.warnings.append(f"catalog.environments.{display_key}.identifier is missing.")

    for item in scenarios:
        key = item.get("key")
        display_key = "unknown" if is_placeholder(key) else key
        if is_placeholder(item.get("identifier")):
            result.warnings.append(f"catalog.scenarios.{display_key}.identifier is missing.")

    if manual_pipeline.get("enabled"):
        if not scenarios or not environments:
            result.warnings.append("Manual pipeline is enabled but environments or scenarios are missing.")

    for job in automated_jobs:
        if not job.get("enabled", True):
            continue
        if job.get("environment_ref") not in env_keys:
            result.warnings.append(
                f"Automated job '{job.get('name', 'unknown')}' references an unknown environment."
            )
        if job.get("scenario_ref") not in scenario_keys:
            result.warnings.append(
                f"Automated job '{job.get('name', 'unknown')}' references an unknown scenario."
            )

    connection = _as_dict(tool.get("connection", {}), "tool.connection", result)

    if tool_type == "blazemeter":
        for key in ["base_url", "workspace_id", "project_id"]:
            value = connection.get(key)
            if is_placeholder(value):
                result.warnings.append(f"tool.connection.{key} is missing for BlazeMeter.")

    if tool_type == "jmeter":
        for key in ["test_plan_path"]:
            value = connection.get(key)
            if is_placeholder(value):
                result.warnings.append(f"tool.connection.{key} is missing for JMeter.")

    for check in config.get("pre_run_checks", []):
        if check not in PRE_RUN_CHECKS:
            result.warnings.append(
                f"Unrecognized pre_run_checks value: {check!r} -- it will be silently dropped and "
                "generate no check (and no TODO comment) in the generated script. Check for a typo."
            )

    automated_enabled = any(job.get("enabled", True) for job in automated_jobs)
    if not manual_pipeline.get("enabled") and not automated_enabled:
        result.warnings.append(
            "Neither the manual pipeline nor any automated job is enabled -- this setup will "
            "generate no CI/CD pipeline files."
        )

    return result

