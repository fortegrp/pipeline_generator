from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class WizardState:
    output_path: Path
    resumed: bool

