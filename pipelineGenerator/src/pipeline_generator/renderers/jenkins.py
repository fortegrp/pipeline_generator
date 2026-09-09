from __future__ import annotations

from pathlib import Path

from pipeline_generator.generator.generic_model import GenericPipelinePackage
from pipeline_generator.renderers.quoting import groovy_squote, safe_filename_component


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
            automated_path.write_text(_render_automated_job(job, package.tool_type), encoding="utf-8")
            outputs.append(str(automated_path))

    return outputs


def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_choices = "\n".join(
        f"                {groovy_squote(item.value)}," for item in package.manual_pipeline.inputs[0].options
    )
    scenario_choices = "\n".join(
        f"                {groovy_squote(item.value)}," for item in package.manual_pipeline.inputs[1].options
    )
    timeout = package.manual_pipeline.timeout_minutes
    timeout_flag = f" --timeout-minutes {timeout}" if package.tool_type == "blazemeter" else ""
    return f"""pipeline {{
    agent any
    parameters {{
        choice(
            name: 'ENVIRONMENT',
            choices: [
{environment_choices}
            ],
            description: 'Select environment'
        )
        choice(
            name: 'SCENARIO',
            choices: [
{scenario_choices}
            ],
            description: 'Select scenario'
        )
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
                sh './scripts/run-{package.tool_type}.sh --environment "$ENVIRONMENT" --scenario "$SCENARIO"{timeout_flag}'
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


def _render_automated_job(job, tool_type: str) -> str:
    timeout_flag = f" --timeout-minutes {job.timeout_minutes}" if tool_type == "blazemeter" else ""
    return f"""pipeline {{
    agent any
    environment {{
        ENVIRONMENT = {groovy_squote(job.environment_ref)}
        SCENARIO = {groovy_squote(job.scenario_ref)}
    }}
    options {{
        timeout(time: {job.timeout_minutes}, unit: 'MINUTES')
    }}
    stages {{
        stage('Run performance wrapper') {{
            steps {{
                sh './scripts/run-{tool_type}.sh --environment "$ENVIRONMENT" --scenario "$SCENARIO"{timeout_flag}'
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
