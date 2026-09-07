from pathlib import Path

import yaml

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.azure_devops import render_azure_devops


def _config() -> dict:
    return {
        "setup": {"id": "azure-test-setup", "generation_mode": "both"},
        "cicd": {"type": "azure_devops"},
        "catalog": {
            "environments": [{"key": "qa", "name": "QA"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke"}],
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

    automated_text = automated_path.read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)
    assert automated_doc["jobs"][0]["timeoutInMinutes"] == 60
    # job identifiers get hyphens sanitized to underscores; the --job argument does not.
    assert automated_doc["jobs"][0]["job"] == "post_deploy_smoke"
    assert "--job post-deploy-smoke" in automated_text
