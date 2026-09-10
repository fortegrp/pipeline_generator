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


def test_validation_does_not_warn_about_optional_wlrun_path() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-loadrunner-setup"
    config["setup"]["target_repository"] = "https://example.com/repo.git"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "loadrunner_professional"
    config["tool"]["auth"]["type"] = "none"
    config["tool"]["connection"] = {}
    config["catalog"]["environments"] = [{"key": "qa", "name": "QA", "identifier": "QA"}]
    config["catalog"]["scenarios"] = [
        {
            "key": "checkout_smoke_qa",
            "name": "Checkout Smoke (QA)",
            "identifier": "C:\\Scenarios\\checkout_smoke_qa.lrs",
        }
    ]

    result = validate_config(config)

    assert not any("wlrun_path" in warning for warning in result.warnings)
    assert not any("controller_host" in warning for warning in result.warnings)


def test_validation_errors_for_unsupported_enum_values() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-setup"
    config["setup"]["target_repository"] = "https://example.com/repo.git"
    config["setup"]["generation_mode"] = "not_a_real_mode"
    config["cicd"]["type"] = "not_a_real_cicd_platform"
    config["tool"]["type"] = "not_a_real_tool"
    config["tool"]["auth"]["type"] = "not_a_real_auth_type"

    result = validate_config(config)

    assert "Unsupported cicd.type: not_a_real_cicd_platform" in result.errors
    assert "Unsupported tool.type: not_a_real_tool" in result.errors
    assert "Unsupported tool.auth.type: not_a_real_auth_type" in result.errors
    assert "Unsupported setup.generation_mode: not_a_real_mode" in result.errors


def test_validation_errors_when_required_field_missing_on_complete_config() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = ""
    config["setup"]["target_repository"] = "https://example.com/repo.git"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"
    config["tool"]["auth"]["type"] = "none"

    result = validate_config(config)

    assert "setup.id is missing." in result.errors
    assert not any("setup.id is missing." in warning for warning in result.warnings)

