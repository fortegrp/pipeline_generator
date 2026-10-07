from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.readme import render_setup_readme


def _base_config(tool_type: str, connection: dict) -> dict:
    return {
        "setup": {
            "id": "readme-test-setup",
            "generation_mode": "both",
        },
        "cicd": {"type": "github_actions"},
        "tool": {"type": tool_type, "connection": connection},
        "pre_run_checks": [],
        "catalog": {
            "environments": [{"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 30},
        "automated_jobs": [],
        "readme": {"include_manual_usage": True, "include_automated_usage": True},
    }


def _section(readme: str, heading: str) -> str:
    """Extract the text of one `## heading` section (up to the next `## `)."""
    marker = f"## {heading}"
    start = readme.index(marker) + len(marker)
    rest = readme[start:]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


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
    assert "Ensure `jq` is installed" in readme


def test_readme_mentions_jmeter_script_in_files_section() -> None:
    config = _base_config("jmeter", {"test_plan_path": "performance/checkout.jmx", "docker_image": ""})
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)

    assert "scripts/run-jmeter.sh" in readme


def test_readme_mentions_jmeter_docker_requirement_in_todos_and_troubleshooting() -> None:
    config = _base_config("jmeter", {"test_plan_path": "performance/checkout.jmx", "docker_image": ""})
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)
    todos = _section(readme, "Remaining TODOs")
    troubleshooting = _section(readme, "Troubleshooting")

    assert "Ensure Docker is installed and running" in todos
    assert "docker` on the agent/runner's" in troubleshooting


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


def test_readme_mentions_run_summary_json_for_every_tool() -> None:
    for tool_type, connection in (
        ("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""}),
        ("loadrunner_professional", {"wlrun_path": "wlrun"}),
        ("blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "1", "project_id": "2"}),
    ):
        config = _base_config(tool_type, connection)
        package = build_generic_package(config)
        readme = render_setup_readme(config, package)
        assert "run-summary.json" in readme


def test_readme_todos_are_trimmed_to_must_fill_ins() -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    )
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)
    todos = _section(readme, "Remaining TODOs")

    assert "BLAZEMETER_API_KEY_ID" in todos
    assert "Ensure `jq` is installed" in todos
    assert "verify against a live account" not in todos

    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    package = build_generic_package(config)
    readme = render_setup_readme(config, package)
    todos = _section(readme, "Remaining TODOs")

    assert "co-located with the LoadRunner" not in todos
    assert "retarget the generated pipeline's runner/agent/pool" not in todos


def test_readme_troubleshooting_section_has_moved_caveats() -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    )
    package = build_generic_package(config)
    readme = render_setup_readme(config, package)
    troubleshooting = _section(readme, "Troubleshooting")

    assert "verify against a live account" in troubleshooting

    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    package = build_generic_package(config)
    readme = render_setup_readme(config, package)
    troubleshooting = _section(readme, "Troubleshooting")

    assert "co-located with the LoadRunner" in troubleshooting
    assert "retarget the generated pipeline's runner/agent/pool" in troubleshooting
    assert "exit code is known to be unreliable" in troubleshooting


def test_readme_troubleshooting_has_generic_guidance_for_every_tool() -> None:
    for tool_type, connection in (
        ("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""}),
        ("loadrunner_professional", {"wlrun_path": "wlrun"}),
        ("blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "1", "project_id": "2"}),
    ):
        config = _base_config(tool_type, connection)
        package = build_generic_package(config)
        readme = render_setup_readme(config, package)
        troubleshooting = _section(readme, "Troubleshooting")
        assert "run-summary.json" in troubleshooting
        assert "Unknown test case" in troubleshooting


def test_readme_connection_details_jmeter() -> None:
    config = _base_config("jmeter", {"test_plan_path": "performance/checkout.jmx", "docker_image": ""})
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)
    details = _section(readme, "Connection Details")

    assert "performance/checkout.jmx" in details
    assert "justb4/jmeter:5.6.3" in details


def test_readme_connection_details_jmeter_custom_docker_image() -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": "myorg/jmeter:custom"})
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)
    details = _section(readme, "Connection Details")

    assert "myorg/jmeter:custom" in details


def test_readme_connection_details_loadrunner() -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "C:\\LoadRunner\\bin\\wlrun.exe"})
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)
    details = _section(readme, "Connection Details")

    assert "C:\\LoadRunner\\bin\\wlrun.exe" in details


def test_readme_connection_details_blazemeter() -> None:
    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    )
    package = build_generic_package(config)

    readme = render_setup_readme(config, package)
    details = _section(readme, "Connection Details")

    assert "https://a.blazemeter.com" in details
    assert "12345" in details
    assert "67890" in details


def test_readme_manual_usage_is_cicd_specific() -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})

    config["cicd"]["type"] = "github_actions"
    readme = render_setup_readme(config, build_generic_package(config))
    assert "Actions" in _section(readme, "Manual Pipeline Usage")

    config["cicd"]["type"] = "azure_devops"
    readme = render_setup_readme(config, build_generic_package(config))
    assert "Run pipeline" in _section(readme, "Manual Pipeline Usage")

    config["cicd"]["type"] = "jenkins"
    readme = render_setup_readme(config, build_generic_package(config))
    assert "Build with Parameters" in _section(readme, "Manual Pipeline Usage")


def test_readme_automated_job_instructions_are_cicd_specific_and_named() -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["automated_jobs"] = [
        {"name": "Nightly Load", "environment_ref": "qa", "scenario_ref": "checkout_smoke", "enabled": True}
    ]

    config["cicd"]["type"] = "github_actions"
    readme = render_setup_readme(config, build_generic_package(config))
    section = _section(readme, "Automated Job Integration")
    assert "nightly-load" in section
    assert "uses:" in section

    config["cicd"]["type"] = "jenkins"
    readme = render_setup_readme(config, build_generic_package(config))
    section = _section(readme, "Automated Job Integration")
    assert "nightly-load" in section
    assert "build job:" in section


def test_readme_artifacts_section_per_tool() -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    readme = render_setup_readme(config, build_generic_package(config))
    section = _section(readme, "Artifacts & Output")
    assert "results.jtl" in section
    assert "report/" in section
    assert "run-summary.json" in section

    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    readme = render_setup_readme(config, build_generic_package(config))
    section = _section(readme, "Artifacts & Output")
    assert "run-summary.json" in section

    config = _base_config(
        "blazemeter",
        {"base_url": "https://a.blazemeter.com", "workspace_id": "1", "project_id": "2"},
    )
    readme = render_setup_readme(config, build_generic_package(config))
    section = _section(readme, "Artifacts & Output")
    assert "summary.json" in section
    assert "report_link.json" in section
    assert "run-summary.json" in section


_LOAD_PROFILE = {"test_type": "soak", "users": 20, "ramp_up_seconds": 60, "duration_minutes": 10, "throughput_rps": 0}


def test_readme_lists_load_profile() -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["load_profile"] = dict(_LOAD_PROFILE)

    section = _section(render_setup_readme(config, build_generic_package(config)), "Load Profile")

    assert "`users`: `20`" in section
    assert "`test_type`: `soak`" in section
    assert "--users" in section  # how to override per run


def test_readme_tells_jmeter_users_which_properties_to_wire() -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["load_profile"] = dict(_LOAD_PROFILE)

    section = _section(render_setup_readme(config, build_generic_package(config)), "Load Profile")

    for prop in ("${__P(users,1)}", "${__P(ramp_up_seconds,0)}", "${__P(duration_seconds,60)}",
                 "${__P(throughput_per_minute,0)}", "${__P(test_type)}"):
        assert prop in section


def test_readme_says_loadrunner_load_shape_comes_from_lrs() -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    config["load_profile"] = {"test_type": "load"}

    section = _section(render_setup_readme(config, build_generic_package(config)), "Load Profile")

    assert ".lrs" in section
    assert "`users`" not in section


def test_readme_todos_list_unfilled_load_values() -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["load_profile"] = {**_LOAD_PROFILE, "users": "TODO"}

    todos = _section(render_setup_readme(config, build_generic_package(config)), "Remaining TODOs")

    assert "`load_profile.users`" in todos
    assert "`load_profile.duration_minutes`" not in todos
