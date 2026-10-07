from __future__ import annotations

from pathlib import Path

from pipeline_generator.generator.generic_model import AutomatedJobSpec, GenericPipelinePackage
from pipeline_generator.config.schema import JENKINS_BLAZEMETER_CREDENTIALS_ID, LOAD_PROFILE_LABELS
from pipeline_generator.renderers.quoting import (
    blazemeter_timeout_flag,
    groovy_squote,
    load_flags,
    safe_filename_component,
    secret_names,
)


def render_jenkins(config: dict, package: GenericPipelinePackage, setup_dir: Path) -> list[str]:
    jenkins_dir = setup_dir / "jenkins"
    jenkins_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []

    if package.manual_pipeline:
        manual_path = jenkins_dir / "Jenkinsfile.performance-manual"
        manual_path.write_text(_render_manual_pipeline(package), encoding="utf-8")
        outputs.append(str(manual_path))

    if package.automated_jobs:
        for job in package.automated_jobs:
            automated_path = jenkins_dir / f"Jenkinsfile.performance-automated-{safe_filename_component(job.name)}"
            automated_path.write_text(
                _render_automated_job(job, package.tool_type, package.runner), encoding="utf-8"
            )
            outputs.append(str(automated_path))

    return outputs


def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    test_case_choices = "\n".join(
        f"                {groovy_squote(target.selector)}," for target in package.run_targets
    )
    timeout = package.manual_pipeline.timeout_minutes
    timeout_flag = blazemeter_timeout_flag(package.tool_type, timeout)
    load_parameters = "".join(
        f"\n        string(name: {groovy_squote(item.env_var)}, defaultValue: {groovy_squote(item.default)}, "
        f"description: {groovy_squote(LOAD_PROFILE_LABELS[item.name])})"
        for item in package.load_inputs
    )
    load_flag_text = load_flags(package.load_inputs)
    return f"""pipeline {{
    {_agent(package.runner)}
    parameters {{
        choice(
            name: 'TEST_CASE',
            choices: [
{test_case_choices}
            ],
            description: 'Select environment and scenario'
        ){load_parameters}
    }}
    options {{
        timeout(time: {timeout}, unit: 'MINUTES')
    }}
    stages {{
        stage('Run performance wrapper') {{
            steps {{
                // Build parameters are exposed as shell environment variables by
                // Jenkins; referencing them here (rather than Groovy-interpolating
                // ${{params.X}} into the command text) avoids splicing a
                // build-triggerer-controlled value directly into the shell script.
{_run_step(package.tool_type, f'sh \'./scripts/run-{package.tool_type}.sh --test-case "$TEST_CASE"{load_flag_text}{timeout_flag}\'')}
            }}
        }}
    }}
    post {{
        always {{
            archiveArtifacts artifacts: 'run-output/**', allowEmptyArchive: true
        }}
    }}
}}
"""


def _run_step(tool_type: str, sh_line: str) -> str:
    names = secret_names(tool_type)
    if not names:
        return f"                {sh_line}"
    key_id, key_secret = names
    # One "Username with password" credential: username = API key ID,
    # password = API key secret.
    return (
        f"                withCredentials([usernamePassword(credentialsId: '{JENKINS_BLAZEMETER_CREDENTIALS_ID}', "
        f"usernameVariable: '{key_id}', passwordVariable: '{key_secret}')]) {{\n"
        f"                    {sh_line}\n"
        "                }"
    )


def _agent(runner: str) -> str:
    return f"agent {{ label {groovy_squote(runner)} }}" if runner else "agent any"


def _render_automated_job(job: AutomatedJobSpec, tool_type: str, runner: str) -> str:
    timeout_flag = blazemeter_timeout_flag(tool_type, job.timeout_minutes)
    return f"""pipeline {{
    {_agent(runner)}
    environment {{
        TEST_CASE = {groovy_squote(job.test_case)}
    }}
    options {{
        timeout(time: {job.timeout_minutes}, unit: 'MINUTES')
    }}
    stages {{
        stage('Run performance wrapper') {{
            steps {{
{_run_step(tool_type, f'sh \'./scripts/run-{tool_type}.sh --test-case "$TEST_CASE"{timeout_flag}\'')}
            }}
        }}
    }}
    post {{
        always {{
            archiveArtifacts artifacts: 'run-output/**', allowEmptyArchive: true
        }}
    }}
}}
"""
