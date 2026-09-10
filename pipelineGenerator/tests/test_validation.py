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


def _complete_jmeter_config() -> dict:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-setup"
    config["setup"]["target_repository"] = "https://example.com/repo.git"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"
    config["tool"]["auth"]["type"] = "none"
    config["tool"]["connection"] = {"test_plan_path": "performance/checkout.jmx"}
    config["catalog"]["environments"] = [{"key": "qa", "name": "QA", "identifier": "env-qa"}]
    config["catalog"]["scenarios"] = [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}]
    return config


def test_validation_warns_about_unrecognized_pre_run_check() -> None:
    config = _complete_jmeter_config()
    config["pre_run_checks"] = ["verify_scenario_exist"]

    result = validate_config(config)

    assert not result.errors
    assert any("verify_scenario_exist" in warning for warning in result.warnings)


def test_validation_does_not_warn_about_recognized_pre_run_check() -> None:
    config = _complete_jmeter_config()
    config["pre_run_checks"] = ["verify_scenario_exists"]

    result = validate_config(config)

    assert not any("verify_scenario_exists" in warning for warning in result.warnings)


def test_validation_warns_about_duplicate_environment_key() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"] = [
        {"key": "qa", "name": "QA East", "identifier": "env-qa-east"},
        {"key": "qa", "name": "QA West", "identifier": "env-qa-west"},
    ]

    result = validate_config(config)

    assert not result.errors
    assert any("duplicate" in warning.lower() and "qa" in warning for warning in result.warnings)


def test_validation_warns_about_duplicate_scenario_key() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["scenarios"] = [
        {"key": "checkout_smoke", "name": "Checkout Smoke A", "identifier": "SC-1"},
        {"key": "checkout_smoke", "name": "Checkout Smoke B", "identifier": "SC-2"},
    ]

    result = validate_config(config)

    assert any("duplicate" in warning.lower() and "checkout_smoke" in warning for warning in result.warnings)


def test_validation_does_not_warn_about_unique_catalog_keys() -> None:
    config = _complete_jmeter_config()

    result = validate_config(config)

    assert not any("duplicate" in warning.lower() for warning in result.warnings)


def test_validation_warns_when_nothing_is_enabled() -> None:
    config = _complete_jmeter_config()
    config["manual_pipeline"]["enabled"] = False
    config["automated_jobs"] = []

    result = validate_config(config)

    assert any("no CI/CD pipeline" in warning or "will generate no" in warning for warning in result.warnings)


def test_validation_does_not_warn_when_manual_pipeline_is_enabled() -> None:
    config = _complete_jmeter_config()
    config["manual_pipeline"]["enabled"] = True
    config["automated_jobs"] = []

    result = validate_config(config)

    assert not any("will generate no" in warning for warning in result.warnings)


def test_validation_errors_instead_of_crashing_on_null_section() -> None:
    config = base_config()
    config["manual_pipeline"] = None

    result = validate_config(config)

    assert any("manual_pipeline" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_wrong_type_section() -> None:
    config = base_config()
    config["tool"] = "jmeter"

    result = validate_config(config)

    assert any("tool" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_wrong_type_auth() -> None:
    config = base_config()
    config["tool"]["auth"] = "none"

    result = validate_config(config)

    assert any("tool.auth" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_environments_as_list_of_strings() -> None:
    config = base_config()
    config["catalog"]["environments"] = ["qa", "staging"]

    result = validate_config(config)

    assert any("catalog.environments" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_scenarios_as_dict() -> None:
    config = base_config()
    config["catalog"]["scenarios"] = {"key": "checkout_smoke"}

    result = validate_config(config)

    assert any("catalog.scenarios" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_automated_jobs_as_dict() -> None:
    config = base_config()
    config["automated_jobs"] = {"name": "nightly"}

    result = validate_config(config)

    assert any("automated_jobs" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_automated_job_entry_as_string() -> None:
    config = base_config()
    config["automated_jobs"] = ["nightly"]

    result = validate_config(config)

    assert any("automated_jobs" in error for error in result.errors)


def test_validation_still_works_correctly_alongside_malformed_sections() -> None:
    # A malformed section must not stop the rest of validate_config from
    # running -- other real problems (e.g. an unsupported tool.type) should
    # still be reported in the same pass, not swallowed by an early return.
    config = base_config()
    config["incomplete"] = False
    config["manual_pipeline"] = None
    config["cicd"]["type"] = "not_a_real_platform"

    result = validate_config(config)

    assert any("manual_pipeline" in error for error in result.errors)
    assert "Unsupported cicd.type: not_a_real_platform" in result.errors


def test_validation_does_not_warn_when_an_automated_job_is_enabled() -> None:
    config = _complete_jmeter_config()
    config["manual_pipeline"]["enabled"] = False
    config["automated_jobs"] = [
        {"name": "nightly", "environment_ref": "qa", "scenario_ref": "checkout_smoke", "enabled": True}
    ]

    result = validate_config(config)

    assert not any("will generate no" in warning for warning in result.warnings)

