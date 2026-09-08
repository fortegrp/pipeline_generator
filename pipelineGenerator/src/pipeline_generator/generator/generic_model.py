from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InputOption:
    value: str
    display_name: str
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
class GenericPipelinePackage:
    setup_id: str
    cicd_type: str
    tool_type: str
    manual_pipeline: ManualPipelineSpec | None = None
    automated_jobs: list[AutomatedJobSpec] = field(default_factory=list)
    environments: list[InputOption] = field(default_factory=list)
    scenarios: list[InputOption] = field(default_factory=list)
