from pathlib import Path

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.jenkins import render_jenkins


def _config() -> dict:
    return {
        "setup": {"id": "jenkins-test-setup", "generation_mode": "both"},
        "cicd": {"type": "jenkins"},
        "catalog": {
            "environments": [{"key": "qa", "name": "QA"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 120},
        "automated_jobs": [
            {"name": "post-deploy-smoke", "enabled": True, "environment_ref": "qa", "scenario_ref": "checkout_smoke", "timeout_minutes": 60}
        ],
    }


def test_render_jenkins_writes_manual_and_automated_jenkinsfiles(tmp_path: Path) -> None:
    config = _config()
    package = build_generic_package(config)

    outputs = render_jenkins(config, package, tmp_path)

    manual_path = tmp_path / "jenkins" / "Jenkinsfile.performance-manual"
    automated_path = tmp_path / "jenkins" / "Jenkinsfile.performance-automated-post-deploy-smoke"
    assert str(manual_path) in outputs
    assert str(automated_path) in outputs

    manual_content = manual_path.read_text(encoding="utf-8")
    assert "pipeline-generator run --config customer.yaml --mode manual" in manual_content
    assert "'qa'," in manual_content
    assert "'checkout_smoke'," in manual_content
    assert "timeout(time: 120, unit: 'MINUTES')" in manual_content

    automated_content = automated_path.read_text(encoding="utf-8")
    assert "--mode automated --job post-deploy-smoke" in automated_content
    assert "timeout(time: 60, unit: 'MINUTES')" in automated_content
