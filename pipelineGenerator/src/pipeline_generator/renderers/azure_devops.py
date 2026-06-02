from __future__ import annotations

from pathlib import Path

from pipeline_generator.generator.generic_model import GenericPipelinePackage


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
            automated_path = azure_dir / f"performance-automated-{job.name}.yml"
            automated_path.write_text(_render_automated_job(job), encoding="utf-8")
            outputs.append(str(automated_path))

    return outputs


def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_values = "\n".join(f"      - {item.value}" for item in package.manual_pipeline.inputs[0].options)
    scenario_values = "\n".join(f"      - {item.value}" for item in package.manual_pipeline.inputs[1].options)
    return f"""trigger: none
pr: none

parameters:
  - name: environment
    displayName: Environment
    type: string
    default: {package.manual_pipeline.inputs[0].options[0].value if package.manual_pipeline.inputs[0].options else "TODO"}
    values:
{environment_values}
  - name: scenario
    displayName: Scenario
    type: string
    default: {package.manual_pipeline.inputs[1].options[0].value if package.manual_pipeline.inputs[1].options else "TODO"}
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
          --environment ${{{{ parameters.environment }}}}
          --scenario ${{{{ parameters.scenario }}}}
        displayName: Run performance wrapper
      - task: PublishPipelineArtifact@1
        condition: always()
        inputs:
          targetPath: run-output
          artifact: performance-results
"""


def _render_automated_job(job) -> str:
    return f"""parameters: []

jobs:
  - job: {job.name.replace('-', '_')}
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
          --job {job.name}
        displayName: Run performance wrapper
      - task: PublishPipelineArtifact@1
        condition: always()
        inputs:
          targetPath: run-output
          artifact: performance-results-{job.name}
"""
