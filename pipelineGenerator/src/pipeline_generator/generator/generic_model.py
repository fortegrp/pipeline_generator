from __future__ import annotations

from dataclasses import dataclass, field


def run_target_selector(environment_key: str, scenario_key: str) -> str:
    """The one format for an environment+scenario pair: the manual pipeline's
    dropdown value, an automated job's baked value, and the generated script's
    resolve_test_case key. Catalog keys can't contain ":" (validator), so
    distinct pairs never collide.
    """
    return f"{environment_key}: {scenario_key}"


@dataclass
class RunTarget:
    environment_key: str
    environment_identifier: str
    scenario_key: str
    scenario_identifier: str

    @property
    def selector(self) -> str:
        return run_target_selector(self.environment_key, self.scenario_key)


@dataclass
class ManualPipelineSpec:
    name: str
    timeout_minutes: int


@dataclass
class AutomatedJobSpec:
    name: str
    timeout_minutes: int
    test_case: str


@dataclass
class LoadInput:
    name: str  # load_profile field name, e.g. "ramp_up_seconds"
    default: str  # config value as text, or TODO ("" allowed for test_type)

    @property
    def flag(self) -> str:
        return "--" + self.name.replace("_", "-")

    @property
    def env_var(self) -> str:
        return self.name.upper()


@dataclass
class GenericPipelinePackage:
    setup_id: str
    cicd_type: str
    tool_type: str
    manual_pipeline: ManualPipelineSpec | None = None
    automated_jobs: list[AutomatedJobSpec] = field(default_factory=list)
    run_targets: list[RunTarget] = field(default_factory=list)
    load_inputs: list[LoadInput] = field(default_factory=list)
