from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InputOption:
    value: str
    display_name: str


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
    run_command: list[str]


@dataclass
class AutomatedJobSpec:
    name: str
    timeout_minutes: int
    fixed_arguments: dict[str, str]
    run_command: list[str]


@dataclass
class GenericPipelinePackage:
    setup_id: str
    cicd_type: str
    manual_pipeline: ManualPipelineSpec | None = None
    automated_jobs: list[AutomatedJobSpec] = field(default_factory=list)

