from __future__ import annotations

from pipeline_generator.generator.generic_model import AutomatedJobSpec, GenericPipelinePackage, InputOption, ManualPipelineSpec, PipelineInput


def build_generic_package(config: dict) -> GenericPipelinePackage:
    setup = config["setup"]
    cicd_type = config["cicd"]["type"]
    environments = [
        InputOption(value=item["key"], display_name=item["name"])
        for item in config["catalog"]["environments"]
    ]
    scenarios = [
        InputOption(value=item["key"], display_name=item["name"])
        for item in config["catalog"]["scenarios"]
    ]

    manual_pipeline = None
    if setup["generation_mode"] in {"manual_only", "both"} and config["manual_pipeline"]["enabled"]:
        manual_pipeline = ManualPipelineSpec(
            name=config["manual_pipeline"]["name"],
            inputs=[
                PipelineInput("environment", "Environment", "dropdown", environments),
                PipelineInput("scenario", "Scenario", "dropdown", scenarios),
            ],
            timeout_minutes=int(config["manual_pipeline"]["timeout_minutes"]),
            run_command=[
                "pipeline-generator",
                "run",
                "--config",
                "customer.yaml",
                "--mode",
                "manual",
                "--environment",
                "${environment}",
                "--scenario",
                "${scenario}",
            ],
        )

    automated_jobs = []
    if setup["generation_mode"] in {"automated_only", "both"}:
        for job in config["automated_jobs"]:
            if not job.get("enabled", True):
                continue
            automated_jobs.append(
                AutomatedJobSpec(
                    name=job["name"],
                    timeout_minutes=int(job.get("timeout_minutes", 240)),
                    fixed_arguments={
                        "job": job["name"],
                    },
                    run_command=[
                        "pipeline-generator",
                        "run",
                        "--config",
                        "customer.yaml",
                        "--mode",
                        "automated",
                        "--job",
                        job["name"],
                    ],
                )
            )

    return GenericPipelinePackage(
        setup_id=setup["id"],
        cicd_type=cicd_type,
        manual_pipeline=manual_pipeline,
        automated_jobs=automated_jobs,
    )

