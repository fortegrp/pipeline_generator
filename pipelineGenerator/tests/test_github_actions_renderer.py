import re
from pathlib import Path

import yaml

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.github_actions import render_github_actions
from pipeline_generator.renderers.quoting import shell_quote


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
    # The build-triggerer-controlled input must be delivered via env:, never
    # spliced directly into the run: shell text (workflow_dispatch's `choice`
    # restriction is only enforced by GitHub's UI, not its dispatch API).
    step = manual_doc["jobs"]["run-performance-test"]["steps"][3]
    assert step["env"] == {
        "ENVIRONMENT": "${{ github.event.inputs.environment }}",
        "SCENARIO": "${{ github.event.inputs.scenario }}",
    }
    assert '--environment "$ENVIRONMENT"' in manual_text
    assert '--scenario "$SCENARIO"' in manual_text
    assert "github.event.inputs" not in step["run"]

    automated_text = automated_path.read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)
    assert automated_doc["jobs"]["post-deploy-smoke"]["timeout-minutes"] == 60
    assert "--mode automated" in automated_text
    assert "--job post-deploy-smoke" in automated_text


def test_render_github_actions_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = 'qa" evil: true'
    nasty_job_name = 'weird "job"; rm -rf / : ../../etc'
    nasty_pipeline_name = 'My "Perf" Pipeline: v2'
    config = {
        "setup": {"id": "gha-adversarial", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "catalog": {
            "environments": [{"key": nasty_env_value, "name": "QA"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke"}],
        },
        "manual_pipeline": {"enabled": True, "name": nasty_pipeline_name, "timeout_minutes": 30},
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

    outputs = render_github_actions(config, package, tmp_path)

    # A hostile job name must never escape the intended output directory or
    # produce filesystem-unsafe filenames.
    for output in outputs:
        filename = Path(output).name
        assert "/" not in filename
        assert ".." not in filename
        assert " " not in filename

    manual_path = tmp_path / ".github" / "workflows" / "performance-manual.yml"
    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)  # raises if the escaping broke YAML syntax
    assert manual_doc["name"] == nasty_pipeline_name
    # PyYAML's default resolver reads the bare "on:" key as boolean True.
    assert nasty_env_value in manual_doc[True]["workflow_dispatch"]["inputs"]["environment"]["options"]

    workflows_dir = tmp_path / ".github" / "workflows"
    automated_files = [p for p in workflows_dir.iterdir() if p.name.startswith("performance-automated-")]
    assert len(automated_files) == 1
    automated_text = automated_files[0].read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)  # raises if the escaping broke YAML syntax

    assert automated_doc["name"] == f"Performance Automated Job - {nasty_job_name}"
    job_id = next(iter(automated_doc["jobs"]))
    assert re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", job_id)
    assert shell_quote(nasty_job_name) in automated_text
