from __future__ import annotations

from pathlib import Path

from pipeline_generator.generator.generic_model import GenericPipelinePackage


def render_github_actions(config: dict, package: GenericPipelinePackage, setup_dir: Path) -> list[str]:
    workflow_dir = setup_dir / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []

    if package.manual_pipeline:
        manual_path = workflow_dir / "performance-manual.yml"
        manual_path.write_text(_render_manual_workflow(package), encoding="utf-8")
        outputs.append(str(manual_path))

    if package.automated_jobs:
        for job in package.automated_jobs:
            automated_path = workflow_dir / f"performance-automated-{job.name}.yml"
            automated_path.write_text(_render_automated_workflow(job), encoding="utf-8")
            outputs.append(str(automated_path))

    return outputs


def _render_manual_workflow(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_options = ", ".join(f'"{item.value}"' for item in package.manual_pipeline.inputs[0].options)
    scenario_options = ", ".join(f'"{item.value}"' for item in package.manual_pipeline.inputs[1].options)
    timeout = package.manual_pipeline.timeout_minutes
    return f"""name: {package.manual_pipeline.name}

on:
  workflow_dispatch:
    inputs:
      environment:
        description: Select environment
        required: true
        type: choice
        options: [{environment_options}]
      scenario:
        description: Select scenario
        required: true
        type: choice
        options: [{scenario_options}]

jobs:
  run-performance-test:
    runs-on: ubuntu-latest
    timeout-minutes: {timeout}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install project
        run: pip install -e .
      - name: Run performance wrapper
        run: >
          pipeline-generator run
          --config customer.yaml
          --mode manual
          --environment "${{{{ github.event.inputs.environment }}}}"
          --scenario "${{{{ github.event.inputs.scenario }}}}"
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: performance-results
          path: run-output/
"""


def _render_automated_workflow(job) -> str:
    return f"""name: Performance Automated Job - {job.name}

on:
  workflow_call:

jobs:
  {job.name}:
    runs-on: ubuntu-latest
    timeout-minutes: {job.timeout_minutes}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install project
        run: pip install -e .
      - name: Run performance wrapper
        run: >
          pipeline-generator run
          --config customer.yaml
          --mode automated
          --job "{job.name}"
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: performance-results-{job.name}
          path: run-output/
"""
