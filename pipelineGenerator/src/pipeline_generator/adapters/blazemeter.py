from __future__ import annotations

from pathlib import Path

from pipeline_generator.adapters.base import BaseAdapter


class BlazeMeterAdapter(BaseAdapter):
    def __init__(self) -> None:
        super().__init__(name="blazemeter")

    def start_run(self, config: dict, request: dict) -> dict:
        raise NotImplementedError(
            "BlazeMeter adapter scaffolded but not implemented yet. Add API calls in start_run()."
        )

    def wait_for_completion(self, config: dict, handle: dict, timeout_minutes: int) -> dict:
        raise NotImplementedError(
            "BlazeMeter adapter scaffolded but not implemented yet. Add polling in wait_for_completion()."
        )

    def collect_artifacts(self, config: dict, result: dict, output_dir: Path) -> dict:
        raise NotImplementedError(
            "BlazeMeter adapter scaffolded but not implemented yet. Add result download in collect_artifacts()."
        )

