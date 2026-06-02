from __future__ import annotations

from pathlib import Path

from pipeline_generator.config.schema import merged_base_config


def _get_yaml_module():
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise SystemExit(
            "PyYAML is required for YAML config handling. Install project dependencies first, for example: pip install -e ."
        ) from exc
    return yaml


def load_config(path: Path) -> dict:
    yaml = _get_yaml_module()
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return merged_base_config(data)


def save_config(path: Path, config: dict) -> None:
    yaml = _get_yaml_module()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=False)
