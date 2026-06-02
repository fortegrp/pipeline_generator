from pipeline_generator.config.schema import base_config
from pipeline_generator.config.validator import validate_config


def test_validation_warns_for_incomplete_base_config() -> None:
    result = validate_config(base_config())
    assert not result.errors
    assert result.warnings

