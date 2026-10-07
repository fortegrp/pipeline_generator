from pathlib import Path

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.jenkins import render_jenkins
from pipeline_generator.renderers.quoting import groovy_squote


def _config() -> dict:
    return {
        "setup": {"id": "jenkins-test-setup", "generation_mode": "both"},
        "cicd": {"type": "jenkins"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "docker_image": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": "qa", "name": "QA", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}]}],
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
    assert "./scripts/run-jmeter.sh" in manual_content
    assert '--test-case "$TEST_CASE"' in manual_content
    assert "name: 'TEST_CASE'" in manual_content
    assert "'qa: checkout_smoke'," in manual_content
    assert "timeout(time: 120, unit: 'MINUTES')" in manual_content
    assert "pipeline-generator" not in manual_content

    automated_content = automated_path.read_text(encoding="utf-8")
    assert "TEST_CASE = 'qa: checkout_smoke'" in automated_content
    assert './scripts/run-jmeter.sh --test-case "$TEST_CASE"' in automated_content
    assert "timeout(time: 60, unit: 'MINUTES')" in automated_content
    assert "pipeline-generator" not in automated_content


def test_render_jenkins_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = "qa'; rm -rf / #"
    nasty_job_name = "weird'job\"; rm -rf / \\ ../../etc"
    config = {
        "setup": {"id": "jenkins-adversarial", "generation_mode": "both"},
        "cicd": {"type": "jenkins"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "docker_image": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": nasty_env_value, "name": "QA", "identifier": "env-nasty", "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}]}],
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
    assert groovy_squote(f"{nasty_env_value}: checkout_smoke") in manual_content
    assert '--test-case "$TEST_CASE"' in manual_content

    jenkins_dir = tmp_path / "jenkins"
    automated_files = [p for p in jenkins_dir.iterdir() if p.name.startswith("Jenkinsfile.performance-automated-")]
    assert len(automated_files) == 1
    automated_content = automated_files[0].read_text(encoding="utf-8")
    # environment_ref (the adversarial value here) must be delivered via the
    # environment{} block, Groovy-escaped, never spliced directly into the
    # sh command text.
    assert f"TEST_CASE = {groovy_squote(f'{nasty_env_value}: checkout_smoke')}" in automated_content
    assert './scripts/run-jmeter.sh --test-case "$TEST_CASE"' in automated_content


def test_render_jenkins_includes_timeout_flag_for_blazemeter(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {
        "type": "blazemeter",
        "connection": {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    }
    package = build_generic_package(config)

    render_jenkins(config, package, tmp_path)

    manual_text = (tmp_path / "jenkins" / "Jenkinsfile.performance-manual").read_text(encoding="utf-8")
    automated_text = (
        tmp_path / "jenkins" / "Jenkinsfile.performance-automated-post-deploy-smoke"
    ).read_text(encoding="utf-8")

    assert "--timeout-minutes 120" in manual_text
    assert "--timeout-minutes 60" in automated_text


_LOAD_PROFILE = {"test_type": "load", "users": 20, "ramp_up_seconds": 60, "duration_minutes": 10, "throughput_rps": 0}


def test_render_jenkins_manual_pipeline_exposes_load_parameters(tmp_path: Path) -> None:
    config = _config()
    config["load_profile"] = dict(_LOAD_PROFILE)
    render_jenkins(config, build_generic_package(config), tmp_path)

    text = (tmp_path / "jenkins" / "Jenkinsfile.performance-manual").read_text(encoding="utf-8")
    assert "string(name: 'USERS', defaultValue: '20'" in text
    assert "string(name: 'TEST_TYPE', defaultValue: 'load'" in text
    assert '--users "$USERS"' in text
    assert "params.USERS" not in text


def test_render_jenkins_loadrunner_manual_pipeline_has_only_test_type(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {"type": "loadrunner_professional", "connection": {"wlrun_path": "wlrun"}}
    config["load_profile"] = dict(_LOAD_PROFILE)
    render_jenkins(config, build_generic_package(config), tmp_path)

    text = (tmp_path / "jenkins" / "Jenkinsfile.performance-manual").read_text(encoding="utf-8")
    assert "name: 'TEST_TYPE'" in text
    assert "name: 'USERS'" not in text


def test_render_jenkins_automated_job_passes_no_load_flags(tmp_path: Path) -> None:
    config = _config()
    config["load_profile"] = dict(_LOAD_PROFILE)
    render_jenkins(config, build_generic_package(config), tmp_path)

    automated = [p for p in (tmp_path / "jenkins").iterdir() if "manual" not in p.name]
    assert automated
    for path in automated:
        assert "--users" not in path.read_text(encoding="utf-8")
