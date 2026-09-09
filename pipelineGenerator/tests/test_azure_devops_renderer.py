import re
from pathlib import Path

import yaml

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.azure_devops import render_azure_devops
from pipeline_generator.renderers.quoting import shell_quote


def _config() -> dict:
    return {
        "setup": {"id": "azure-test-setup", "generation_mode": "both"},
        "cicd": {"type": "azure_devops"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "jmeter_bin": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": "qa", "name": "QA", "identifier": "env-qa"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 120},
        "automated_jobs": [
            {
                "name": "post-deploy-smoke",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 60,
            }
        ],
    }


def test_render_azure_devops_writes_valid_pipelines(tmp_path: Path) -> None:
    config = _config()
    package = build_generic_package(config)

    outputs = render_azure_devops(config, package, tmp_path)

    manual_path = tmp_path / "azure" / "performance-manual.yml"
    automated_path = tmp_path / "azure" / "performance-automated-post-deploy-smoke.yml"
    assert str(manual_path) in outputs
    assert str(automated_path) in outputs

    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)
    assert manual_doc["jobs"][0]["timeoutInMinutes"] == 120
    assert manual_doc["parameters"][0]["name"] == "environment"
    assert "qa" in manual_text
    # The parameter value must be delivered via env:, never spliced directly
    # into the script: text.
    run_step = manual_doc["jobs"][0]["steps"][1]
    assert run_step["env"] == {
        "ENVIRONMENT": "${{ parameters.environment }}",
        "SCENARIO": "${{ parameters.scenario }}",
    }
    assert "./scripts/run-jmeter.sh" in manual_text
    assert '--environment "$ENVIRONMENT"' in manual_text
    assert '--scenario "$SCENARIO"' in manual_text
    assert "parameters.environment" not in run_step["script"]
    assert "pipeline-generator" not in manual_text

    automated_text = automated_path.read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)
    assert automated_doc["jobs"][0]["timeoutInMinutes"] == 60
    # job identifiers get hyphens sanitized to underscores.
    assert automated_doc["jobs"][0]["job"] == "post_deploy_smoke"
    assert "./scripts/run-jmeter.sh" in automated_text
    assert "--environment qa" in automated_text
    assert "--scenario checkout_smoke" in automated_text
    assert "pipeline-generator" not in automated_text


def test_render_azure_devops_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = 'qa" evil: true'
    nasty_job_name = 'weird "job"; rm -rf / : ../../etc'
    config = {
        "setup": {"id": "azure-adversarial", "generation_mode": "both"},
        "cicd": {"type": "azure_devops"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "jmeter_bin": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": nasty_env_value, "name": "QA", "identifier": "env-nasty"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 30},
        "automated_jobs": [
            {
                "name": nasty_job_name,
                "enabled": True,
                "environment_ref": nasty_env_value,
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 15,
            }
        ],
    }
    package = build_generic_package(config)

    outputs = render_azure_devops(config, package, tmp_path)

    for output in outputs:
        filename = Path(output).name
        assert "/" not in filename
        assert ".." not in filename
        assert " " not in filename

    manual_path = tmp_path / "azure" / "performance-manual.yml"
    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)  # raises if the escaping broke YAML syntax
    environment_param = next(p for p in manual_doc["parameters"] if p["name"] == "environment")
    assert nasty_env_value in environment_param["values"]

    azure_dir = tmp_path / "azure"
    automated_files = [p for p in azure_dir.iterdir() if p.name.startswith("performance-automated-")]
    assert len(automated_files) == 1
    automated_text = automated_files[0].read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)  # raises if the escaping broke YAML syntax

    job_id = automated_doc["jobs"][0]["job"]
    assert re.match(r"^[A-Za-z0-9_]+$", job_id)
    assert not job_id[0].isdigit()
    assert shell_quote(nasty_env_value) in automated_text


def test_render_azure_devops_includes_timeout_flag_for_blazemeter(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {
        "type": "blazemeter",
        "connection": {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    }
    package = build_generic_package(config)

    render_azure_devops(config, package, tmp_path)

    manual_text = (tmp_path / "azure" / "performance-manual.yml").read_text(encoding="utf-8")
    automated_text = (tmp_path / "azure" / "performance-automated-post-deploy-smoke.yml").read_text(encoding="utf-8")

    assert "--timeout-minutes 120" in manual_text
    assert "--timeout-minutes 60" in automated_text
