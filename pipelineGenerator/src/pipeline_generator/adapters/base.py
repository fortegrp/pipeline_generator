from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pipeline_generator.runtime.prechecks import CheckResult


class ToolAdapter(Protocol):
    name: str

    def run_prechecks(self, config: dict, request: dict) -> list[CheckResult]:
        ...

    def start_run(self, config: dict, request: dict) -> dict:
        ...

    def wait_for_completion(self, config: dict, handle: dict, timeout_minutes: int) -> dict:
        ...

    def collect_artifacts(self, config: dict, result: dict, output_dir: Path) -> dict:
        ...


@dataclass
class BaseAdapter:
    name: str

    def run_prechecks(self, config: dict, request: dict) -> list[CheckResult]:
        checks = []
        for item in config.get("pre_run_checks", []):
            checks.append(CheckResult(name=item, status="planned", message="Check stubbed in scaffold."))
        return checks

    def start_run(self, config: dict, request: dict) -> dict:
        raise NotImplementedError("Real remote execution is not implemented yet.")

    def wait_for_completion(self, config: dict, handle: dict, timeout_minutes: int) -> dict:
        raise NotImplementedError("Real remote execution is not implemented yet.")

    def collect_artifacts(self, config: dict, result: dict, output_dir: Path) -> dict:
        raise NotImplementedError("Real remote execution is not implemented yet.")


def get_adapter(tool_type: str) -> ToolAdapter:
    if tool_type == "blazemeter":
        from pipeline_generator.adapters.blazemeter import BlazeMeterAdapter

        return BlazeMeterAdapter()
    if tool_type == "loadrunner_professional":
        from pipeline_generator.adapters.loadrunner_professional import LoadRunnerProfessionalAdapter

        return LoadRunnerProfessionalAdapter()
    if tool_type == "jmeter":
        from pipeline_generator.adapters.jmeter import JMeterAdapter

        return JMeterAdapter()
    raise ValueError(f"Unsupported adapter: {tool_type}")

