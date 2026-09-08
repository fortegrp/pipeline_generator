from __future__ import annotations

import re
from pathlib import Path

from pipeline_generator.generator.generic_model import GenericPipelinePackage
from pipeline_generator.renderers.quoting import safe_filename_component, shell_quote, yaml_dquote


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
            automated_path = workflow_dir / f"performance-automated-{safe_filename_component(job.name)}.yml"
            automated_path.write_text(_render_automated_workflow(job, package.tool_type), encoding="utf-8")
            outputs.append(str(automated_path))

    return outputs


def _safe_job_id(value: str) -> str:
    """Sanitize a job name into a valid GitHub Actions job id.

    Job ids must start with a letter or underscore and contain only
    alphanumerics, `-`, or `_` (https://docs.github.com/actions).
    """
    text = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    if not text or not re.match(r"[A-Za-z_]", text[0]):
        text = f"job_{text}"
    return text


def _render_manual_workflow(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    environment_options = ", ".join(yaml_dquote(item.value) for item in package.manual_pipeline.inputs[0].options)
    scenario_options = ", ".join(yaml_dquote(item.value) for item in package.manual_pipeline.inputs[1].options)
    timeout = package.manual_pipeline.timeout_minutes
    return f"""name: {yaml_dquote(package.manual_pipeline.name)}

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
      - name: Run performance wrapper
        env:
          ENVIRONMENT: ${{{{ github.event.inputs.environment }}}}
          SCENARIO: ${{{{ github.event.inputs.scenario }}}}
        run: >
          ./scripts/run-{package.tool_type}.sh
          --environment "$ENVIRONMENT"
          --scenario "$SCENARIO"
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: performance-results
          path: run-output/
"""


def _render_automated_workflow(job, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    return f"""name: {yaml_dquote(f"Performance Automated Job - {job.name}")}

on:
  workflow_call:

jobs:
  {job_id}:
    runs-on: ubuntu-latest
    timeout-minutes: {job.timeout_minutes}
    steps:
      - uses: actions/checkout@v4
      - name: Run performance wrapper
        run: >
          ./scripts/run-{tool_type}.sh
          --environment {shell_quote(job.environment_ref)}
          --scenario {shell_quote(job.scenario_ref)}
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: {yaml_dquote(f"performance-results-{job.name}")}
          path: run-output/
"""
