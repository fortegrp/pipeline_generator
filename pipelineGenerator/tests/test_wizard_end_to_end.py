from pathlib import Path

import pytest

from pipeline_generator.config.schema import merged_base_config
from pipeline_generator.wizard.flow import _step_cicd_and_tool, run_wizard


def test_run_wizard_full_flow_produces_expected_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_path = tmp_path / "draft.yaml"
    responses = iter(
        [
            "",  # generation mode -> default both
            "",  # cicd platform -> default github_actions
            "3",  # performance tool -> jmeter
            "performance/checkout.jmx",  # jmeter test plan path
            "",  # jmeter bin -> blank (uses PATH)
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
    assert config["tool"]["connection"] == {"test_plan_path": "performance/checkout.jmx", "jmeter_bin": ""}
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
