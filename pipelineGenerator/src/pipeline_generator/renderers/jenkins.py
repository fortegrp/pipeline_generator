from __future__ import annotations

from pathlib import Path

from pipeline_generator.generator.generic_model import GenericPipelinePackage


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
            automated_path = jenkins_dir / f"Jenkinsfile.performance-automated-{job.name}"
            automated_path.write_text(_render_automated_job(job), encoding="utf-8")
            outputs.append(str(automated_path))

    return outputs


def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_choices = "\n".join(
        f"                '{item.value}'," for item in package.manual_pipeline.inputs[0].options
    )
    scenario_choices = "\n".join(
        f"                '{item.value}'," for item in package.manual_pipeline.inputs[1].options
    )
    timeout = package.manual_pipeline.timeout_minutes
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
        stage('Install project') {{
            steps {{
                sh 'pip install -e .'
            }}
        }}
        stage('Run performance wrapper') {{
            steps {{
                sh "pipeline-generator run --config customer.yaml --mode manual --environment ${{params.ENVIRONMENT}} --scenario ${{params.SCENARIO}}"
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


def _render_automated_job(job) -> str:
    return f"""pipeline {{
    agent any
    options {{
        timeout(time: {job.timeout_minutes}, unit: 'MINUTES')
    }}
    stages {{
        stage('Install project') {{
            steps {{
                sh 'pip install -e .'
            }}
        }}
        stage('Run performance wrapper') {{
            steps {{
                sh 'pipeline-generator run --config customer.yaml --mode automated --job {job.name}'
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
