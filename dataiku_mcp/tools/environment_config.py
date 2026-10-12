"""
Environment and configuration tools for Dataiku MCP integration.
"""

from collections import defaultdict
from typing import Any, Optional

from dataiku_mcp.client import get_client, get_project
from dataiku_mcp.tools._common import error, flat_refs, ok

_SENSITIVE_MARKERS = ("password", "passwd", "secret", "token", "key", "credential")

# Connection parameters safe to display; everything else is dropped
# (allowlist: connection params may hold encrypted secrets).
_SAFE_CONNECTION_PARAMS = (
    "host",
    "port",
    "db",
    "database",
    "defaultDatabase",
    "defaultSchema",
    "schema",
    "catalog",
    "defaultCatalog",
    "warehouse",
    "role",
    "httpPath",
    "bucket",
    "chbucket",
    "path",
    "root",
    "container",
    "storageAccount",
    "region",
    "namingRule",
)


def _is_sensitive(name: str) -> bool:
    return any(marker in name.lower() for marker in _SENSITIVE_MARKERS)


def _mask(variables: dict[str, Any]) -> dict[str, Any]:
    return {
        k: "***HIDDEN***" if _is_sensitive(k) else v for k, v in variables.items()
    }


def get_code_environments(project_key: Optional[str] = None) -> dict[str, Any]:
    """
    List code environments, and the defaults of a project if given.

    Args:
        project_key: Project identifier (optional)

    Returns:
        Dict containing code environments information
    """
    try:
        environments = [
            {
                "name": env.get("envName"),
                "language": env.get("envLang"),
                "deployment_mode": env.get("deploymentMode"),
                "owner": env.get("owner"),
            }
            for env in get_client().list_code_envs()
        ]
        result = ok(
            environments=environments, environment_count=len(environments)
        )
    except Exception as e:
        return error(f"Failed to list code environments: {e}")

    if project_key:
        try:
            raw = get_project(project_key).get_settings().get_raw()
            code_envs = (raw.get("settings") or {}).get("codeEnvs") or {}
            result["project_code_envs"] = {
                lang: {
                    "mode": (code_envs.get(lang) or {}).get("mode"),
                    "env": (code_envs.get(lang) or {}).get("envName"),
                }
                for lang in ("python", "r")
            }
        except Exception as e:
            result["warnings"] = [f"Could not read project code envs: {e}"]

    return result


def get_project_variables(project_key: str) -> dict[str, Any]:
    """
    Get project variables (sensitive names masked) and metadata.

    Args:
        project_key: The project key

    Returns:
        Dict containing project variables and metadata
    """
    try:
        project = get_project(project_key)
        variables = project.get_variables()
        metadata = project.get_metadata()

        standard = variables.get("standard") or {}
        local = variables.get("local") or {}

        return ok(
            project_info={
                "key": project_key,
                "name": metadata.get("label", project_key),
                "description": metadata.get("description", ""),
                "short_description": metadata.get("shortDesc", ""),
                "tags": metadata.get("tags", []),
                "custom_fields": metadata.get("customFields", {}),
            },
            variables={"standard": _mask(standard), "local": _mask(local)},
            variable_stats={
                "standard_count": len(standard),
                "local_count": len(local),
                "masked": sorted(
                    k for k in (*standard, *local) if _is_sensitive(k)
                ),
            },
        )

    except Exception as e:
        return error(f"Failed to get variables of '{project_key}': {e}")


def get_connections(project_key: Optional[str] = None) -> dict[str, Any]:
    """
    List DSS connections, and the connections used by a project if given.

    Only an allowlist of connection parameters (host, database, schema...)
    is returned; reading connection details needs DSS admin rights.

    Args:
        project_key: Project identifier (optional)

    Returns:
        Dict containing connection information
    """
    warnings = []
    try:
        listing = get_client().list_connections()
    except Exception as e:
        return error(f"Failed to list connections: {e}")

    connections = []
    for name, item in sorted(listing.items()):
        params = item.get("params") or {}
        connections.append(
            {
                "name": name,
                "type": item.get("type"),
                "allow_write": item.get("allowWrite"),
                "allow_managed_datasets": item.get("allowManagedDatasets"),
                "parameters": {
                    k: params[k] for k in _SAFE_CONNECTION_PARAMS if k in params
                },
            }
        )

    by_type = defaultdict(list)
    for conn in connections:
        by_type[conn["type"]].append(conn["name"])

    result = ok(
        connections=connections,
        connection_count=len(connections),
        connection_types=dict(by_type),
    )

    if project_key:
        try:
            project = get_project(project_key)
            dataset_connection = {
                d.get("name"): (d.get("params") or {}).get("connection")
                for d in project.list_datasets()
            }
            usage: dict[str, dict[str, list[str]]] = {}
            for dataset, connection in dataset_connection.items():
                key = connection or "(none)"
                usage.setdefault(key, {"datasets": [], "recipes": []})
                usage[key]["datasets"].append(dataset)

            for recipe in project.list_recipes():
                refs = flat_refs(recipe.get("inputs")) + flat_refs(
                    recipe.get("outputs")
                )
                for ref in refs:
                    if ref in dataset_connection:
                        key = dataset_connection[ref] or "(none)"
                        if recipe.get("name") not in usage[key]["recipes"]:
                            usage[key]["recipes"].append(recipe.get("name"))

            result["project_connection_usage"] = usage
        except Exception as e:
            warnings.append(f"Could not compute project usage: {e}")

    if warnings:
        result["warnings"] = warnings
    return result
