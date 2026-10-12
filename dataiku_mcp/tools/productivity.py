"""
Productivity tools for Dataiku MCP integration.
"""

import json
import re
from typing import Any, Optional

import yaml

from dataiku_mcp.client import get_project
from dataiku_mcp.tools import datasets, recipes, scenarios
from dataiku_mcp.tools._common import CODE_RECIPE_TYPES, error, flat_refs, ok
from dataiku_mcp.tools.environment_config import _is_sensitive, _mask

DUPLICATION_MODES = ("MINIMAL", "SHARING", "FULL", "NONE")


def duplicate_project_structure(
    source_project_key: str,
    target_project_key: str,
    include_data: bool = False,
    target_project_name: Optional[str] = None,
    connection_remapping: Optional[dict[str, str]] = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Duplicate a project with the native DSS duplication.

    Managed datasets are re-created in the target project; with
    include_data=False (mode MINIMAL) they are empty, with include_data=True
    (mode FULL) their data is copied as well.

    Args:
        source_project_key: Source project identifier
        target_project_key: Key of the new project (must not exist)
        include_data: Whether to copy the data of managed datasets
        target_project_name: Name of the new project (defaults to its key)
        connection_remapping: {source connection: target connection}
        dry_run: Only describe what would be duplicated (default True)

    Returns:
        Dict containing duplication results
    """
    mode = "FULL" if include_data else "MINIMAL"

    try:
        source = get_project(source_project_key)
        summary = {
            "source_project": source_project_key,
            "target_project": target_project_key,
            "duplication_mode": mode,
            "datasets": len(source.list_datasets()),
            "recipes": len(source.list_recipes()),
            "scenarios": len(source.list_scenarios()),
            "connection_remapping": connection_remapping or {},
        }

        if dry_run:
            return ok(
                dry_run=True,
                duplication_summary=summary,
                message="Dry run: call again with dry_run=false to duplicate",
            )

        remapping = {
            "connections": [
                {"source": s, "target": t}
                for s, t in (connection_remapping or {}).items()
            ]
        }
        result = source.duplicate(
            target_project_key,
            target_project_name or target_project_key,
            duplication_mode=mode,
            remapping=remapping,
        )

        return ok(
            dry_run=False,
            duplication_summary=summary,
            dss_result=result,
            message=(
                f"Project '{source_project_key}' duplicated to "
                f"'{target_project_key}'"
            ),
        )

    except Exception as e:
        return error(f"Failed to duplicate project '{source_project_key}': {e}")


def export_project_config(
    project_key: str, format: str = "json"
) -> dict[str, Any]:
    """
    Export the configuration of a project: metadata, variables (sensitive
    names masked), datasets, recipes (with code) and scenarios.

    Args:
        project_key: The project key
        format: Export format ('json' or 'yaml')

    Returns:
        Dict with the configuration (as a dict and as a serialized string)
    """
    if format.lower() not in ("json", "yaml"):
        return error("format must be 'json' or 'yaml'", "invalid_argument")

    try:
        project = get_project(project_key)
        metadata = project.get_metadata()
        variables = project.get_variables()
        warnings = []

        config: dict[str, Any] = {
            "project": {
                "key": project_key,
                "name": metadata.get("label", project_key),
                "description": metadata.get("description", ""),
                "tags": metadata.get("tags", []),
            },
            "variables": {
                "standard": _mask(variables.get("standard") or {}),
                "local": _mask(variables.get("local") or {}),
            },
            "datasets": [],
            "recipes": [],
            "scenarios": [],
        }

        for item in project.list_datasets():
            params = item.get("params") or {}
            config["datasets"].append(
                {
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "managed": item.get("managed", False),
                    "params": {
                        k: v for k, v in params.items() if not _is_sensitive(k)
                    },
                    "format_type": item.get("formatType"),
                    "partitioning": item.get("partitioning"),
                    "schema": (item.get("schema") or {}).get("columns", []),
                }
            )

        for item in project.list_recipes():
            name = item.get("name")
            entry = {
                "name": name,
                "type": item.get("type"),
                "inputs": flat_refs(item.get("inputs")),
                "outputs": flat_refs(item.get("outputs")),
            }
            try:
                settings = project.get_recipe(name).get_settings()
                entry["params"] = settings.raw_params
                if settings.type in CODE_RECIPE_TYPES:
                    entry["code"] = settings.str_payload
                else:
                    entry["payload"] = settings.obj_payload
            except Exception as e:
                warnings.append(f"Recipe {name}: {e}")
            config["recipes"].append(entry)

        for item in project.list_scenarios():
            scenario_id = item.get("id")
            try:
                settings = project.get_scenario(scenario_id).get_settings()
                raw = settings.get_raw()
                entry = {
                    "id": scenario_id,
                    "name": raw.get("name"),
                    "type": raw.get("type"),
                    "active": settings.active,
                    "triggers": settings.raw_triggers,
                    "reporters": settings.raw_reporters,
                }
                if raw.get("type") == "custom_python":
                    entry["script"] = settings.code
                else:
                    entry["steps"] = settings.raw_steps
            except Exception as e:
                warnings.append(f"Scenario {scenario_id}: {e}")
                entry = {"id": scenario_id, "name": item.get("name")}
            config["scenarios"].append(entry)

        if format.lower() == "yaml":
            content = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
        else:
            content = json.dumps(config, indent=2, ensure_ascii=False, default=str)

        result = ok(
            project_key=project_key,
            format=format.lower(),
            stats={
                "datasets": len(config["datasets"]),
                "recipes": len(config["recipes"]),
                "scenarios": len(config["scenarios"]),
            },
            config=config,
            content=content,
        )
        if warnings:
            result["warnings"] = warnings
        return result

    except Exception as e:
        return error(f"Failed to export config of '{project_key}': {e}")


_UPDATERS = {
    "datasets": ("name", datasets.update_dataset),
    "recipes": ("name", recipes.update_recipe),
    "scenarios": ("id", scenarios.update_scenario),
}


def batch_update_objects(
    project_key: str,
    object_type: str,
    pattern: str,
    updates: dict[str, Any],
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Apply the same update to every object whose name matches a pattern.

    Args:
        project_key: The project key
        object_type: 'datasets', 'recipes' or 'scenarios'
        pattern: Regular expression matched against the object name
            (scenario: id or name)
        updates: Fields accepted by update_dataset / update_recipe /
            update_scenario (e.g. {"tags": [...], "description": "..."})
        dry_run: Only list the matching objects (default True)

    Returns:
        Dict containing update results
    """
    kind = object_type.lower()
    if kind not in _UPDATERS:
        return error(
            f"Unsupported object type: {object_type}. "
            f"Supported types: {sorted(_UPDATERS)}",
            "invalid_argument",
        )
    if not updates:
        return error("updates must not be empty", "invalid_argument")
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return error(f"Invalid pattern: {e}", "invalid_argument")

    try:
        project = get_project(project_key)
        listing = {
            "datasets": project.list_datasets,
            "recipes": project.list_recipes,
            "scenarios": project.list_scenarios,
        }[kind]()
    except Exception as e:
        return error(f"Failed to list {kind} of '{project_key}': {e}")

    id_field, updater = _UPDATERS[kind]
    matches = [
        item.get(id_field)
        for item in listing
        if regex.search(item.get(id_field) or "")
        or regex.search(item.get("name") or "")
    ]

    if dry_run:
        return ok(
            dry_run=True,
            matching_objects=matches,
            match_count=len(matches),
            message="Dry run: call again with dry_run=false to apply",
        )

    updated, failed = [], []
    for object_id in matches:
        result = updater(project_key, object_id, **updates)
        if result.get("status") == "ok":
            updated.append(object_id)
        else:
            failed.append({"id": object_id, "error": result.get("message")})

    respond = ok if not failed else error
    return respond(
        message=f"{len(updated)} {kind} updated, {len(failed)} failure(s)",
        dry_run=False,
        updated_objects=updated,
        failed_updates=failed,
    )
