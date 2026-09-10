from pathlib import Path

from pipeline_generator.config.schema import merged_base_config
from pipeline_generator.generator.service import generate_assets


def _config(tool_type: str, connection: dict) -> dict:
    config = merged_base_config(None)
    config["setup"]["id"] = "regen-setup"
    config["setup"]["target_repository"] = "github.com/acme/storefront"
    config["setup"]["generation_mode"] = "manual_only"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = tool_type
    config["tool"]["auth"]["type"] = "none"
    config["tool"]["connection"] = connection
    return config


def test_regenerating_after_switching_tool_type_removes_stale_script(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"

    generate_assets(_config("loadrunner_professional", {"wlrun_path": "wlrun"}), output_dir)
    setup_dir = output_dir / "regen-setup"
    assert (setup_dir / "scripts" / "run-loadrunner_professional.sh").exists()

    generate_assets(_config("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": "jmeter"}), output_dir)

    assert (setup_dir / "scripts" / "run-jmeter.sh").exists()
    assert not (setup_dir / "scripts" / "run-loadrunner_professional.sh").exists()


def test_regenerating_after_removing_automated_job_removes_stale_workflow(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"

    config = _config("jmeter", {"test_plan_path": "plan.jmx", "jmeter_bin": "jmeter"})
    config["setup"]["generation_mode"] = "automated_only"
    config["catalog"]["environments"] = [{"key": "qa", "name": "QA", "identifier": "env-qa"}]
    config["catalog"]["scenarios"] = [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}]
    config["automated_jobs"] = [
        {"name": "nightly-load", "environment_ref": "qa", "scenario_ref": "checkout_smoke", "enabled": True}
    ]
    generate_assets(config, output_dir)
    setup_dir = output_dir / "regen-setup"
    workflow_path = setup_dir / ".github" / "workflows" / "performance-automated-nightly-load.yml"
    assert workflow_path.exists()

    config["automated_jobs"] = []
    generate_assets(config, output_dir)

    assert not workflow_path.exists()
