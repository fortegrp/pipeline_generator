from __future__ import annotations

from pathlib import Path

from pipeline_generator.adapters.base import BaseAdapter


class JMeterAdapter(BaseAdapter):
    def __init__(self) -> None:
        super().__init__(name="jmeter")

    def start_run(self, config: dict, request: dict) -> dict:
        raise NotImplementedError(
            "JMeter adapter scaffolded but not implemented yet. "
            "Add a local jmeter subprocess invocation in start_run()."
        )

    def wait_for_completion(self, config: dict, handle: dict, timeout_minutes: int) -> dict:
        raise NotImplementedError(
            "JMeter adapter scaffolded but not implemented yet. "
            "Add subprocess completion handling in wait_for_completion()."
        )

    def collect_artifacts(self, config: dict, result: dict, output_dir: Path) -> dict:
        raise NotImplementedError(
            "JMeter adapter scaffolded but not implemented yet. "
            "Add local .jtl/report collection in collect_artifacts()."
        )
