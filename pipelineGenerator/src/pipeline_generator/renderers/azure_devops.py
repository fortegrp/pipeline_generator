from __future__ import annotations

import re
from pathlib import Path

from pipeline_generator.generator.generic_model import GenericPipelinePackage
from pipeline_generator.renderers.quoting import safe_filename_component, shell_quote, yaml_dquote


def render_azure_devops(config: dict, package: GenericPipelinePackage, setup_dir: Path) -> list[str]:
    azure_dir = setup_dir / "azure"
    azure_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []

    if package.manual_pipeline:
        manual_path = azure_dir / "performance-manual.yml"
        manual_path.write_text(_render_manual_pipeline(package), encoding="utf-8")
        outputs.append(str(manual_path))

    if package.automated_jobs:
        for job in package.automated_jobs:
            automated_path = azure_dir / f"performance-automated-{safe_filename_component(job.name)}.yml"
            automated_path.write_text(_render_automated_job(job), encoding="utf-8")
            outputs.append(str(automated_path))

    return outputs


def _safe_job_id(value: str) -> str:
    """Sanitize a job name into a valid Azure Pipelines job id (`[A-Za-z0-9_]`, no leading digit)."""
    text = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not text or text[0].isdigit():
        text = f"job_{text}"
    return text


def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_options = package.manual_pipeline.inputs[0].options
    scenario_options = package.manual_pipeline.inputs[1].options
    environment_values = "\n".join(f"      - {yaml_dquote(item.value)}" for item in environment_options)
    scenario_values = "\n".join(f"      - {yaml_dquote(item.value)}" for item in scenario_options)
    environment_default = yaml_dquote(environment_options[0].value if environment_options else "TODO")
    scenario_default = yaml_dquote(scenario_options[0].value if scenario_options else "TODO")
    return f"""trigger: none
pr: none

parameters:
  - name: environment
    displayName: Environment
    type: string
    default: {environment_default}
    values:
{environment_values}
  - name: scenario
    displayName: Scenario
    type: string
    default: {scenario_default}
    values:
{scenario_values}

jobs:
  - job: run_performance_test
    timeoutInMinutes: {package.manual_pipeline.timeout_minutes}
    pool:
      vmImage: ubuntu-latest
    steps:
      - checkout: self
      - task: UsePythonVersion@0
        inputs:
          versionSpec: '3.11'
      - script: pip install -e .
        displayName: Install project
      - script: >
          pipeline-generator run
          --config customer.yaml
          --mode manual
          --environment "$ENVIRONMENT"
          --scenario "$SCENARIO"
        env:
          ENVIRONMENT: ${{{{ parameters.environment }}}}
          SCENARIO: ${{{{ parameters.scenario }}}}
        displayName: Run performance wrapper
      - task: PublishPipelineArtifact@1
        condition: always()
        inputs:
          targetPath: run-output
          artifact: performance-results
"""


def _render_automated_job(job) -> str:
    job_id = _safe_job_id(job.name)
    return f"""parameters: []

jobs:
  - job: {job_id}
    timeoutInMinutes: {job.timeout_minutes}
    pool:
      vmImage: ubuntu-latest
    steps:
      - checkout: self
      - task: UsePythonVersion@0
        inputs:
          versionSpec: '3.11'
      - script: pip install -e .
        displayName: Install project
      - script: >
          pipeline-generator run
          --config customer.yaml
          --mode automated
          --job {shell_quote(job.name)}
        displayName: Run performance wrapper
      - task: PublishPipelineArtifact@1
        condition: always()
        inputs:
          targetPath: run-output
          artifact: {yaml_dquote(f"performance-results-{job.name}")}
"""
