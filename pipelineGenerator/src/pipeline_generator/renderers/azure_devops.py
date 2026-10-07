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
            automated_path.write_text(
                _render_automated_job(job, package.tool_type, package.runner), encoding="utf-8"
            )
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
    selectors = [target.selector for target in package.run_targets]
    test_case_values = "\n".join(f"      - {yaml_dquote(selector)}" for selector in selectors)
    test_case_default = yaml_dquote(selectors[0] if selectors else "TODO")
    timeout_flag = blazemeter_timeout_flag(
        package.tool_type, package.manual_pipeline.timeout_minutes, separator="\n          "
    )
    load_parameters = "".join(
        f"""
  - name: {item.name}
    displayName: {yaml_dquote(LOAD_PROFILE_LABELS[item.name])}
    type: string
    default: {yaml_dquote(item.default)}"""
        for item in package.load_inputs
    )
    load_env = "".join(
        f"\n          {item.env_var}: ${{{{ parameters.{item.name} }}}}" for item in package.load_inputs
    )
    load_flag_text = load_flags(package.load_inputs, separator="\n          ")
    return f"""trigger: none
pr: none

parameters:
  - name: test_case
    displayName: Environment and scenario
    type: string
    default: {test_case_default}
    values:
{test_case_values}{load_parameters}

jobs:
  - job: run_performance_test
    timeoutInMinutes: {package.manual_pipeline.timeout_minutes}
    pool:
      {_pool(package.runner)}
    steps:
      - checkout: self
      - bash: >
          ./scripts/run-{package.tool_type}.sh
          --test-case "$TEST_CASE"{load_flag_text}{timeout_flag}
        env:
          TEST_CASE: ${{{{ parameters.test_case }}}}{load_env}{_secret_env(package.tool_type)}
        displayName: Run performance wrapper
      - task: PublishPipelineArtifact@1
        condition: always()
        inputs:
          targetPath: run-output
          artifact: performance-results
"""


def _secret_env(tool_type: str) -> str:
    # Azure never exposes secret variables to scripts on its own -- each one
    # has to be mapped into the step's env explicitly.
    return "".join(f"\n          {name}: $({name})" for name in secret_names(tool_type))


def _secret_env_block(tool_type: str) -> str:
    secret_env = _secret_env(tool_type)
    return f"\n        env:{secret_env}" if secret_env else ""


_HOSTED_IMAGE = re.compile(r"(ubuntu|windows|macos|macOS)-(latest|\d[\d.]*)")


def _pool(runner: str) -> str:
    # Blank = Microsoft-hosted ubuntu-latest; a hosted image name (windows-latest,
    # ubuntu-22.04, ...) stays Microsoft-hosted; anything else is a self-hosted pool.
    if not runner:
        return "vmImage: ubuntu-latest"
    if _HOSTED_IMAGE.fullmatch(runner):
        return f"vmImage: {yaml_dquote(runner)}"
    return f"name: {yaml_dquote(runner)}"


def _render_automated_job(job: AutomatedJobSpec, tool_type: str, runner: str) -> str:
    job_id = _safe_job_id(job.name)
    timeout_flag = blazemeter_timeout_flag(tool_type, job.timeout_minutes, separator="\n          ")
    # dependsOn: jobs in one stage run in parallel unless they declare it, so
    # the including pipeline passes e.g. [deploy] to run this after the deploy.
    return f"""parameters:
  - name: dependsOn
    type: object
    default: []

jobs:
  - job: {job_id}
    dependsOn: ${{{{ parameters.dependsOn }}}}
    timeoutInMinutes: {job.timeout_minutes}
    pool:
      {_pool(runner)}
    steps:
      - checkout: self
      - bash: >
          ./scripts/run-{tool_type}.sh
          --test-case {shell_quote(job.test_case)}{timeout_flag}{_secret_env_block(tool_type)}
        displayName: Run performance wrapper
      - task: PublishPipelineArtifact@1
        condition: always()
        inputs:
          targetPath: run-output
          artifact: {yaml_dquote(f"performance-results-{job.name}")}
"""
