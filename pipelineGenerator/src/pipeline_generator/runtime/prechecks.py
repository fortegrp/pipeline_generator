from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    status: str
    message: str

