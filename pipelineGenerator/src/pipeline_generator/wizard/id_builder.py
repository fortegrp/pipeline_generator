from __future__ import annotations

from pipeline_generator.text_utils import slugify


def build_setup_id(cicd_type: str, tool_type: str, target_repository: str) -> str:
    repo_name = target_repository.rstrip("/").split("/")[-1] if target_repository else "repo"
    parts = [cicd_type, tool_type, repo_name]
    return slugify("-".join(part for part in parts if part))
