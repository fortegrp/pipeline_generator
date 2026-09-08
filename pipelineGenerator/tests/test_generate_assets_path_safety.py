from pathlib import Path

from pipeline_generator.config.schema import merged_base_config
from pipeline_generator.generator.service import generate_assets


def _config(setup_id: str) -> dict:
    config = merged_base_config(None)
    config["setup"]["id"] = setup_id
    config["setup"]["target_repository"] = "github.com/acme/storefront"
    config["setup"]["generation_mode"] = "manual_only"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "loadrunner_professional"
    config["tool"]["auth"]["type"] = "username_password"
    return config


def test_generate_assets_confines_relative_traversal_to_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"
    outputs = generate_assets(_config("../../evil"), output_dir)

    for output in outputs:
        assert Path(output).resolve().is_relative_to(output_dir.resolve())


def test_generate_assets_ignores_absolute_setup_id(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"
    hostile_target = tmp_path / "outside"
    outputs = generate_assets(_config(str(hostile_target)), output_dir)

    assert not hostile_target.exists()
    for output in outputs:
        assert Path(output).resolve().is_relative_to(output_dir.resolve())
