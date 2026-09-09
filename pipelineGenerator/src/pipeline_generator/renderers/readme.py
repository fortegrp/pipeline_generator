from __future__ import annotations

from pipeline_generator.generator.generic_model import GenericPipelinePackage


def render_setup_readme(config: dict, package: GenericPipelinePackage) -> str:
    tool_type = config["tool"]["type"]
    script_name = f"scripts/run-{tool_type}.sh"

    todo_lines = [
        "- Fill secret variable names in the generated pipeline files.",
        "- Replace TODO placeholders in `customer.yaml`.",
    ]
    if tool_type == "blazemeter":
        todo_lines.append(f"- Fill in the actual API/controller call in `{script_name}` (marked with `# TODO`).")
    else:
        todo_lines.append("- Implement remote tool connectivity details required by the target customer.")

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
        *todo_lines,
        "",
    ]

    if package.manual_pipeline and config["readme"]["include_manual_usage"]:
        lines.extend(
            [
                "## Manual Pipeline Usage",
                "",
                "- Trigger the generated manual pipeline from the CI/CD UI.",
                "- Select an environment and scenario from the configured dropdowns.",
                "- Review the pipeline summary and published artifacts after completion.",
                "",
            ]
        )

    if package.automated_jobs and config["readme"]["include_automated_usage"]:
        lines.extend(
            [
                "## Automated Job Integration",
                "",
                "- Reference the generated reusable job/template from the deployment pipeline.",
                "- DevOps can place the job wherever it fits in the deployment workflow.",
                "- Each generated automated job uses fixed environment and scenario values from `customer.yaml`.",
                "",
            ]
        )

    lines.extend(
        [
            "## Files",
            "",
            "- `customer.yaml`: setup source of truth",
            "- generated pipeline files: CI/CD-specific assets",
            f"- `{script_name}`: the script the generated pipeline calls to run the performance test",
            "- this README: setup guidance",
            "",
        ]
    )
    return "\n".join(lines)

