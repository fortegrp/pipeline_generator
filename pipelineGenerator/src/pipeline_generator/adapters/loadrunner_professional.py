from __future__ import annotations

from pathlib import Path

from pipeline_generator.adapters.base import BaseAdapter


class LoadRunnerProfessionalAdapter(BaseAdapter):
    def __init__(self) -> None:
        super().__init__(name="loadrunner_professional")

    def start_run(self, config: dict, request: dict) -> dict:
        raise NotImplementedError(
            "LoadRunner Professional adapter scaffolded but not implemented yet. Add remote Windows execution in start_run()."
        )

    def wait_for_completion(self, config: dict, handle: dict, timeout_minutes: int) -> dict:
        raise NotImplementedError(
            "LoadRunner Professional adapter scaffolded but not implemented yet. Add polling and completion logic in wait_for_completion()."
        )

    def collect_artifacts(self, config: dict, result: dict, output_dir: Path) -> dict:
        raise NotImplementedError(
            "LoadRunner Professional adapter scaffolded but not implemented yet. Add artifact collection in collect_artifacts()."
        )

