"""
Advanced scenario management tools for Dataiku MCP integration.
"""

import copy
from typing import Any, Optional

from dataiku_mcp.client import get_project
from dataiku_mcp.tools._common import error, ok, scenario_run_summary

# Keys of a scenario definition that DSS assigns itself.
_SCENARIO_OWN_KEYS = ("id", "projectKey", "name", "versionTag", "creationTag")


def _tail(text: Optional[str], max_chars: int) -> Optional[str]:
    """Keep the end of a log (errors are usually at the end)."""
    if not text or len(text) <= max_chars:
        return text
    return f"[... {len(text) - max_chars} chars truncated ...]\n" + text[-max_chars:]


def _first_error(obj: Any) -> Optional[dict[str, Any]]:
    """first_error_details of a run or step, None if not available."""
    try:
        return obj.first_error_details
    except (KeyError, TypeError, AttributeError):
        return None


def get_scenario_logs(
    project_key: str,
    scenario_id: str,
    run_id: Optional[str] = None,
    max_chars: int = 20000,
) -> dict[str, Any]:
    """
    Get the log, step outcomes and first error of a scenario run.

    Args:
        project_key: The project key
        scenario_id: ID of the scenario
        run_id: Specific run ID (defaults to latest)
        max_chars: Maximum size of each log returned (end of the log is kept)

    Returns:
        Dict containing run information, step details and logs
    """
    try:
        project = get_project(project_key)
        scenario = project.get_scenario(scenario_id)

        if run_id:
            run = scenario.get_run(run_id)
        else:
            runs = scenario.get_last_runs(limit=1)
            if not runs:
                return ok(
                    scenario_id=scenario_id,
                    run_info=None,
                    steps=[],
                    message="No runs found for this scenario",
                )
            run = runs[0]

        details = run.get_details()
        steps = []
        job_ids = []
        for i, step in enumerate(details.steps if "stepRuns" in details else []):
            step_def = step.get("step", {}) or {}
            step_jobs = [
                item.get("jobId")
                for item in step.get("additionalReportItems", []) or []
                if item.get("type") == "JOB_EXECUTED"
            ]
            job_ids.extend(step_jobs)
            steps.append(
                {
                    "index": i,
                    "name": step_def.get("name"),
                    "type": step_def.get("type"),
                    "outcome": (step.get("result") or {}).get("outcome"),
                    "job_ids": step_jobs,
                    "error": _first_error(step),
                }
            )

        warnings = []
        try:
            scenario_log = _tail(run.get_log(), max_chars)
        except Exception as e:
            scenario_log = None
            warnings.append(f"Could not retrieve scenario log: {e}")

        job_logs = []
        for job_id in job_ids:
            try:
                job_logs.append(
                    {
                        "job_id": job_id,
                        "log": _tail(project.get_job(job_id).get_log(), max_chars),
                    }
                )
            except Exception as e:
                warnings.append(f"Could not retrieve log of job {job_id}: {e}")

        result = ok(
            scenario_id=scenario_id,
            run_info=scenario_run_summary(run),
            first_error=_first_error(details) if steps else None,
            steps=steps,
            scenario_log=scenario_log,
            job_logs=job_logs,
        )
        if warnings:
            result["warnings"] = warnings
        return result

    except Exception as e:
        return error(f"Failed to get scenario logs for '{scenario_id}': {e}")


def get_scenario_steps(project_key: str, scenario_id: str) -> dict[str, Any]:
    """
    Get detailed step configuration including Python code.

    Args:
        project_key: The project key
        scenario_id: ID of the scenario

    Returns:
        Dict containing step configurations (or the script of a
        custom_python scenario)
    """
    try:
        settings = get_project(project_key).get_scenario(scenario_id).get_settings()
        raw = settings.get_raw()

        scenario_info = {
            "id": scenario_id,
            "name": raw.get("name"),
            "type": raw.get("type"),
            "active": settings.active,
        }

        if raw.get("type") == "custom_python":
            return ok(scenario_info=scenario_info, script=settings.code, steps=[])

        steps = []
        for i, step in enumerate(settings.raw_steps):
            params = step.get("params", {}) or {}
            info = {
                "index": i,
                "id": step.get("id"),
                "name": step.get("name"),
                "type": step.get("type"),
                "enabled": step.get("enabled", True),
                "run_condition": step.get("runConditionType"),
                "params": params,
            }
            if step.get("type") == "custom_python":
                info["code"] = params.get("script", "")
            elif step.get("type") in ("build_flowitem", "check_dataset", "compute_metrics"):
                info["items"] = [
                    {
                        "type": item.get("type"),
                        "project_key": item.get("projectKey"),
                        "item_id": item.get("itemId"),
                        "partitions": item.get("partitionsSpec"),
                    }
                    for item in params.get("builds", params.get("items", [])) or []
                ]
            steps.append(info)

        return ok(scenario_info=scenario_info, steps=steps, step_count=len(steps))

    except Exception as e:
        return error(f"Failed to get scenario steps for '{scenario_id}': {e}")


def clone_scenario(
    project_key: str,
    source_scenario_id: str,
    new_scenario_name: str,
    modifications: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Clone an existing scenario (steps, triggers, reporters, script).

    The clone is created INACTIVE (its triggers do not fire) unless
    modifications contains "active": true, so that it never runs twice the
    production jobs of the source scenario by accident.

    Args:
        project_key: The project key
        source_scenario_id: Source scenario ID to clone
        new_scenario_name: Name for the new scenario
        modifications: Optional changes: description, tags, active,
            step_modifications {index: {params, code, name, enabled}},
            remove_triggers [indexes], new_triggers [raw trigger dicts]

    Returns:
        Dict containing cloned scenario information
    """
    modifications = modifications or {}

    try:
        project = get_project(project_key)
        source_settings = project.get_scenario(source_scenario_id).get_settings()
        definition = copy.deepcopy(source_settings.get_raw())
        scenario_type = definition.get("type")
        for key in _SCENARIO_OWN_KEYS:
            definition.pop(key, None)

        definition["active"] = bool(modifications.get("active", False))
        for field in ("description", "tags"):
            if field in modifications:
                definition[field] = modifications[field]

        steps = (definition.get("params") or {}).get("steps", [])
        for index, changes in (modifications.get("step_modifications") or {}).items():
            index = int(index)  # JSON object keys are strings
            if not 0 <= index < len(steps):
                return error(f"Step index {index} is out of range", "invalid_argument")
            step = steps[index]
            if "params" in changes:
                step.setdefault("params", {}).update(changes["params"])
            if "code" in changes:
                if step.get("type") != "custom_python":
                    return error(f"Step {index} is not a custom_python step", "invalid_argument")
                step.setdefault("params", {})["script"] = changes["code"]
            for field in ("name", "enabled"):
                if field in changes:
                    step[field] = changes[field]

        triggers = definition.get("triggers", [])
        for index in sorted(modifications.get("remove_triggers", []), reverse=True):
            if 0 <= index < len(triggers):
                triggers.pop(index)
        triggers.extend(modifications.get("new_triggers", []))

        new_scenario = project.create_scenario(
            new_scenario_name, scenario_type, definition=definition
        )

        if scenario_type == "custom_python":
            new_settings = new_scenario.get_settings()
            new_settings.code = source_settings.code
            new_settings.save()

        return ok(
            source_scenario_id=source_scenario_id,
            new_scenario_id=new_scenario.id,
            new_scenario_name=new_scenario_name,
            active=definition["active"],
            step_count=len(steps),
            trigger_count=len(triggers),
            modifications_applied=sorted(modifications),
        )

    except Exception as e:
        return error(f"Failed to clone scenario '{source_scenario_id}': {e}")
