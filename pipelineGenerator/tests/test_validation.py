from pipeline_generator.config.schema import base_config
from pipeline_generator.config.validator import validate_config


def test_validation_warns_for_incomplete_base_config() -> None:
    result = validate_config(base_config())
    assert not result.errors
    assert result.warnings


def test_validation_warns_when_catalog_identifier_is_missing() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-setup"
    config["setup"]["target_repository"] = "https://example.com/repo.git"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"
    config["tool"]["auth"]["type"] = "none"
    config["tool"]["connection"] = {"test_plan_path": "performance/checkout.jmx"}
    config["catalog"]["environments"] = [{"key": "qa", "name": "QA"}]
    config["catalog"]["scenarios"] = [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}]

    result = validate_config(config)

    assert not result.errors
    assert any("catalog.environments.qa.identifier is missing." in warning for warning in result.warnings)

