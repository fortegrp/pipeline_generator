from __future__ import annotations

from pipeline_generator.generator.generic_model import AutomatedJobSpec, GenericPipelinePackage
from pipeline_generator.renderers.quoting import safe_filename_component


def _todo_lines(tool_type: str, script_name: str) -> list[str]:
    lines = [
        "- Fill secret variable names in the generated pipeline files.",
        "- Replace TODO placeholders in `customer.yaml`.",
    ]
    if tool_type == "blazemeter":
        lines.append(
            "- Set `BLAZEMETER_API_KEY_ID`/`BLAZEMETER_API_KEY_SECRET` as secrets for the generated pipeline."
        )
        lines.append(f"- Ensure `jq` is installed on whatever agent/runner executes `{script_name}`.")
    elif tool_type not in {"jmeter", "loadrunner_professional"}:
        lines.append("- Implement remote tool connectivity details required by the target customer.")
    return lines


def _connection_details_lines(config: dict) -> list[str]:
    tool_type = config["tool"]["type"]
    connection = config.get("tool", {}).get("connection", {})
    if tool_type == "jmeter":
        return [
            f"- Test plan: `{connection.get('test_plan_path', '')}`",
            f"- JMeter binary: `{connection.get('jmeter_bin') or 'jmeter'}`",
        ]
    if tool_type == "loadrunner_professional":
        return [f"- `wlrun` path: `{connection.get('wlrun_path') or 'wlrun'}`"]
    if tool_type == "blazemeter":
        return [
            f"- Base URL: `{connection.get('base_url', '')}`",
            f"- Workspace ID: `{connection.get('workspace_id', '')}`",
            f"- Project ID: `{connection.get('project_id', '')}`",
        ]
    return ["- No connection details recorded for this tool type."]


def _manual_usage_lines(cicd_type: str, script_name: str) -> list[str]:
    if cicd_type == "github_actions":
        return [
            "- In GitHub, open the **Actions** tab and select the manual performance workflow.",
            "- Click **Run workflow**, choose an environment and scenario from the dropdowns, "
            "then click **Run workflow** again to start.",
            "- Review the run's summary and download the published `run-output` artifact once it finishes.",
        ]
    if cicd_type == "azure_devops":
        return [
            "- In Azure DevOps, open **Pipelines** and select the manual performance pipeline.",
            "- Click **Run pipeline**, fill in the `environment`/`scenario` parameters, then click **Run**.",
            "- Review the run's summary and download the published `run-output` pipeline artifact once "
            "it finishes.",
        ]
    if cicd_type == "jenkins":
        return [
            "- In Jenkins, open the manual performance job (`Jenkinsfile.performance-manual`).",
            "- Click **Build with Parameters**, choose an environment and scenario, then click **Build**.",
            "- Review the build's console output and archived `run-output` artifacts once it finishes.",
        ]
    return [
        f"- Trigger the generated manual pipeline and pass `--environment`/`--scenario` through to "
        f"`{script_name}`.",
    ]


def _automated_job_lines(cicd_type: str, job: AutomatedJobSpec) -> list[str]:
    job_slug = safe_filename_component(job.name)
    if cicd_type == "github_actions":
        return [
            f"- **{job.name}**: reference the reusable workflow "
            f"`.github/workflows/performance-automated-{job_slug}.yml` from your deployment workflow "
            f"with `uses: ./.github/workflows/performance-automated-{job_slug}.yml` (or the full "
            "`owner/repo/.github/workflows/...@ref` path if calling it from another repository).",
        ]
    if cicd_type == "azure_devops":
        return [
            f"- **{job.name}**: reference the generated `azure/performance-automated-{job_slug}.yml` "
            "template from your deployment pipeline with a `template:` step.",
        ]
    if cicd_type == "jenkins":
        return [
            f"- **{job.name}**: call `Jenkinsfile.performance-automated-{job_slug}` from your deployment "
            f"pipeline, e.g. `build job: 'performance-automated-{job_slug}'`, or copy its stages into "
            "your existing Jenkinsfile.",
        ]
    return [f"- **{job.name}**: reference the generated automated job from your deployment workflow."]


def _artifacts_lines(tool_type: str) -> list[str]:
    lines = [
        "All runs write into `run-output/<environment_slug>_<scenario_slug>/` in the pipeline's working "
        "directory, which the generated pipeline publishes/archives as a build artifact:",
        "",
    ]
    if tool_type == "jmeter":
        lines.extend(
            [
                "- `results.jtl`: raw JMeter sample results.",
                "- `report/`: JMeter's generated HTML dashboard (open `report/index.html`).",
            ]
        )
    elif tool_type == "loadrunner_professional":
        lines.append(
            "- LoadRunner's own results files (`wlrun`'s `-ResultName` output) — authoritative for "
            "pass/fail; see Troubleshooting about `wlrun`'s exit code."
        )
    elif tool_type == "blazemeter":
        lines.extend(
            [
                "- `summary.json`: raw BlazeMeter API summary report for the run.",
                "- `report_link.json`: `{\"master_id\": ..., \"report_url\": ...}` pointing at "
                "BlazeMeter's web UI.",
            ]
        )
    lines.append(
        "- `run-summary.json`: normalized run status, timestamps, duration, report link, and artifact "
        "status — written for every tool once the run is actually attempted."
    )
    return lines


def _troubleshooting_lines(tool_type: str, script_name: str) -> list[str]:
    lines = [
        f"- Check `run-summary.json`'s `status` (`passed`/`failed`/`error`) and `artifact_status` fields "
        "first for a quick, machine-readable verdict before digging into logs.",
        "- An `Unknown environment key: ...` / `Unknown scenario key: ...` message on stderr means the "
        f"`--environment`/`--scenario` value passed to `{script_name}` doesn't match any key in this "
        "setup's catalog — check `customer.yaml`'s `catalog` section.",
    ]
    if tool_type == "blazemeter":
        lines.append(
            f"- The status-string vocabulary and report endpoint in `{script_name}` are our best "
            "understanding of the BlazeMeter API v4 — verify against a live account before relying on "
            "this in production."
        )
    elif tool_type == "loadrunner_professional":
        lines.append(
            "- This pipeline's CI/CD job must run on an agent co-located with the LoadRunner Controller "
            "(`wlrun` must be on `PATH` there) — retarget the generated pipeline's runner/agent/pool "
            "before use."
        )
        lines.append(
            "- `wlrun`'s exit code is known to be unreliable on some LoadRunner versions/configurations "
            "(it can return 0 even when a scenario had errors) — check `run-summary.json` and the "
            "results directory's own reports for the authoritative pass/fail status."
        )
    return lines


def render_setup_readme(config: dict, package: GenericPipelinePackage) -> str:
    tool_type = config["tool"]["type"]
    cicd_type = config["cicd"]["type"]
    script_name = f"scripts/run-{tool_type}.sh"

    lines = [
        f"# {package.setup_id}",
        "",
        "Generated setup package for pipeline generation.",
        "",
        "## Setup Summary",
        "",
        f"- CI/CD: `{config['cicd']['type']}`",
        f"- Tool: `{config['tool']['type']}`",
        f"- Target repository: `{config['setup']['target_repository']}`",
        f"- Working location: `{config['setup']['working_location']}`",
        f"- Final pipeline destination: `{config['setup']['final_pipeline_destination']}`",
        "",
        "## Remaining TODOs",
        "",
        *_todo_lines(tool_type, script_name),
        "",
        "## Connection Details",
        "",
        *_connection_details_lines(config),
        "",
    ]

    if package.manual_pipeline and config["readme"]["include_manual_usage"]:
        lines.extend(
            [
                "## Manual Pipeline Usage",
                "",
                *_manual_usage_lines(cicd_type, script_name),
                "",
            ]
        )

    if package.automated_jobs and config["readme"]["include_automated_usage"]:
        job_lines: list[str] = []
        for job in package.automated_jobs:
            job_lines.extend(_automated_job_lines(cicd_type, job))
        lines.extend(
            [
                "## Automated Job Integration",
                "",
                "- Each generated automated job uses fixed environment and scenario values from "
                "`customer.yaml`.",
                *job_lines,
                "",
            ]
        )

    lines.extend(
        [
            "## Artifacts & Output",
            "",
            *_artifacts_lines(tool_type),
            "",
            "## Troubleshooting",
            "",
            *_troubleshooting_lines(tool_type, script_name),
            "",
            "## Files",
            "",
            "- `customer.yaml`: setup source of truth",
            "- generated pipeline files: CI/CD-specific assets",
            f"- `{script_name}`: the script the generated pipeline calls to run the performance test",
            "- `run-output/`: where the generated script writes results — see \"Artifacts & Output\" above",
            "- this README: setup guidance",
            "",
        ]
    )
    return "\n".join(lines)
