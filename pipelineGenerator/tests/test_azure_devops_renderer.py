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
    assert manual_doc["parameters"][0]["name"] == "test_case"
    assert manual_doc["parameters"][0]["values"] == ["qa: checkout_smoke"]
    assert "qa" in manual_text
    # The parameter value must be delivered via env:, never spliced directly
    # into the script: text.
    run_step = manual_doc["jobs"][0]["steps"][1]
    assert run_step["env"]["TEST_CASE"] == "${{ parameters.test_case }}"
    assert "./scripts/run-jmeter.sh" in manual_text
    assert '--test-case "$TEST_CASE"' in manual_text
    assert "parameters.test_case" not in run_step["script"]
    assert "pipeline-generator" not in manual_text

    automated_text = automated_path.read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)
    assert automated_doc["jobs"][0]["timeoutInMinutes"] == 60
    # job identifiers get hyphens sanitized to underscores.
    assert automated_doc["jobs"][0]["job"] == "post_deploy_smoke"
    assert "./scripts/run-jmeter.sh" in automated_text
    assert "--test-case 'qa: checkout_smoke'" in automated_text
    assert "pipeline-generator" not in automated_text


def test_render_azure_devops_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = 'qa" evil: true'
    nasty_job_name = 'weird "job"; rm -rf / : ../../etc'
    config = {
        "setup": {"id": "azure-adversarial", "generation_mode": "both"},
        "cicd": {"type": "azure_devops"},
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

    outputs = render_azure_devops(config, package, tmp_path)

    for output in outputs:
        filename = Path(output).name
        assert "/" not in filename
        assert ".." not in filename
        assert " " not in filename

    manual_path = tmp_path / "azure" / "performance-manual.yml"
    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)  # raises if the escaping broke YAML syntax
    test_case_param = next(p for p in manual_doc["parameters"] if p["name"] == "test_case")
    assert f"{nasty_env_value}: checkout_smoke" in test_case_param["values"]

    azure_dir = tmp_path / "azure"
    automated_files = [p for p in azure_dir.iterdir() if p.name.startswith("performance-automated-")]
    assert len(automated_files) == 1
    automated_text = automated_files[0].read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)  # raises if the escaping broke YAML syntax

    job_id = automated_doc["jobs"][0]["job"]
    assert re.match(r"^[A-Za-z0-9_]+$", job_id)
    assert not job_id[0].isdigit()
    assert shell_quote(f"{nasty_env_value}: checkout_smoke") in automated_text


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


_LOAD_PROFILE = {"test_type": "load", "users": 20, "ramp_up_seconds": 60, "duration_minutes": 10, "throughput_rps": 0}


def _manual_doc(tmp_path: Path) -> dict:
    return yaml.safe_load((tmp_path / "azure" / "performance-manual.yml").read_text(encoding="utf-8"))


def test_render_azure_devops_manual_pipeline_exposes_load_parameters(tmp_path: Path) -> None:
    config = _config()
    config["load_profile"] = dict(_LOAD_PROFILE)
    render_azure_devops(config, build_generic_package(config), tmp_path)

    doc = _manual_doc(tmp_path)
    parameters = {item["name"]: item for item in doc["parameters"]}
    assert parameters["users"]["default"] == "20"
    assert parameters["users"]["type"] == "string"
    assert parameters["test_type"]["default"] == "load"
    step = doc["jobs"][0]["steps"][1]
    assert step["env"]["USERS"] == "${{ parameters.users }}"
    assert '--users "$USERS"' in step["script"]
    assert "parameters.users" not in step["script"]


def test_render_azure_devops_loadrunner_manual_pipeline_has_only_test_type(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {"type": "loadrunner_professional", "connection": {"wlrun_path": "wlrun"}}
    config["load_profile"] = dict(_LOAD_PROFILE)
    render_azure_devops(config, build_generic_package(config), tmp_path)

    names = {item["name"] for item in _manual_doc(tmp_path)["parameters"]}
    assert "test_type" in names
    assert "users" not in names


def test_render_azure_devops_automated_job_passes_no_load_flags(tmp_path: Path) -> None:
    config = _config()
    config["load_profile"] = dict(_LOAD_PROFILE)
    render_azure_devops(config, build_generic_package(config), tmp_path)

    automated = [p for p in (tmp_path / "azure").iterdir() if p.name != "performance-manual.yml"]
    assert automated
    for path in automated:
        assert "--users" not in path.read_text(encoding="utf-8")
