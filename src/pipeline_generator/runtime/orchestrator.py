from __future__ import annotations

from datetime import datetime, timezone

from pipeline_generator.adapters.base import get_adapter
from pipeline_generator.runtime.artifacts import ensure_output_dir, write_json
from pipeline_generator.runtime.summary import build_summary


def run_execution(
    config: dict,
    *,
    mode: str,
    environment: str | None,
    scenario: str | None,
    job_name: str | None,
    dry_run: bool,
) -> dict:
    tool_type = config["tool"]["type"]
    adapter = get_adapter(tool_type)
    request = _build_run_request(config, mode, environment, scenario, job_name)
    output_dir = ensure_output_dir()

    if dry_run:
        payload = {
            "mode": mode,
            "tool": tool_type,
            "request": request,
            "adapter": adapter.name,
            "dry_run": True,
        }
        write_json(output_dir / "execution-plan.json", payload)
        return payload

    started_at = datetime.now(tz=timezone.utc)
    prechecks = [check.__dict__ for check in adapter.run_prechecks(config, request)]
    run_handle = adapter.start_run(config, request)
    result = adapter.wait_for_completion(config, run_handle, request["timeout_minutes"])
    artifacts = adapter.collect_artifacts(config, result, output_dir)
    finished_at = datetime.now(tz=timezone.utc)
    summary = build_summary(
        tool=tool_type,
        environment=request["environment"],
        scenario=request["scenario"],
        run_status=result["status"],
        remote_run_id=result["remote_run_id"],
        report_link=result["report_link"],
        artifact_download_status=artifacts["status"],
        started_at=started_at,
        finished_at=finished_at,
    )
    write_json(output_dir / "summary.json", summary)
    return {
        "request": request,
        "prechecks": prechecks,
        "result": result,
        "artifacts": artifacts,
        "summary": summary,
    }


def _build_run_request(
    config: dict,
    mode: str,
    environment: str | None,
    scenario: str | None,
    job_name: str | None,
) -> dict:
    if mode == "manual":
        if not environment or not scenario:
            raise ValueError("Manual mode requires --environment and --scenario.")
        timeout_minutes = int(config["manual_pipeline"]["timeout_minutes"])
        return {
            "mode": mode,
            "environment": environment,
            "scenario": scenario,
            "timeout_minutes": timeout_minutes,
        }

    if mode == "automated":
        if not job_name:
            raise ValueError("Automated mode requires --job.")
        for job in config["automated_jobs"]:
            if job["name"] == job_name:
                return {
                    "mode": mode,
                    "job_name": job_name,
                    "environment": job["environment_ref"],
                    "scenario": job["scenario_ref"],
                    "timeout_minutes": int(job.get("timeout_minutes", 240)),
                }
        raise ValueError(f"Automated job '{job_name}' was not found.")

    raise ValueError(f"Unsupported mode: {mode}")
