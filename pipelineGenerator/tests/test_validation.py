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
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"
    config["tool"]["connection"] = {"test_plan_path": "performance/checkout.jmx"}
    config["catalog"]["environments"] = [{"key": "qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}]

    result = validate_config(config)

    assert not result.errors
    assert any("catalog.environments.qa.identifier is missing." in warning for warning in result.warnings)


def test_validation_does_not_warn_about_optional_wlrun_path() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-loadrunner-setup"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "loadrunner_professional"
    config["tool"]["connection"] = {}
    config["catalog"]["environments"] = [
        {
            "key": "qa",
            "identifier": "QA",
            "scenarios": [{"key": "checkout_smoke", "identifier": "C:\\Scenarios\\checkout_smoke_qa.lrs"}],
        }
    ]

    result = validate_config(config)

    assert not any("wlrun_path" in warning for warning in result.warnings)
    assert not any("controller_host" in warning for warning in result.warnings)


def test_validation_errors_for_unsupported_enum_values() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-setup"
    config["setup"]["generation_mode"] = "not_a_real_mode"
    config["cicd"]["type"] = "not_a_real_cicd_platform"
    config["tool"]["type"] = "not_a_real_tool"

    result = validate_config(config)

    assert "Unsupported cicd.type: not_a_real_cicd_platform" in result.errors
    assert "Unsupported tool.type: not_a_real_tool" in result.errors
    assert "Unsupported setup.generation_mode: not_a_real_mode" in result.errors


def test_validation_errors_when_required_field_missing_on_complete_config() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = ""
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"

    result = validate_config(config)

    assert "setup.id is missing." in result.errors
    assert not any("setup.id is missing." in warning for warning in result.warnings)


def _complete_jmeter_config() -> dict:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-setup"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"
    config["tool"]["connection"] = {"test_plan_path": "performance/checkout.jmx"}
    config["catalog"]["environments"] = [
        {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
    ]
    config["load_profile"] = {
        "test_type": "load",
        "users": 10,
        "ramp_up_seconds": 30,
        "duration_minutes": 5,
        "throughput_rps": 0,
    }
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
        {"key": "qa", "identifier": "env-qa-east", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]},
        {"key": "qa", "identifier": "env-qa-west", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-2"}]},
    ]

    result = validate_config(config)

    assert not result.errors
    assert any("duplicate" in warning.lower() and "qa" in warning for warning in result.warnings)


def test_validation_warns_about_duplicate_scenario_key_within_same_environment() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"][0]["scenarios"] = [
        {"key": "checkout_smoke", "identifier": "SC-1"},
        {"key": "checkout_smoke", "identifier": "SC-2"},
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


def test_validation_errors_instead_of_crashing_on_environments_as_list_of_strings() -> None:
    config = base_config()
    config["catalog"]["environments"] = ["qa", "staging"]

    result = validate_config(config)

    assert any("catalog.environments" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_scenarios_as_dict() -> None:
    config = base_config()
    config["catalog"]["environments"] = [{"key": "qa", "identifier": "QA", "scenarios": {"key": "checkout_smoke"}}]

    result = validate_config(config)

    assert any("catalog.environments.qa.scenarios" in error for error in result.errors)


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



def test_validation_warns_about_todo_load_value_for_jmeter() -> None:
    config = _complete_jmeter_config()
    config["load_profile"]["users"] = "TODO"

    result = validate_config(config)

    assert "load_profile.users is missing." in result.warnings


def test_validation_ignores_load_profile_for_loadrunner() -> None:
    config = _complete_jmeter_config()
    config["tool"] = {"type": "loadrunner_professional", "connection": {}}
    config["load_profile"] = {"test_type": "load"}

    result = validate_config(config)

    assert not any("load_profile" in message for message in result.warnings + result.errors)


def test_validation_errors_on_out_of_range_load_values() -> None:
    for bad in (0, "ten", True, -5):
        config = _complete_jmeter_config()
        config["load_profile"]["users"] = bad

        result = validate_config(config)

        assert any("load_profile.users" in error for error in result.errors), bad


def test_validation_accepts_zero_throughput_and_ramp_up() -> None:
    config = _complete_jmeter_config()
    config["load_profile"]["throughput_rps"] = 0
    config["load_profile"]["ramp_up_seconds"] = 0

    result = validate_config(config)

    assert not any("load_profile" in message for message in result.warnings + result.errors)


def test_validation_does_not_require_test_type() -> None:
    config = _complete_jmeter_config()
    del config["load_profile"]["test_type"]

    result = validate_config(config)

    assert not any("test_type" in message for message in result.warnings + result.errors)


def test_validation_warns_when_timeout_is_shorter_than_test() -> None:
    config = _complete_jmeter_config()
    config["load_profile"]["ramp_up_seconds"] = 60
    config["load_profile"]["duration_minutes"] = 5
    config["manual_pipeline"]["timeout_minutes"] = 5

    result = validate_config(config)

    assert any("manual_pipeline timeout" in warning for warning in result.warnings)


def test_validation_does_not_warn_when_timeout_covers_test() -> None:
    config = _complete_jmeter_config()
    config["load_profile"]["ramp_up_seconds"] = 60
    config["load_profile"]["duration_minutes"] = 5
    config["manual_pipeline"]["timeout_minutes"] = 10

    result = validate_config(config)

    assert not any("timeout" in warning for warning in result.warnings)


def test_validation_warns_when_automated_job_timeout_is_shorter_than_test() -> None:
    config = _complete_jmeter_config()
    config["automated_jobs"] = [
        {"name": "nightly", "environment_ref": "qa", "scenario_ref": "checkout_smoke", "timeout_minutes": 3}
    ]

    result = validate_config(config)

    assert any("automated job 'nightly' timeout" in warning for warning in result.warnings)


def test_validation_errors_on_multiline_or_non_string_test_type() -> None:
    for bad in ("load\nstress", "x" * 65, ["load"], "it's"):
        config = _complete_jmeter_config()
        config["load_profile"]["test_type"] = bad

        result = validate_config(config)

        assert any("load_profile.test_type" in error for error in result.errors), bad


def test_validation_accepts_simple_test_type_label() -> None:
    config = _complete_jmeter_config()
    config["load_profile"]["test_type"] = "soak test-2.1"

    result = validate_config(config)

    assert not any("test_type" in message for message in result.errors + result.warnings)


def test_validation_does_not_warn_about_same_scenario_key_reused_across_environments() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"].append(
        {"key": "staging", "identifier": "env-staging", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-2"}]}
    )

    result = validate_config(config)

    assert not any("duplicate" in warning.lower() for warning in result.warnings)


def test_validation_warns_about_environment_with_no_scenarios() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"].append({"key": "staging", "identifier": "env-staging", "scenarios": []})

    result = validate_config(config)

    assert any("catalog.environments.staging.scenarios is missing" in warning for warning in result.warnings)


def test_validation_warns_about_missing_scenario_identifier_with_nested_path() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"][0]["scenarios"] = [{"key": "checkout_smoke"}]

    result = validate_config(config)

    assert "catalog.environments.qa.scenarios.checkout_smoke.identifier is missing." in result.warnings


def test_validation_warns_about_automated_job_scenario_from_another_environment() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"].append(
        {"key": "staging", "identifier": "env-staging", "scenarios": [{"key": "browse_baseline", "identifier": "SC-9"}]}
    )
    config["automated_jobs"] = [
        {"name": "nightly", "environment_ref": "staging", "scenario_ref": "checkout_smoke", "enabled": True}
    ]

    result = validate_config(config)

    assert any(
        "nightly" in warning and "unknown scenario for environment 'staging'" in warning
        for warning in result.warnings
    )


def test_validation_errors_on_catalog_key_with_unsupported_characters() -> None:
    for bad in ("qa: east", "../x", "east us", "-qa"):
        config = _complete_jmeter_config()
        config["catalog"]["environments"][0]["key"] = bad

        result = validate_config(config)

        assert any("catalog.environments" in error and "key" in error for error in result.errors), bad

    config = _complete_jmeter_config()
    config["catalog"]["environments"][0]["scenarios"][0]["key"] = "smoke: 1"
    assert any("scenarios" in error and "key" in error for error in validate_config(config).errors)


def test_validation_accepts_simple_catalog_keys() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"][0]["key"] = "qa-east.1"
    config["catalog"]["environments"][0]["scenarios"][0]["key"] = "Checkout_Smoke"

    result = validate_config(config)

    assert not result.errors


def test_validation_errors_on_non_string_catalog_key() -> None:
    # YAML reads `key: 1` / `key: yes` as int/bool; they'd crash generate later.
    for bad in (1, 2025, True):
        config = _complete_jmeter_config()
        config["catalog"]["environments"][0]["scenarios"][0]["key"] = bad

        result = validate_config(config)

        assert any("must be a string" in error for error in result.errors), bad


def test_validation_errors_on_missing_catalog_key() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"][0]["scenarios"] = [{"identifier": "SC-1"}]
    config["incomplete"] = True

    result = validate_config(config)

    assert any("catalog.environments.qa.scenarios" in error and "key" in error for error in result.errors)


def test_validation_errors_on_legacy_flat_scenarios_list() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["scenarios"] = [{"key": "checkout_smoke", "identifier": "SC-1"}]

    result = validate_config(config)

    assert any("catalog.scenarios is no longer supported" in error for error in result.errors)


def test_validation_duplicate_environment_warning_says_to_merge() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"].append(
        {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "browse", "identifier": "SC-2"}]}
    )

    result = validate_config(config)

    warning = next(w for w in result.warnings if "duplicate" in w.lower())
    assert "merge" in warning
    assert "only the first is ever reachable" not in warning


def test_validation_warns_when_loadrunner_has_no_runner() -> None:
    config = _complete_jmeter_config()
    config["tool"] = {"type": "loadrunner_professional", "connection": {}}
    config["cicd"]["runner"] = ""

    result = validate_config(config)

    assert any(w.startswith("cicd.runner is missing") for w in result.warnings)


def test_validation_does_not_require_runner_for_jmeter() -> None:
    config = _complete_jmeter_config()
    config["cicd"]["runner"] = ""

    assert not any("cicd.runner" in w for w in validate_config(config).warnings)


def test_validation_warns_about_todo_runner_for_any_tool() -> None:
    config = _complete_jmeter_config()
    config["cicd"]["runner"] = "TODO"

    assert any(w.startswith("cicd.runner is missing") for w in validate_config(config).warnings)


def test_validation_accepts_runner_label_list_and_rejects_other_types() -> None:
    config = _complete_jmeter_config()
    config["cicd"]["runner"] = ["self-hosted", "windows"]
    assert not any("cicd.runner" in e for e in validate_config(config).errors)

    for bad in ({"label": "x"}, 123, ["ok", 5]):
        config["cicd"]["runner"] = bad
        assert any("cicd.runner" in e for e in validate_config(config).errors), bad
