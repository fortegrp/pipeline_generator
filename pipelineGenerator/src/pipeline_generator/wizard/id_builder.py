from __future__ import annotations

import secrets

from pipeline_generator.text_utils import slugify


def build_setup_id(cicd_type: str, tool_type: str) -> str:
    parts = [cicd_type, tool_type]
    return slugify("-".join(part for part in parts if part))


def generate_unique_setup_id(cicd_type: str, tool_type: str) -> str:
    """Build a setup id with a short random suffix.

    Two setups sharing the same cicd_type/tool_type would otherwise
    suggest identical ids and silently overwrite each other's generated
    output folder -- the suffix keeps them apart without asking the user
    anything.
    """
    return f"{build_setup_id(cicd_type, tool_type)}-{secrets.token_hex(3)}"
