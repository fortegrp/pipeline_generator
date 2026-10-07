from pipeline_generator.config.placeholders import TODO_VALUE
from pipeline_generator.generator.context import build_generic_package


def _config() -> dict:
    return {
        "setup": {"id": "generic-model-test", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "tool": {"type": "jmeter", "connection": {}},
        "catalog": {
            "environments": [
                {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
            ],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 60},
        "automated_jobs": [
            {
                "name": "nightly",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 45,
            }
        ],
    }


def test_build_generic_package_carries_identifiers_and_tool_type() -> None:
    package = build_generic_package(_config())

    assert package.tool_type == "jmeter"
    assert len(package.run_targets) == 1
    target = package.run_targets[0]
    assert (target.environment_key, target.environment_identifier) == ("qa", "env-qa")
    assert (target.scenario_key, target.scenario_identifier) == ("checkout_smoke", "SC-1")
    assert target.selector == "qa: checkout_smoke"

    assert package.automated_jobs[0].test_case == "qa: checkout_smoke"


def test_build_generic_package_defaults_missing_identifier_to_todo_placeholder() -> None:
    config = _config()
    del config["catalog"]["environments"][0]["identifier"]

    package = build_generic_package(config)

    assert package.run_targets[0].environment_identifier == TODO_VALUE


def test_build_generic_package_builds_load_inputs_for_jmeter() -> None:
    config = _config()
    config["load_profile"] = {
        "test_type": "soak",
        "users": 20,
        "ramp_up_seconds": 60,
        "duration_minutes": 10,
        "throughput_rps": 0,
    }

    package = build_generic_package(config)

    assert [(item.name, item.default) for item in package.load_inputs] == [
        ("test_type", "soak"),
        ("users", "20"),
        ("ramp_up_seconds", "60"),
        ("duration_minutes", "10"),
        ("throughput_rps", "0"),
    ]


def test_build_generic_package_only_has_test_type_for_loadrunner() -> None:
    config = _config()
    config["tool"] = {"type": "loadrunner_professional", "connection": {}}
    config["load_profile"] = {"test_type": "load", "users": 20}

    package = build_generic_package(config)

    assert [item.name for item in package.load_inputs] == ["test_type"]


def test_build_generic_package_defaults_missing_load_values_to_todo() -> None:
    package = build_generic_package(_config())

    defaults = {item.name: item.default for item in package.load_inputs}
    assert defaults["users"] == TODO_VALUE
    assert defaults["test_type"] == ""


def test_load_input_flag_and_env_var() -> None:
    package = build_generic_package(_config())

    ramp_up = next(item for item in package.load_inputs if item.name == "ramp_up_seconds")
    assert ramp_up.flag == "--ramp-up-seconds"
    assert ramp_up.env_var == "RAMP_UP_SECONDS"


def test_build_generic_package_builds_one_target_per_defined_pair_in_catalog_order() -> None:
    config = _config()
    config["catalog"]["environments"] = [
        {
            "key": "qa",
            "identifier": "env-qa",
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}, {"key": "browse", "identifier": "SC-2"}],
        },
        {"key": "staging", "identifier": "env-stg", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-3"}]},
    ]

    package = build_generic_package(config)

    assert [t.selector for t in package.run_targets] == ["qa: checkout_smoke", "qa: browse", "staging: checkout_smoke"]
    assert package.run_targets[2].scenario_identifier == "SC-3"
