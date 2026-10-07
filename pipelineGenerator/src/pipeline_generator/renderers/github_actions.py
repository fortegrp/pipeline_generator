from __future__ import annotations

import re
from pathlib import Path

from pipeline_generator.generator.generic_model import AutomatedJobSpec, GenericPipelinePackage
from pipeline_generator.config.schema import LOAD_PROFILE_LABELS
from pipeline_generator.renderers.quoting import (
    blazemeter_timeout_flag,
    load_flags,
    secret_names,
    safe_filename_component,
    shell_quote,
    yaml_dquote,
)


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
    test_case_options = ", ".join(yaml_dquote(target.selector) for target in package.run_targets)
    timeout = package.manual_pipeline.timeout_minutes
    timeout_flag = blazemeter_timeout_flag(package.tool_type, timeout, separator="\n          ")
    load_input_blocks = "".join(
        f"""
      {item.name}:
        description: {yaml_dquote(LOAD_PROFILE_LABELS[item.name])}
        required: false
        type: string
        default: {yaml_dquote(item.default)}"""
        for item in package.load_inputs
    )
    load_env = "".join(
        f"\n          {item.env_var}: ${{{{ github.event.inputs.{item.name} }}}}" for item in package.load_inputs
    )
    load_flag_text = load_flags(package.load_inputs, separator="\n          ")
    secret_env = _secret_env(package.tool_type)
    return f"""name: {yaml_dquote(package.manual_pipeline.name)}

on:
  workflow_dispatch:
    inputs:
      test_case:
        description: Select environment and scenario
        required: true
        type: choice
        options: [{test_case_options}]{load_input_blocks}

jobs:
  run-performance-test:
    runs-on: ubuntu-latest
    timeout-minutes: {timeout}
    steps:
      - uses: actions/checkout@v4
      - name: Run performance wrapper
        env:
          TEST_CASE: ${{{{ github.event.inputs.test_case }}}}{load_env}{secret_env}
        run: >
          ./scripts/run-{package.tool_type}.sh
          --test-case "$TEST_CASE"{load_flag_text}{timeout_flag}
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: performance-results
          path: run-output/
"""


def _secret_env(tool_type: str) -> str:
    return "".join(f"\n          {name}: ${{{{ secrets.{name} }}}}" for name in secret_names(tool_type))


def _render_automated_workflow(job: AutomatedJobSpec, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    timeout_flag = blazemeter_timeout_flag(tool_type, job.timeout_minutes, separator="\n          ")
    names = secret_names(tool_type)
    # A reusable workflow only sees the secrets its caller passes (e.g.
    # `secrets: inherit`), so it has to declare the ones it needs.
    secrets_declaration = ""
    step_env = ""
    if names:
        secrets_declaration = "\n    secrets:" + "".join(f"\n      {name}:\n        required: true" for name in names)
        step_env = "\n        env:" + _secret_env(tool_type)
    return f"""name: {yaml_dquote(f"Performance Automated Job - {job.name}")}

on:
  workflow_call:{secrets_declaration}

jobs:
  {job_id}:
    runs-on: ubuntu-latest
    timeout-minutes: {job.timeout_minutes}
    steps:
      - uses: actions/checkout@v4
      - name: Run performance wrapper{step_env}
        run: >
          ./scripts/run-{tool_type}.sh
          --test-case {shell_quote(job.test_case)}{timeout_flag}
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: {yaml_dquote(f"performance-results-{job.name}")}
          path: run-output/
"""
