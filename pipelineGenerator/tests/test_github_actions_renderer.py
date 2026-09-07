from pathlib import Path

import yaml

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.github_actions import render_github_actions


def _config() -> dict:
    return {
        "setup": {"id": "gha-test-setup", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
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


def test_render_github_actions_writes_valid_workflows(tmp_path: Path) -> None:
    config = _config()
    package = build_generic_package(config)

    outputs = render_github_actions(config, package, tmp_path)

    manual_path = tmp_path / ".github" / "workflows" / "performance-manual.yml"
    automated_path = tmp_path / ".github" / "workflows" / "performance-automated-post-deploy-smoke.yml"
    assert str(manual_path) in outputs
    assert str(automated_path) in outputs

    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)
    assert manual_doc["name"] == "Performance Manual Run"
    assert manual_doc["jobs"]["run-performance-test"]["timeout-minutes"] == 120
    assert '"qa"' in manual_text
    assert '"checkout_smoke"' in manual_text

    automated_text = automated_path.read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)
    assert automated_doc["jobs"]["post-deploy-smoke"]["timeout-minutes"] == 60
    assert "--mode automated" in automated_text
    assert '--job "post-deploy-smoke"' in automated_text
