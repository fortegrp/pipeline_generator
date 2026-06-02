from __future__ import annotations

import re


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-") or "setup"


def build_setup_id(cicd_type: str, tool_type: str, target_repository: str) -> str:
    repo_name = target_repository.rstrip("/").split("/")[-1] if target_repository else "repo"
    parts = [cicd_type, tool_type, repo_name]
    return slugify("-".join(part for part in parts if part))

