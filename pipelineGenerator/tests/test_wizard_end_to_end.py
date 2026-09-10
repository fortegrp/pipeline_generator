from pathlib import Path

import pytest

from pipeline_generator.wizard.flow import run_wizard


def test_run_wizard_full_flow_produces_expected_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_path = tmp_path / "draft.yaml"
    responses = iter(
        [
            "",  # working location -> default central_repo
            "",  # final pipeline destination -> default copy_to_customer_repo
            "",  # ci_can_use_central_repo_directly -> default False
            "https://github.com/acme/storefront.git",  # target repository
            "",  # generation mode -> default both
            "",  # cicd platform -> default github_actions
            "3",  # performance tool -> jmeter
            "5",  # auth type -> none
            "",  # setup id -> accept suggested
            "performance/checkout.jmx",  # jmeter test plan path
            "",  # jmeter bin -> blank (uses PATH)
            "",  # generate manual pipeline? -> default True
            "",  # manual pipeline name -> default
            "",  # manual pipeline timeout -> default 240
            "y",  # add environments now?
            "qa",  # environment key
            "QA",  # environment display name
            "env-qa",  # environment identifier
            "",  # blank key ends environment collection
            "y",  # add scenarios now?
            "checkout_smoke",  # scenario key
            "Checkout Smoke",  # scenario display name
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

    assert config["setup"]["working_location"] == "central_repo"
    assert config["setup"]["final_pipeline_destination"] == "copy_to_customer_repo"
    assert config["setup"]["ci_can_use_central_repo_directly"] is False
    assert config["setup"]["target_repository"] == "https://github.com/acme/storefront.git"
    assert config["setup"]["generation_mode"] == "both"
    assert config["setup"]["id"] == "github-actions-jmeter-storefront"
    assert config["cicd"]["type"] == "github_actions"
    assert config["tool"]["type"] == "jmeter"
    assert config["tool"]["auth"]["type"] == "none"
    assert config["tool"]["connection"] == {"test_plan_path": "performance/checkout.jmx", "jmeter_bin": ""}
    assert config["manual_pipeline"] == {
        "enabled": True,
        "name": "Performance Manual Run",
        "timeout_minutes": 240,
    }
    assert config["catalog"]["environments"] == [{"key": "qa", "name": "QA", "identifier": "env-qa"}]
    assert config["catalog"]["scenarios"] == [
        {"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}
    ]
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
