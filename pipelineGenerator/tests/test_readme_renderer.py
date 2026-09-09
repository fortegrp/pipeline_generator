from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.readme import render_setup_readme


def _base_config(tool_type: str, connection: dict) -> dict:
    return {
        "setup": {
            "id": "readme-test-setup",
            "generation_mode": "both",
            "target_repository": "https://example.com/repo.git",
            "working_location": "central_repo",
            "final_pipeline_destination": "copy_to_customer_repo",
        },
        "cicd": {"type": "github_actions"},
        "tool": {"type": tool_type, "connection": connection},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": "qa", "name": "QA", "identifier": "env-qa"}],
            "scenarios": [{"key": "checkout_smoke", "name": "Checkout Smoke", "identifier": "SC-1"}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 30},
        "automated_jobs": [],
        "readme": {"include_manual_usage": True, "include_automated_usage": True},
    }


def test_readme_mentions_blazemeter_secrets_and_verification_caveat() -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    )
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)

    assert "scripts/run-blazemeter.sh" in readme
    assert "BLAZEMETER_API_KEY_ID" in readme
    assert "BLAZEMETER_API_KEY_SECRET" in readme
    assert "verify against a live account" in readme
    assert "Fill in the actual API/controller call" not in readme


def test_readme_mentions_jmeter_script_in_files_section() -> None:
    config = _base_config("jmeter", {"test_plan_path": "performance/checkout.jmx", "jmeter_bin": ""})
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)

    assert "scripts/run-jmeter.sh" in readme


def test_readme_mentions_loadrunner_script_without_todo_api_call() -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)

    assert "scripts/run-loadrunner_professional.sh" in readme
    assert "Fill in the actual API/controller call" not in readme


def test_readme_mentions_loadrunner_agent_caveat() -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)

    assert "co-located with the LoadRunner" in readme
    assert "retarget the generated pipeline's runner/agent/pool" in readme
