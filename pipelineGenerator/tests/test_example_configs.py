from pathlib import Path

import pytest

from pipeline_generator.config.loader import load_config
from pipeline_generator.config.validator import validate_config
from pipeline_generator.generator.service import generate_assets

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
EXAMPLE_CONFIGS = sorted(EXAMPLES_DIR.glob("*/customer.yaml"))


@pytest.mark.parametrize("config_path", EXAMPLE_CONFIGS, ids=lambda path: path.parent.name)
def test_example_config_validates_and_generates(config_path: Path, tmp_path: Path) -> None:
    config = load_config(config_path)
    result = validate_config(config)
    assert not result.errors, f"{config_path} has errors: {result.errors}"
    assert not result.warnings, f"{config_path} has warnings: {result.warnings}"

    outputs = generate_assets(config, tmp_path)
    assert outputs
    for output in outputs:
        assert Path(output).exists()
    assert any("scripts" in Path(output).parts for output in outputs)
