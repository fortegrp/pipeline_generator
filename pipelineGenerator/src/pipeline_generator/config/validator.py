from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from pipeline_generator.config.placeholders import is_placeholder
from pipeline_generator.config.schema import (
    CATALOG_KEY_PATTERN,
    GENERATION_MODES,
    LOAD_PROFILE_FIELDS,
    LOAD_PROFILE_MINIMUMS,
    LOAD_PROFILE_TOOLS,
    TEST_TYPE_PATTERN,
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


def _warn_duplicate_keys(items: list[dict], path: str, consequence: str, result: ValidationResult) -> None:
    counts = Counter(item.get("key") for item in items if isinstance(item.get("key"), str))
    for key, count in counts.items():
        if count > 1 and not is_placeholder(key):
            result.warnings.append(f"{path} has {count} entries with the duplicate key '{key}' -- {consequence}")


def _check_key_format(key: object, path: str, result: ValidationResult) -> None:
    if is_placeholder(key):
        # Even a draft can't render an entry without a key (it's the dropdown value).
        result.errors.append(f"{path} has an entry whose key is missing.")
    elif not isinstance(key, str):
        result.errors.append(f"{path} key {key!r} must be a string -- quote it in the YAML.")
    elif not re.fullmatch(CATALOG_KEY_PATTERN, key):
        result.errors.append(
            f"{path} key {key!r} may only contain letters, digits, '_', '.', '-' "
            "and must start with a letter or digit."
        )


def _is_int_at_least(value: object, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _warn_timeouts_shorter_than_test(
    load_profile: dict, manual_pipeline: dict, automated_jobs: list[dict], result: ValidationResult
) -> None:
    ramp_up, duration = load_profile.get("ramp_up_seconds"), load_profile.get("duration_minutes")
    if not (_is_int_at_least(ramp_up, 0) and _is_int_at_least(duration, 1)):
        return
    test_minutes = ramp_up / 60 + duration
    timeouts = []
    if manual_pipeline.get("enabled"):
        timeouts.append(("manual_pipeline", manual_pipeline.get("timeout_minutes")))
    timeouts += [
        (f"automated job '{job.get('name', 'unknown')}'", job.get("timeout_minutes", 240))
        for job in automated_jobs
        if job.get("enabled", True)
    ]
    for label, timeout in timeouts:
        if isinstance(timeout, int) and timeout <= test_minutes:
            result.warnings.append(
                f"{label} timeout ({timeout} min) is not longer than ramp-up + duration "
                f"({test_minutes:g} min) -- the CI job would be killed before the test finishes."
            )


def validate_config(config: dict) -> ValidationResult:
    result = ValidationResult()
    incomplete = bool(config.get("incomplete", False))

    setup = _as_dict(config.get("setup", {}), "setup", result)
    cicd = _as_dict(config.get("cicd", {}), "cicd", result)
    tool = _as_dict(config.get("tool", {}), "tool", result)
    catalog = _as_dict(config.get("catalog", {}), "catalog", result)
    manual_pipeline = _as_dict(config.get("manual_pipeline", {}), "manual_pipeline", result)
    automated_jobs = _as_list_of_dicts(config.get("automated_jobs", []), "automated_jobs", result)

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

    generation_mode = setup.get("generation_mode")
    if generation_mode not in GENERATION_MODES:
        result.errors.append(f"Unsupported setup.generation_mode: {generation_mode}")

    if "scenarios" in catalog:
        result.errors.append(
            "catalog.scenarios is no longer supported -- move each scenario under its environment's "
            "scenarios list (catalog.environments[].scenarios)."
        )
    environments = _as_list_of_dicts(catalog.get("environments", []), "catalog.environments", result)
    if not environments:
        result.warnings.append("No environments are defined in catalog.environments.")
    _warn_duplicate_keys(
        environments, "catalog.environments", "merge them into one entry with all their scenarios.", result
    )

    pairs: set[tuple[object, object]] = set()
    for env in environments:
        env_key = env.get("key")
        env_path = f"catalog.environments.{'unknown' if is_placeholder(env_key) else env_key}"
        _check_key_format(env_key, "catalog.environments", result)
        if is_placeholder(env.get("identifier")):
            result.warnings.append(f"{env_path}.identifier is missing.")

        scenarios = _as_list_of_dicts(env.get("scenarios", []), f"{env_path}.scenarios", result)
        if not scenarios:
            result.warnings.append(f"{env_path}.scenarios is missing -- this environment can never be selected.")
        _warn_duplicate_keys(
            scenarios,
            f"{env_path}.scenarios",
            "only the first is ever reachable; the others are silently unselectable.",
            result,
        )
        for scenario in scenarios:
            scenario_key = scenario.get("key")
            scenario_path = f"{env_path}.scenarios.{'unknown' if is_placeholder(scenario_key) else scenario_key}"
            _check_key_format(scenario_key, f"{env_path}.scenarios", result)
            if is_placeholder(scenario.get("identifier")):
                result.warnings.append(f"{scenario_path}.identifier is missing.")
            pairs.add((env_key, scenario_key))

    if not pairs:
        result.warnings.append("No scenarios are defined under catalog.environments[].scenarios.")
        if manual_pipeline.get("enabled"):
            result.warnings.append("Manual pipeline is enabled but there are no environment/scenario pairs.")

    env_keys = {env.get("key") for env in environments}
    for job in automated_jobs:
        if not job.get("enabled", True):
            continue
        name = job.get("name", "unknown")
        if is_placeholder(job.get("environment_ref")):
            result.warnings.append(f"Automated job '{name}' environment_ref is missing.")
        elif is_placeholder(job.get("scenario_ref")):
            result.warnings.append(f"Automated job '{name}' scenario_ref is missing.")
        elif job.get("environment_ref") not in env_keys:
            result.warnings.append(f"Automated job '{name}' references an unknown environment.")
        elif (job.get("environment_ref"), job.get("scenario_ref")) not in pairs:
            result.warnings.append(
                f"Automated job '{name}' references an unknown scenario for environment "
                f"'{job.get('environment_ref')}'."
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

    if tool_type == "loadrunner_professional" and is_placeholder(cicd.get("runner")):
        result.warnings.append(
            "cicd.runner is missing -- LoadRunner Professional must run on an agent co-located with the "
            "Controller, not the platform's hosted default."
        )

    load_profile = _as_dict(config.get("load_profile", {}), "load_profile", result)
    test_type = load_profile.get("test_type")
    if test_type is not None and not (isinstance(test_type, str) and re.fullmatch(TEST_TYPE_PATTERN, test_type)):
        result.errors.append(
            f"load_profile.test_type must be a single-line label of up to 64 letters, digits, spaces, "
            f"'_', '.' or '-', got: {test_type!r}"
        )
    if tool_type in LOAD_PROFILE_TOOLS:
        for name in LOAD_PROFILE_FIELDS:
            value = load_profile.get(name)
            if is_placeholder(value):
                result.warnings.append(f"load_profile.{name} is missing.")
            elif not _is_int_at_least(value, LOAD_PROFILE_MINIMUMS[name]):
                result.errors.append(
                    f"load_profile.{name} must be a whole number >= {LOAD_PROFILE_MINIMUMS[name]}, got: {value!r}"
                )
        _warn_timeouts_shorter_than_test(load_profile, manual_pipeline, automated_jobs, result)

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

