from pathlib import Path

import pytest

from pipeline_generator.config.schema import merged_base_config
from pipeline_generator.wizard.flow import _is_incomplete, _step_cicd_and_tool, _step_load_profile, run_wizard


def test_run_wizard_full_flow_produces_expected_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_path = tmp_path / "draft.yaml"
    responses = iter(
        [
            "",  # generation mode -> default both
            "",  # cicd platform -> default github_actions
            "3",  # performance tool -> jmeter
            "performance/checkout.jmx",  # jmeter test plan path
            "",  # docker image -> blank (uses default)
            "",  # test type label -> default load
            "20",  # users
            "60",  # ramp-up seconds
            "10",  # duration minutes
            "0",  # throughput rps (no cap)
            "",  # manual pipeline name -> default
            "",  # manual pipeline timeout -> default 240
            "y",  # add environments now?
            "qa",  # environment key
            "env-qa",  # environment identifier
            "",  # blank key ends environment collection
            "y",  # add scenarios now?
            "checkout_smoke",  # scenario key
            "SC-1",  # scenario identifier
            "",  # blank key ends scenario collection
            "y",  # add automated jobs now?
            "nightly-load",  # automated job name
            "",  # environment ref -> default qa
            "",  # scenario ref -> default checkout_smoke
            "",  # timeout -> default 240
            "",  # blank name ends automated job collection
            "1",  # pre-run checks -> select option 1 (verify_scenario_exists)
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *_: next(responses))

    config = run_wizard(output_path, resume=False)

    assert config["setup"]["generation_mode"] == "both"
    assert config["setup"]["id"].startswith("github-actions-jmeter-")
    assert len(config["setup"]["id"]) == len("github-actions-jmeter-") + 6
    assert config["cicd"]["type"] == "github_actions"
    assert config["tool"]["type"] == "jmeter"
    assert config["tool"]["connection"] == {"test_plan_path": "performance/checkout.jmx", "docker_image": ""}
    assert config["manual_pipeline"] == {
        "enabled": True,
        "name": "Performance Manual Run",
        "timeout_minutes": 240,
    }
    assert config["catalog"]["environments"] == [{"key": "qa", "identifier": "env-qa"}]
    assert config["catalog"]["scenarios"] == [{"key": "checkout_smoke", "identifier": "SC-1"}]
    assert config["automated_jobs"] == [
        {
            "name": "nightly-load",
            "enabled": True,
            "environment_ref": "qa",
            "scenario_ref": "checkout_smoke",
            "timeout_minutes": 240,
        }
    ]
    assert config["load_profile"] == {
        "test_type": "load",
        "users": 20,
        "ramp_up_seconds": 60,
        "duration_minutes": 10,
        "throughput_rps": 0,
    }
    assert config["pre_run_checks"] == ["verify_scenario_exists"]
    assert config["readme"]["include_manual_usage"] is True
    assert config["readme"]["include_automated_usage"] is True
    assert config["incomplete"] is False

    assert output_path.exists()


def test_step_cicd_and_tool_preserves_existing_setup_id_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = merged_base_config(None)
    config["setup"]["id"] = "already-assigned-id"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"
    responses = iter(["", "2"])  # cicd -> keep default, tool -> switch to blazemeter
    monkeypatch.setattr("builtins.input", lambda *_: next(responses))

    _step_cicd_and_tool(config, tmp_path / "draft.yaml")

    assert config["tool"]["type"] == "blazemeter"
    assert config["setup"]["id"] == "already-assigned-id"


def _jmeter_config() -> dict:
    config = merged_base_config(None)
    config["tool"]["type"] = "jmeter"
    return config


def test_step_load_profile_asks_all_values_for_jmeter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _jmeter_config()
    responses = iter(["soak", "50", "todo", "-1", "abc", "30", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(responses))

    _step_load_profile(config, tmp_path / "draft.yaml")

    assert config["load_profile"] == {
        "test_type": "soak",
        "users": 50,
        "ramp_up_seconds": "TODO",
        "duration_minutes": 30,  # "-1" and "abc" were re-asked
        "throughput_rps": "TODO",  # blank keeps the TODO default
    }


def test_step_load_profile_asks_only_test_type_for_loadrunner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = merged_base_config(None)
    config["tool"]["type"] = "loadrunner_professional"
    responses = iter(["stress"])
    monkeypatch.setattr("builtins.input", lambda *_: next(responses))

    _step_load_profile(config, tmp_path / "draft.yaml")

    assert config["load_profile"]["test_type"] == "stress"
    assert config["load_profile"]["users"] == "TODO"  # untouched, never asked


def test_step_load_profile_resume_keeps_existing_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _jmeter_config()
    config["load_profile"].update({"test_type": "spike", "users": 5, "ramp_up_seconds": 0,
                                   "duration_minutes": 2, "throughput_rps": 9})
    responses = iter(["", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(responses))

    _step_load_profile(config, tmp_path / "draft.yaml")

    assert config["load_profile"] == {"test_type": "spike", "users": 5, "ramp_up_seconds": 0,
                                      "duration_minutes": 2, "throughput_rps": 9}


def test_config_with_todo_load_value_stays_incomplete() -> None:
    config = _jmeter_config()
    config["setup"]["id"] = "some-setup"
    config["cicd"]["type"] = "github_actions"

    assert _is_incomplete(config) is True


def test_config_with_non_todo_warning_is_not_marked_incomplete() -> None:
    # A real misconfiguration (timeout shorter than the test) must keep blocking
    # `generate` -- only missing/TODO values make a config a draft.
    config = _jmeter_config()
    config["setup"]["id"] = "some-setup"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["connection"] = {"test_plan_path": "plan.jmx", "docker_image": ""}
    config["catalog"]["environments"] = [{"key": "qa", "identifier": "env-qa"}]
    config["catalog"]["scenarios"] = [{"key": "checkout_smoke", "identifier": "SC-1"}]
    config["load_profile"].update({"users": 10, "ramp_up_seconds": 0, "duration_minutes": 60, "throughput_rps": 0})
    config["manual_pipeline"]["timeout_minutes"] = 30

    assert _is_incomplete(config) is False
