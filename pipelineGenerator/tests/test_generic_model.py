from pipeline_generator.config.placeholders import TODO_VALUE
from pipeline_generator.generator.context import build_generic_package


def _config() -> dict:
    return {
        "setup": {"id": "generic-model-test", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "tool": {"type": "jmeter", "connection": {}},
        "catalog": {
            "environments": [{"key": "qa", "name": "QA", "identifier": "env-qa"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
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
    assert package.environments == [package.environments[0]]
    assert package.environments[0].value == "qa"
    assert package.environments[0].identifier == "env-qa"
    assert package.scenarios[0].identifier == "SC-1"

    job = package.automated_jobs[0]
    assert job.environment_ref == "qa"
    assert job.scenario_ref == "checkout_smoke"


def test_build_generic_package_defaults_missing_identifier_to_todo_placeholder() -> None:
    config = _config()
    del config["catalog"]["environments"][0]["identifier"]

    package = build_generic_package(config)

    assert package.environments[0].identifier == TODO_VALUE


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
