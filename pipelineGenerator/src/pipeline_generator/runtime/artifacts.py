from __future__ import annotations

import json
from pathlib import Path


def ensure_output_dir(path: Path | None = None) -> Path:
    output_dir = path or Path("run-output")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

