from __future__ import annotations

from dataclasses import dataclass, field

from pipeline_generator.config.placeholders import is_placeholder
from pipeline_generator.config.schema import AUTH_TYPES, GENERATION_MODES, SUPPORTED_CICD, SUPPORTED_TOOLS


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


def validate_config(config: dict) -> ValidationResult:
    result = ValidationResult()
    incomplete = bool(config.get("incomplete", False))

    setup = config.get("setup", {})
    cicd = config.get("cicd", {})
    tool = config.get("tool", {})
    catalog = config.get("catalog", {})
    manual_pipeline = config.get("manual_pipeline", {})
    automated_jobs = config.get("automated_jobs", [])

    required_paths = [
        ("setup.id", setup.get("id")),
        ("setup.target_repository", setup.get("target_repository")),
        ("cicd.type", cicd.get("type")),
        ("tool.type", tool.get("type")),
        ("tool.auth.type", tool.get("auth", {}).get("type")),
    ]

    for path, value in required_paths:
        if is_placeholder(value):
            target = result.warnings if incomplete else result.errors
            target.append(f"{path} is missing.")

    cicd_type = cicd.get("type")
    if not is_placeholder(cicd_type) and cicd_type not in SUPPORTED_CICD:
        result.errors.append(f"Unsupported cicd.type: {cicd_type}")

    tool_type = tool.get("type")
    if not is_placeholder(tool_type) and tool_type not in SUPPORTED_TOOLS:
        result.errors.append(f"Unsupported tool.type: {tool_type}")

    auth_type = tool.get("auth", {}).get("type")
    if not is_placeholder(auth_type) and auth_type not in AUTH_TYPES:
        result.errors.append(f"Unsupported tool.auth.type: {auth_type}")

    generation_mode = setup.get("generation_mode")
    if generation_mode not in GENERATION_MODES:
        result.errors.append(f"Unsupported setup.generation_mode: {generation_mode}")

    environments = catalog.get("environments", [])
    scenarios = catalog.get("scenarios", [])
    if not environments:
        result.warnings.append("No environments are defined in catalog.environments.")
    if not scenarios:
        result.warnings.append("No scenarios are defined in catalog.scenarios.")

    env_keys = {item.get("key") for item in environments}
    scenario_keys = {item.get("key") for item in scenarios}

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

    if tool_type == "blazemeter":
        connection = tool.get("connection", {})
        for key in ["base_url", "workspace_id", "project_id"]:
            value = connection.get(key)
            if is_placeholder(value):
                result.warnings.append(f"tool.connection.{key} is missing for BlazeMeter.")

    if tool_type == "jmeter":
        connection = tool.get("connection", {})
        for key in ["test_plan_path"]:
            value = connection.get(key)
            if is_placeholder(value):
                result.warnings.append(f"tool.connection.{key} is missing for JMeter.")

    return result

