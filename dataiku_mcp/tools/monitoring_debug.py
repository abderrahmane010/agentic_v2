"""
Debugging and monitoring tools for Dataiku MCP integration.
"""

from collections import Counter
from typing import Any, Optional

from dataiku_mcp.client import get_project
from dataiku_mcp.tools._common import (
    JOB_TERMINAL_STATES,
    error,
    job_summary,
    ms_to_iso,
    ok,
    scenario_run_summary,
)

_FAILED = ("FAILED", "ABORTED")
_SUCCESS = ("SUCCESS", "WARNING", "DONE")


def _job_list_entry(job: dict[str, Any]) -> dict[str, Any]:
    """Normalise an entry of DSSProject.list_jobs()."""
    base = job.get("baseStatus", job) or {}
    definition = base.get("def", job.get("def", {})) or {}
    return {
        "kind": "job",
        "id": definition.get("id") or job.get("jobId"),
        "name": definition.get("name") or definition.get("id"),
        "outcome": base.get("state") or job.get("state"),
        "start_time": ms_to_iso(
            base.get("jobStartTime") or definition.get("initiationTimestamp")
        ),
        "end_time": ms_to_iso(base.get("jobEndTime")),
        "initiator": definition.get("initiator"),
        "trigger_type": definition.get("type"),
    }


def get_recent_runs(
    project_key: str,
    limit: int = 50,
    status_filter: Optional[str] = None,
) -> dict[str, Any]:
    """
    Get recent scenario runs and jobs of a project, most recent first.

    Args:
        project_key: The project key
        limit: Number of recent runs to return
        status_filter: Filter by outcome (SUCCESS, WARNING, FAILED, ABORTED,
            DONE, RUNNING...)

    Returns:
        Dict containing recent runs and summary
    """
    try:
        project = get_project(project_key)
        runs: list[dict[str, Any]] = []
        warnings: list[str] = []

        for scenario in project.list_scenarios():
            scenario_id = scenario.get("id")
            try:
                for run in project.get_scenario(scenario_id).get_last_runs(limit=limit):
                    entry = scenario_run_summary(run)
                    runs.append(
                        {
                            "kind": "scenario",
                            "id": scenario_id,
                            "name": scenario.get("name"),
                            **entry,
                            "outcome": entry["outcome"] or "RUNNING",
                        }
                    )
            except Exception as e:
                warnings.append(f"Scenario {scenario_id}: {e}")

        try:
            runs.extend(_job_list_entry(j) for j in project.list_jobs())
        except Exception as e:
            warnings.append(f"Jobs: {e}")

        if status_filter:
            runs = [r for r in runs if r["outcome"] == status_filter.upper()]

        runs.sort(key=lambda r: r["start_time"] or "", reverse=True)
        runs = runs[:limit]

        outcomes = Counter(r["outcome"] for r in runs)
        failed = sum(outcomes[o] for o in _FAILED)
        success = sum(outcomes[o] for o in _SUCCESS)
        finished = failed + success

        result = ok(
            project_key=project_key,
            runs=runs,
            recent_failures=[r for r in runs if r["outcome"] in _FAILED][:10],
            summary={
                "total_runs": len(runs),
                "success_runs": success,
                "failed_runs": failed,
                "success_rate": round(success / finished * 100, 1)
                if finished
                else None,
                "outcome_summary": dict(outcomes),
                "kind_summary": dict(Counter(r["kind"] for r in runs)),
            },
        )
        if warnings:
            result["warnings"] = warnings
        return result

    except Exception as e:
        return error(f"Failed to get recent runs of '{project_key}': {e}")


def get_job_details(
    project_key: str, job_id: str, max_log_chars: int = 20000
) -> dict[str, Any]:
    """
    Get the state, activities and log of a job.

    Args:
        project_key: The project key
        job_id: Job identifier
        max_log_chars: Maximum log size returned (end of the log is kept)

    Returns:
        Dict with job details or error message
    """
    try:
        job = get_project(project_key).get_job(job_id)
        status = job.get_status() or {}

        activities = [
            {
                "id": activity_id,
                "state": (activity or {}).get("state"),
                "recipe": (activity or {}).get("recipeName"),
                "target": (activity or {}).get("target"),
            }
            for activity_id, activity in (status.get("activities") or {}).items()
        ]

        log = None
        log_error = None
        try:
            log = job.get_log()
            if log and len(log) > max_log_chars:
                log = (
                    f"[... {len(log) - max_log_chars} chars truncated ...]\n"
                    + log[-max_log_chars:]
                )
        except Exception as e:
            log_error = str(e)

        result = ok(
            job=job_summary(job),
            activities=activities,
            log=log,
        )
        if log_error:
            result["warnings"] = [f"Could not retrieve log: {log_error}"]
        return result

    except Exception as e:
        return error(f"Failed to get details of job '{job_id}': {e}")


def cancel_running_jobs(project_key: str, job_ids: list[str]) -> dict[str, Any]:
    """
    Abort running jobs.

    Args:
        project_key: The project key
        job_ids: List of job IDs to abort

    Returns:
        Dict listing aborted jobs and failures
    """
    try:
        project = get_project(project_key)
    except Exception as e:
        return error(f"Failed to access project '{project_key}': {e}")

    cancelled, failed = [], []
    for job_id in job_ids:
        try:
            job = project.get_job(job_id)
            state = job_summary(job)["state"]
            if state in JOB_TERMINAL_STATES:
                failed.append(
                    {"job_id": job_id, "error": f"Job is not running (state: {state})"}
                )
                continue
            job.abort()
            cancelled.append({"job_id": job_id, "previous_state": state})
        except Exception as e:
            failed.append({"job_id": job_id, "error": str(e)})

    result = ok if not failed else error
    return result(
        message=f"{len(cancelled)} job(s) aborted, {len(failed)} failure(s)",
        cancelled_jobs=cancelled,
        failed_cancellations=failed,
    )
