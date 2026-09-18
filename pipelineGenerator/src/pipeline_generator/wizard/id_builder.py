from __future__ import annotations

from pipeline_generator.text_utils import slugify


def build_setup_id(cicd_type: str, tool_type: str) -> str:
    parts = [cicd_type, tool_type]
    return slugify("-".join(part for part in parts if part))
