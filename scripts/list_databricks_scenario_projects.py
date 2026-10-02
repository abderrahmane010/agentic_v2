#!/usr/bin/env python3
"""
List Dataiku DSS projects that have:
  1. At least one dataset backed by a Databricks connection, AND
  2. At least one scenario with an active ("enabled") trigger of type
     'dataset' pointing at that Databricks dataset.

Usage:
    python scripts/list_databricks_scenario_projects.py [--json]

Requires DSS_HOST / DSS_API_KEY (and optionally DSS_INSECURE_TLS) to be set,
either in the environment or in a .env file at the project root
(same convention as dataiku_mcp/client.py).
"""

import sys
import json
import argparse
from pathlib import Path

# Allow running the script directly without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataiku_mcp.client import get_client  # noqa: E402


def _databricks_connection_names(client) -> set:
    """Return the set of connection names whose type is 'Databricks'."""
    names = set()
    connections = client.list_connections()
    # dataikuapi returns a dict {connection_name: connection_def}
    if isinstance(connections, dict):
        for name, conn_def in connections.items():
            if str(conn_def.get("type", "")).lower() == "databricks":
                names.add(name)
    else:
        # Fallback in case the API returns a list of dicts
        for conn in connections:
            if str(conn.get("type", "")).lower() == "databricks":
                names.add(conn.get("name"))
    return names


def _dataset_is_databricks(dataset_def: dict, databricks_connections: set) -> bool:
    """Detect whether a dataset definition is backed by Databricks."""
    ds_type = str(dataset_def.get("type", ""))
    params = dataset_def.get("params", {}) or {}
    connection = params.get("connection")

    if ds_type.lower() == "databricks":
        return True
    if connection and connection in databricks_connections:
        return True
    return False


def find_projects_with_databricks_scenario_trigger(client):
    """
    Scan all projects and return details about those matching the criteria.

    Returns:
        list[dict]: one entry per matching project with the databricks
        datasets found and the scenarios/triggers that reference them.
    """
    databricks_connections = _databricks_connection_names(client)
    results = []

    for project_key in client.list_project_keys():
        project = client.get_project(project_key)

        try:
            datasets = project.list_datasets()
        except Exception as e:
            print(f"[WARN] {project_key}: could not list datasets ({e})", file=sys.stderr)
            continue

        databricks_datasets = {
            ds["name"]
            for ds in datasets
            if _dataset_is_databricks(ds, databricks_connections)
        }

        if not databricks_datasets:
            continue

        try:
            scenarios = project.list_scenarios()
        except Exception as e:
            print(f"[WARN] {project_key}: could not list scenarios ({e})", file=sys.stderr)
            continue

        matching_scenarios = []
        for scenario_info in scenarios:
            scenario_id = scenario_info.get("id") or scenario_info.get("name")
            scenario = project.get_scenario(scenario_id)

            try:
                settings = scenario.get_settings()
                triggers = settings.get_triggers()
            except Exception as e:
                print(
                    f"[WARN] {project_key}/{scenario_id}: could not read triggers ({e})",
                    file=sys.stderr,
                )
                continue

            for trigger in triggers:
                if not trigger.get("active", False):
                    continue
                if trigger.get("type") != "dataset":
                    continue

                trigger_dataset = (
                    trigger.get("params", {}).get("datasetName")
                    or trigger.get("datasetName")
                )
                if trigger_dataset in databricks_datasets:
                    matching_scenarios.append({
                        "scenario_id": scenario_id,
                        "scenario_name": scenario_info.get("name", scenario_id),
                        "dataset": trigger_dataset,
                        "trigger_type": trigger.get("type"),
                    })

        if matching_scenarios:
            results.append({
                "project_key": project_key,
                "databricks_datasets": sorted(databricks_datasets),
                "scenarios": matching_scenarios,
            })

    return results


def main():
    parser = argparse.ArgumentParser(
        description=(
            "List projects with a Databricks dataset and an active "
            "dataset-trigger scenario on that dataset."
        )
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of a table")
    args = parser.parse_args()

    client = get_client()
    results = find_projects_with_databricks_scenario_trigger(client)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    if not results:
        print("Aucun projet trouvé avec un dataset Databricks + scénario déclenché dessus.")
        return

    for entry in results:
        print(f"\nProjet: {entry['project_key']}")
        print(f"  Datasets Databricks: {', '.join(entry['databricks_datasets'])}")
        for sc in entry["scenarios"]:
            print(
                f"  - Scénario '{sc['scenario_name']}' ({sc['scenario_id']}) "
                f"déclenché sur le dataset '{sc['dataset']}'"
            )


if __name__ == "__main__":
    main()
