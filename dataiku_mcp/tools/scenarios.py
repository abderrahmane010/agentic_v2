"""
Scenario management tools for Dataiku DSS.

This module provides functions for creating, updating, deleting, and managing scenarios
in Dataiku DSS projects through the dataiku-api-client.
"""

from typing import Any, Optional

from dataiku_mcp.client import get_project
from dataiku_mcp.tools._common import (
    error,
    iso,
    ok,
    scenario_run_summary,
    trigger_summary,
)

SCENARIO_TYPES = ("step_based", "custom_python")
TRIGGER_TYPES = ("periodic", "hourly", "daily", "monthly", "raw")


def create_scenario(
    project_key: str,
    scenario_name: str,
    scenario_type: str,
    definition: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Create a new scenario in a Dataiku DSS project.

    Args:
        project_key: The project key where the scenario will be created
        scenario_name: Name of the scenario to create
        scenario_type: Type of scenario ('step_based' or 'custom_python')
        definition: Optional scenario definition dict. If None, defaults to {'params': {}}

    Returns:
        Dict with status and scenario details or error message
    """
    if scenario_type not in SCENARIO_TYPES:
        return error(
            f"Invalid scenario type '{scenario_type}'. "
            f"Must be one of: {list(SCENARIO_TYPES)}",
            "invalid_argument",
        )

    try:
        scenario = get_project(project_key).create_scenario(
            scenario_name,
            scenario_type,
            definition=definition or {"params": {}},
        )
        return ok(
            scenario_name=scenario_name,
            scenario_id=scenario.id,
            scenario_type=scenario_type,
            project_key=project_key,
            message=f"Scenario '{scenario_name}' created successfully",
        )

    except Exception as e:
        return error(f"Failed to create scenario '{scenario_name}': {e}")


def update_scenario(
    project_key: str, scenario_id: str, **kwargs: Any
) -> dict[str, Any]:
    """
    Update an existing scenario's settings.

    Args:
        project_key: The project key containing the scenario
        scenario_id: ID of the scenario to update
        **kwargs: Update parameters including:
            - name: New scenario name
            - description: Scenario description
            - active: Whether the scenario auto-triggers run (bool)
            - tags: List of tags
            - params: Dict merged into the scenario "params"
            - script: Python script (custom_python scenarios)
            - step_script + step_index: script of a custom_python step
              (step_based scenarios, default step_index 0)

    Returns:
        Dict with status and update details or error message
    """
    supported = {
        "name",
        "description",
        "active",
        "tags",
        "params",
        "script",
        "step_script",
        "step_index",
    }
    unknown = sorted(set(kwargs) - supported)
    if unknown:
        return error(
            f"Unsupported fields: {unknown}. Supported: {sorted(supported)}",
            "invalid_argument",
        )

    try:
        settings = get_project(project_key).get_scenario(scenario_id).get_settings()
        raw = settings.get_raw()
        updated_fields = []

        for field in ("name", "description", "tags"):
            if field in kwargs:
                raw[field] = kwargs[field]
                updated_fields.append(field)

        if "active" in kwargs:
            settings.active = bool(kwargs["active"])
            updated_fields.append("active")

        if "params" in kwargs:
            raw.setdefault("params", {}).update(kwargs["params"])
            updated_fields.append("params")

        if "script" in kwargs:
            if raw.get("type") != "custom_python":
                return error(
                    f"Scenario '{scenario_id}' is not a custom_python scenario",
                    "invalid_argument",
                )
            settings.code = kwargs["script"]
            updated_fields.append("script")

        if "step_script" in kwargs:
            steps = (raw.get("params") or {}).get("steps", [])
            index = kwargs.get("step_index", 0)
            if not 0 <= index < len(steps):
                return error(
                    f"Step index {index} is out of range (0-{len(steps) - 1})",
                    "invalid_argument",
                )
            if steps[index].get("type") != "custom_python":
                return error(
                    f"Step {index} is not a custom_python step",
                    "invalid_argument",
                )
            steps[index].setdefault("params", {})["script"] = kwargs[
                "step_script"
            ]
            updated_fields.append("step_script")

        settings.save()

        return ok(
            scenario_id=scenario_id,
            updated_fields=updated_fields,
            message=f"Scenario '{scenario_id}' updated successfully",
        )

    except Exception as e:
        return error(f"Failed to update scenario '{scenario_id}': {e}")


def delete_scenario(project_key: str, scenario_id: str) -> dict[str, Any]:
    """
    Delete a scenario from a Dataiku DSS project.

    Args:
        project_key: The project key containing the scenario
        scenario_id: ID of the scenario to delete

    Returns:
        Dict with status and deletion details or error message
    """
    try:
        scenario = get_project(project_key).get_scenario(scenario_id)
        raw = scenario.get_settings().get_raw()
        scenario.delete()

        return ok(
            deleted_scenario={
                "id": scenario_id,
                "name": raw.get("name"),
                "type": raw.get("type"),
            },
            message=f"Scenario '{scenario_id}' deleted successfully",
        )

    except Exception as e:
        return error(f"Failed to delete scenario '{scenario_id}': {e}")


def add_scenario_trigger(
    project_key: str, scenario_id: str, trigger_type: str, **params: Any
) -> dict[str, Any]:
    """
    Add a trigger to a scenario.

    Args:
        project_key: The project key containing the scenario
        scenario_id: ID of the scenario to add trigger to
        trigger_type: 'periodic', 'hourly', 'daily', 'monthly' or 'raw'
        **params: Trigger-specific parameters:
            periodic: every_minutes
            hourly: minute_of_hour, starting_hour, repeat_every, timezone
            daily: hour, minute, days (list of day names), repeat_every,
                timezone
            monthly: day, hour, minute, run_on, repeat_every, timezone
            raw: trigger (a raw DSS trigger dict, e.g. copied from another
                scenario with get_scenario_info; used for dataset or SQL
                triggers)

    Returns:
        Dict with status and trigger details or error message
    """
    if trigger_type not in TRIGGER_TYPES:
        return error(
            f"Unsupported trigger type '{trigger_type}'. "
            f"Supported types: {list(TRIGGER_TYPES)}",
            "invalid_argument",
        )
    if trigger_type == "raw" and not isinstance(params.get("trigger"), dict):
        return error(
            "A 'trigger' dict is required for raw triggers",
            "invalid_argument",
        )

    try:
        settings = get_project(project_key).get_scenario(scenario_id).get_settings()
        tz = params.get("timezone", "SERVER")

        if trigger_type == "periodic":
            settings.add_periodic_trigger(
                every_minutes=params.get("every_minutes", 60)
            )
        elif trigger_type == "hourly":
            settings.add_hourly_trigger(
                minute_of_hour=params.get("minute_of_hour", 0),
                starting_hour=params.get("starting_hour", 0),
                repeat_every=params.get("repeat_every", 1),
                timezone=tz,
            )
        elif trigger_type == "daily":
            settings.add_daily_trigger(
                hour=params.get("hour", 2),
                minute=params.get("minute", 0),
                days=params.get("days"),
                repeat_every=params.get("repeat_every", 1),
                timezone=tz,
            )
        elif trigger_type == "monthly":
            settings.add_monthly_trigger(
                day=params.get("day", 1),
                hour=params.get("hour", 2),
                minute=params.get("minute", 0),
                run_on=params.get("run_on", "ON_THE_DAY"),
                repeat_every=params.get("repeat_every", 1),
                timezone=tz,
            )
        else:
            trigger = dict(params["trigger"])
            trigger.pop("id", None)  # DSS assigns a new id
            settings.raw_triggers.append(trigger)

        settings.save()
        index = len(settings.raw_triggers) - 1

        return ok(
            scenario_id=scenario_id,
            trigger=trigger_summary(settings.raw_triggers[index], index),
            message=(
                f"Trigger '{trigger_type}' added to scenario '{scenario_id}'"
            ),
        )

    except Exception as e:
        return error(f"Failed to add trigger to scenario '{scenario_id}': {e}")


def remove_scenario_trigger(
    project_key: str, scenario_id: str, trigger_idx: int
) -> dict[str, Any]:
    """
    Remove a trigger from a scenario by index.

    Args:
        project_key: The project key containing the scenario
        scenario_id: ID of the scenario to remove trigger from
        trigger_idx: Index of the trigger to remove (0-based, see
            get_scenario_info)

    Returns:
        Dict with status and removal details or error message
    """
    try:
        settings = get_project(project_key).get_scenario(scenario_id).get_settings()
        triggers = settings.raw_triggers

        if not 0 <= trigger_idx < len(triggers):
            return error(
                f"Invalid trigger index {trigger_idx}. "
                f"Scenario has {len(triggers)} trigger(s)",
                "invalid_argument",
            )

        removed = triggers.pop(trigger_idx)
        settings.save()

        return ok(
            scenario_id=scenario_id,
            removed_trigger=trigger_summary(removed, trigger_idx),
            remaining_triggers=len(triggers),
            message=(
                f"Trigger {trigger_idx} removed from scenario '{scenario_id}'"
            ),
        )

    except Exception as e:
        return error(
            f"Failed to remove trigger from scenario '{scenario_id}': {e}"
        )


def run_scenario(
    project_key: str, scenario_id: str, wait: bool = True
) -> dict[str, Any]:
    """
    Run a scenario and optionally wait for completion.

    Args:
        project_key: The project key containing the scenario
        scenario_id: ID of the scenario to run
        wait: Wait for the run to finish (False returns once it is requested)

    Returns:
        Dict with the run outcome. "status" is "error" if the run did not
        end with outcome SUCCESS (or WARNING).
    """
    try:
        scenario = get_project(project_key).get_scenario(scenario_id)

        if not wait:
            fire = scenario.run()
            return ok(
                scenario_id=scenario_id,
                trigger_run_id=fire.run_id,
                message=(
                    f"Run of scenario '{scenario_id}' requested; follow it "
                    "with get_scenario_run_history"
                ),
            )

        run = scenario.run_and_wait(no_fail=True)

    except Exception as e:
        return error(f"Failed to run scenario '{scenario_id}': {e}")

    if run is None:
        return error(
            f"Run of scenario '{scenario_id}' was cancelled before starting",
            "job_failed",
        )

    run_info = scenario_run_summary(run)
    if run_info["outcome"] not in ("SUCCESS", "WARNING"):
        return error(
            f"Scenario '{scenario_id}' ended with outcome "
            f"{run_info['outcome']}; see get_scenario_logs",
            "job_failed",
            run_info=run_info,
        )

    return ok(
        run_info=run_info,
        message=f"Scenario '{scenario_id}' ran with outcome {run_info['outcome']}",
    )


def get_scenario_info(project_key: str, scenario_id: str) -> dict[str, Any]:
    """
    Get detailed information about a scenario (settings, triggers, status).

    Args:
        project_key: The project key containing the scenario
        scenario_id: ID of the scenario to inspect

    Returns:
        Dict with scenario information or error message
    """
    try:
        scenario = get_project(project_key).get_scenario(scenario_id)
        settings = scenario.get_settings()
        raw = settings.get_raw()
        status = scenario.get_status()

        last_runs = scenario.get_last_runs(limit=1, only_finished_runs=True)

        return ok(
            scenario_info={
                "id": scenario_id,
                "name": raw.get("name"),
                "type": raw.get("type"),
                "active": settings.active,
                "description": raw.get("description", ""),
                "tags": raw.get("tags", []),
                "run_as": settings.effective_run_as,
                "step_count": len((raw.get("params") or {}).get("steps", [])),
                "triggers": [
                    trigger_summary(t, i)
                    for i, t in enumerate(settings.raw_triggers)
                ],
                "reporters": [
                    {
                        "name": r.get("name"),
                        "type": (r.get("messaging") or {}).get("type"),
                        "active": r.get("active", False),
                    }
                    for r in settings.raw_reporters
                ],
                "running": status.running,
                "next_run": iso(status.next_run),
                "last_run": (
                    scenario_run_summary(last_runs[0]) if last_runs else None
                ),
            }
        )

    except Exception as e:
        return error(f"Failed to get scenario info for '{scenario_id}': {e}")


def list_scenarios(
    project_key: str,
    scenario_type: Optional[str] = None,
    active_only: bool = False,
) -> dict[str, Any]:
    """
    List all scenarios in a project, optionally filtered by type or active status.

    Args:
        project_key: The project key to list scenarios from
        scenario_type: Optional filter ('step_based' or 'custom_python')
        active_only: Whether to list only active scenarios (default: False)

    Returns:
        Dict with list of scenarios or error message
    """
    try:
        project = get_project(project_key)
        scenarios = []
        warnings = []

        for item in project.list_scenarios():
            scenario_id = item.get("id")
            try:
                settings = project.get_scenario(scenario_id).get_settings()
            except Exception as e:
                warnings.append(f"{scenario_id}: {e}")
                continue

            raw = settings.get_raw()
            if scenario_type and raw.get("type") != scenario_type:
                continue
            if active_only and not settings.active:
                continue

            scenarios.append(
                {
                    "id": scenario_id,
                    "name": raw.get("name"),
                    "type": raw.get("type"),
                    "active": settings.active,
                    "tags": raw.get("tags", []),
                    "triggers": [
                        trigger_summary(t, i)
                        for i, t in enumerate(settings.raw_triggers)
                    ],
                }
            )

        result = ok(
            scenarios=scenarios,
            total_count=len(scenarios),
            project_key=project_key,
        )
        if warnings:
            result["warnings"] = warnings
        return result

    except Exception as e:
        return error(
            f"Failed to list scenarios in project '{project_key}': {e}"
        )


def get_scenario_run_history(
    project_key: str, scenario_id: str, limit: int = 10
) -> dict[str, Any]:
    """
    Get the run history for a scenario.

    Args:
        project_key: The project key containing the scenario
        scenario_id: ID of the scenario to get run history for
        limit: Maximum number of runs to return (default: 10)

    Returns:
        Dict with run history (most recent first) or error message
    """
    try:
        scenario = get_project(project_key).get_scenario(scenario_id)
        runs = [scenario_run_summary(r) for r in scenario.get_last_runs(limit=limit)]

        return ok(
            scenario_id=scenario_id,
            run_history=runs,
            total_runs=len(runs),
        )

    except Exception as e:
        return error(
            f"Failed to get run history for scenario '{scenario_id}': {e}"
        )
