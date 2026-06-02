from __future__ import annotations

from datetime import datetime, timezone


def build_summary(
    tool: str,
    environment: str,
    scenario: str,
    run_status: str,
    remote_run_id: str,
    report_link: str,
    artifact_download_status: str,
    started_at: datetime,
    finished_at: datetime,
) -> dict:
    return {
        "tool": tool,
        "environment": environment,
        "scenario": scenario,
        "run_status": run_status,
        "start_time": started_at.astimezone(timezone.utc).isoformat(),
        "end_time": finished_at.astimezone(timezone.utc).isoformat(),
        "duration_seconds": int((finished_at - started_at).total_seconds()),
        "remote_run_id": remote_run_id,
        "report_link": report_link,
        "artifact_download_status": artifact_download_status,
    }
