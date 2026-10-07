import re
from pathlib import Path

import yaml

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.github_actions import render_github_actions
from pipeline_generator.renderers.quoting import shell_quote



def _run_step(steps: list[dict]) -> dict:
    return next(step for step in steps if "Run performance wrapper" in (step.get("name"), step.get("displayName")))

def _config() -> dict:
    return {
        "setup": {"id": "gha-test-setup", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
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
    assert '"qa: checkout_smoke"' in manual_text
    # The build-triggerer-controlled input must be delivered via env:, never
    # spliced directly into the run: shell text (workflow_dispatch's `choice`
    # restriction is only enforced by GitHub's UI, not its dispatch API).
    step = _run_step(manual_doc["jobs"]["run-performance-test"]["steps"])
    assert step["env"]["TEST_CASE"] == "${{ github.event.inputs.test_case }}"
    assert "ENVIRONMENT" not in step["env"]
    assert "./scripts/run-jmeter.sh" in manual_text
    assert '--test-case "$TEST_CASE"' in manual_text
    assert manual_doc[True]["workflow_dispatch"]["inputs"]["test_case"]["options"] == ["qa: checkout_smoke"]
    assert "github.event.inputs" not in step["run"]
    assert "pipeline-generator" not in manual_text

    automated_text = automated_path.read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)
    assert automated_doc["jobs"]["post-deploy-smoke"]["timeout-minutes"] == 60
    assert "./scripts/run-jmeter.sh" in automated_text
    assert "--test-case 'qa: checkout_smoke'" in automated_text
    assert "pipeline-generator" not in automated_text


def test_render_github_actions_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = 'qa" evil: true'
    nasty_job_name = 'weird "job"; rm -rf / : ../../etc'
    nasty_pipeline_name = 'My "Perf" Pipeline: v2'
    config = {
        "setup": {"id": "gha-adversarial", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "docker_image": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": nasty_env_value, "name": "QA", "identifier": "env-nasty", "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}]}],
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
    assert f"{nasty_env_value}: checkout_smoke" in manual_doc[True]["workflow_dispatch"]["inputs"]["test_case"]["options"]

    workflows_dir = tmp_path / ".github" / "workflows"
    automated_files = [p for p in workflows_dir.iterdir() if p.name.startswith("performance-automated-")]
    assert len(automated_files) == 1
    automated_text = automated_files[0].read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)  # raises if the escaping broke YAML syntax

    assert automated_doc["name"] == f"Performance Automated Job - {nasty_job_name}"
    job_id = next(iter(automated_doc["jobs"]))
    assert re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", job_id)
    assert shell_quote(f"{nasty_env_value}: checkout_smoke") in automated_text


def test_render_github_actions_includes_timeout_flag_for_blazemeter(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {
        "type": "blazemeter",
        "connection": {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    }
    package = build_generic_package(config)

    render_github_actions(config, package, tmp_path)

    manual_text = (tmp_path / ".github" / "workflows" / "performance-manual.yml").read_text(encoding="utf-8")
    automated_text = (
        tmp_path / ".github" / "workflows" / "performance-automated-post-deploy-smoke.yml"
    ).read_text(encoding="utf-8")

    assert "--timeout-minutes 120" in manual_text
    assert "--timeout-minutes 60" in automated_text


_LOAD_PROFILE = {"test_type": "load", "users": 20, "ramp_up_seconds": 60, "duration_minutes": 10, "throughput_rps": 0}


def test_render_github_actions_manual_workflow_exposes_load_inputs(tmp_path: Path) -> None:
    config = _config()
    config["load_profile"] = dict(_LOAD_PROFILE)
    render_github_actions(config, build_generic_package(config), tmp_path)

    manual_text = (tmp_path / ".github" / "workflows" / "performance-manual.yml").read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)
    inputs = manual_doc[True]["workflow_dispatch"]["inputs"]
    assert inputs["users"]["default"] == "20"
    assert inputs["users"]["type"] == "string"
    assert inputs["throughput_rps"]["default"] == "0"
    assert inputs["test_type"]["default"] == "load"
    step = _run_step(manual_doc["jobs"]["run-performance-test"]["steps"])
    assert step["env"]["USERS"] == "${{ github.event.inputs.users }}"
    assert step["env"]["RAMP_UP_SECONDS"] == "${{ github.event.inputs.ramp_up_seconds }}"
    assert '--users "$USERS"' in step["run"]
    assert '--throughput-rps "$THROUGHPUT_RPS"' in step["run"]
    assert "inputs.users" not in step["run"]


def test_render_github_actions_shows_todo_default_for_unknown_load_value(tmp_path: Path) -> None:
    config = _config()
    config["load_profile"] = {**_LOAD_PROFILE, "users": "TODO"}
    render_github_actions(config, build_generic_package(config), tmp_path)

    manual_doc = yaml.safe_load((tmp_path / ".github" / "workflows" / "performance-manual.yml").read_text())
    assert manual_doc[True]["workflow_dispatch"]["inputs"]["users"]["default"] == "TODO"


def test_render_github_actions_loadrunner_manual_workflow_has_only_test_type(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {"type": "loadrunner_professional", "connection": {"wlrun_path": "wlrun"}}
    config["load_profile"] = dict(_LOAD_PROFILE)
    render_github_actions(config, build_generic_package(config), tmp_path)

    manual_doc = yaml.safe_load((tmp_path / ".github" / "workflows" / "performance-manual.yml").read_text())
    inputs = manual_doc[True]["workflow_dispatch"]["inputs"]
    assert "test_type" in inputs
    assert "users" not in inputs


def test_render_github_actions_automated_job_passes_no_load_flags(tmp_path: Path) -> None:
    config = _config()
    config["load_profile"] = dict(_LOAD_PROFILE)
    render_github_actions(config, build_generic_package(config), tmp_path)

    automated_text = (
        tmp_path / ".github" / "workflows" / "performance-automated-post-deploy-smoke.yml"
    ).read_text(encoding="utf-8")
    assert "--users" not in automated_text
    assert "--test-type" not in automated_text


def test_render_github_actions_dropdown_lists_only_defined_pairs(tmp_path: Path) -> None:
    config = _config()
    config["catalog"]["environments"] = [
        {"key": "qa", "identifier": "QA", "scenarios": [{"key": "checkout", "identifier": "1"}, {"key": "browse", "identifier": "2"}]},
        {"key": "staging", "identifier": "STG", "scenarios": [{"key": "checkout", "identifier": "3"}]},
    ]
    config["automated_jobs"] = []
    render_github_actions(config, build_generic_package(config), tmp_path)

    manual_doc = yaml.safe_load((tmp_path / ".github" / "workflows" / "performance-manual.yml").read_text())
    options = manual_doc[True]["workflow_dispatch"]["inputs"]["test_case"]["options"]
    assert options == ["qa: checkout", "qa: browse", "staging: checkout"]  # no "staging: browse"


def _blazemeter_config() -> dict:
    config = _config()
    config["tool"] = {
        "type": "blazemeter",
        "connection": {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    }
    return config


def test_render_github_actions_maps_blazemeter_secrets_into_manual_step(tmp_path: Path) -> None:
    config = _blazemeter_config()
    render_github_actions(config, build_generic_package(config), tmp_path)

    doc = yaml.safe_load((tmp_path / ".github" / "workflows" / "performance-manual.yml").read_text())
    env = _run_step(doc["jobs"]["run-performance-test"]["steps"])["env"]
    assert env["BLAZEMETER_API_KEY_ID"] == "${{ secrets.BLAZEMETER_API_KEY_ID }}"
    assert env["BLAZEMETER_API_KEY_SECRET"] == "${{ secrets.BLAZEMETER_API_KEY_SECRET }}"


def test_render_github_actions_automated_workflow_declares_and_maps_blazemeter_secrets(tmp_path: Path) -> None:
    config = _blazemeter_config()
    render_github_actions(config, build_generic_package(config), tmp_path)

    doc = yaml.safe_load(
        (tmp_path / ".github" / "workflows" / "performance-automated-post-deploy-smoke.yml").read_text()
    )
    # A reusable workflow only sees secrets its caller passes, so it must declare them.
    declared = doc[True]["workflow_call"]["secrets"]
    assert declared["BLAZEMETER_API_KEY_ID"]["required"] is True
    assert declared["BLAZEMETER_API_KEY_SECRET"]["required"] is True
    env = _run_step(doc["jobs"]["post-deploy-smoke"]["steps"])["env"]
    assert env["BLAZEMETER_API_KEY_ID"] == "${{ secrets.BLAZEMETER_API_KEY_ID }}"
    assert env["BLAZEMETER_API_KEY_SECRET"] == "${{ secrets.BLAZEMETER_API_KEY_SECRET }}"


def test_render_github_actions_jmeter_has_no_blazemeter_secrets(tmp_path: Path) -> None:
    config = _config()
    render_github_actions(config, build_generic_package(config), tmp_path)

    for path in (tmp_path / ".github" / "workflows").iterdir():
        assert "BLAZEMETER" not in path.read_text()


def _all_workflows(tmp_path: Path) -> list[dict]:
    return [yaml.safe_load(p.read_text()) for p in sorted((tmp_path / ".github" / "workflows").iterdir())]


def test_render_github_actions_defaults_to_hosted_ubuntu_and_bash(tmp_path: Path) -> None:
    config = _config()
    render_github_actions(config, build_generic_package(config), tmp_path)

    for doc in _all_workflows(tmp_path):
        job = next(iter(doc["jobs"].values()))
        assert job["runs-on"] == "ubuntu-latest"
        # Explicit bash: a Windows runner would otherwise run the step in PowerShell.
        assert _run_step(job["steps"])["shell"] == "bash"


def test_render_github_actions_targets_configured_runner_labels(tmp_path: Path) -> None:
    config = _config()
    config["cicd"]["runner"] = "self-hosted, windows, lr-controller"
    render_github_actions(config, build_generic_package(config), tmp_path)

    for doc in _all_workflows(tmp_path):
        assert next(iter(doc["jobs"].values()))["runs-on"] == ["self-hosted", "windows", "lr-controller"]
