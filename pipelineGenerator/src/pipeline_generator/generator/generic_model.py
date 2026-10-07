from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InputOption:
    value: str
    identifier: str


@dataclass
class PipelineInput:
    key: str
    label: str
    kind: str
    options: list[InputOption]


@dataclass
class ManualPipelineSpec:
    name: str
    inputs: list[PipelineInput]
    timeout_minutes: int


@dataclass
class AutomatedJobSpec:
    name: str
    timeout_minutes: int
    environment_ref: str
    scenario_ref: str


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
    environments: list[InputOption] = field(default_factory=list)
    scenarios: list[InputOption] = field(default_factory=list)
    load_inputs: list[LoadInput] = field(default_factory=list)
