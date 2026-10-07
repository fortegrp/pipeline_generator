from __future__ import annotations

from pipeline_generator.config.placeholders import TODO_VALUE
from pipeline_generator.config.schema import LOAD_PROFILE_FIELDS, LOAD_PROFILE_TOOLS
from pipeline_generator.generator.generic_model import (
    AutomatedJobSpec,
    GenericPipelinePackage,
    InputOption,
    LoadInput,
    ManualPipelineSpec,
    PipelineInput,
)


def _load_default(load_profile: dict, name: str) -> str:
    value = load_profile.get(name)
    if value is None or value == "":
        return "" if name == "test_type" else TODO_VALUE
    return str(value)  # not `or`: throughput_rps / ramp_up_seconds may legitimately be 0


def build_generic_package(config: dict) -> GenericPipelinePackage:
    setup = config["setup"]
    cicd_type = config["cicd"]["type"]
    tool_type = config["tool"]["type"]
    environments = [
        InputOption(value=item["key"], identifier=item.get("identifier", TODO_VALUE))
        for item in config["catalog"]["environments"]
    ]
    scenarios = [
        InputOption(value=item["key"], identifier=item.get("identifier", TODO_VALUE))
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
                    environment_ref=job["environment_ref"],
                    scenario_ref=job["scenario_ref"],
                )
            )

    load_profile = config.get("load_profile", {})
    load_names = ("test_type", *LOAD_PROFILE_FIELDS) if tool_type in LOAD_PROFILE_TOOLS else ("test_type",)
    load_inputs = [LoadInput(name, _load_default(load_profile, name)) for name in load_names]

    return GenericPipelinePackage(
        setup_id=setup["id"],
        cicd_type=cicd_type,
        tool_type=tool_type,
        manual_pipeline=manual_pipeline,
        automated_jobs=automated_jobs,
        environments=environments,
        scenarios=scenarios,
        load_inputs=load_inputs,
    )
