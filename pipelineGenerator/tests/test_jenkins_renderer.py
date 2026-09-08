from pathlib import Path

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.jenkins import render_jenkins
from pipeline_generator.renderers.quoting import groovy_squote


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
            {
                "name": "post-deploy-smoke",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 60,
            }
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
    assert '--environment "$ENVIRONMENT" --scenario "$SCENARIO"' in manual_content
    assert "'qa'," in manual_content
    assert "'checkout_smoke'," in manual_content
    assert "timeout(time: 120, unit: 'MINUTES')" in manual_content

    automated_content = automated_path.read_text(encoding="utf-8")
    assert "AUTOMATED_JOB_NAME = 'post-deploy-smoke'" in automated_content
    assert '--mode automated --job "$AUTOMATED_JOB_NAME"' in automated_content
    assert "timeout(time: 60, unit: 'MINUTES')" in automated_content


def test_render_jenkins_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = "qa'; rm -rf / #"
    nasty_job_name = "weird'job\"; rm -rf / \\ ../../etc"
    config = {
        "setup": {"id": "jenkins-adversarial", "generation_mode": "both"},
        "cicd": {"type": "jenkins"},
        "catalog": {
            "environments": [{"key": nasty_env_value, "name": "QA"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke"}],
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

    outputs = render_jenkins(config, package, tmp_path)

    # A hostile job name must never escape the intended output directory.
    for output in outputs:
        filename = Path(output).name
        assert "/" not in filename
        assert ".." not in filename
        assert " " not in filename

    manual_path = tmp_path / "jenkins" / "Jenkinsfile.performance-manual"
    manual_content = manual_path.read_text(encoding="utf-8")
    # The hostile environment value must appear only inside a properly
    # escaped single-quoted Groovy string, never able to close the `choice`
    # literal's quote early.
    assert groovy_squote(nasty_env_value) in manual_content
    # The manual step must reference the shell-native env var, never splice
    # a Jenkins parameter value directly into the command text.
    assert '--environment "$ENVIRONMENT" --scenario "$SCENARIO"' in manual_content

    jenkins_dir = tmp_path / "jenkins"
    automated_files = [p for p in jenkins_dir.iterdir() if p.name.startswith("Jenkinsfile.performance-automated-")]
    assert len(automated_files) == 1
    automated_content = automated_files[0].read_text(encoding="utf-8")
    assert f"AUTOMATED_JOB_NAME = {groovy_squote(nasty_job_name)}" in automated_content
    assert '--mode automated --job "$AUTOMATED_JOB_NAME"' in automated_content
