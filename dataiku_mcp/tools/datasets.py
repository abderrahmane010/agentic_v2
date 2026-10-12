"""
Dataset management tools for Dataiku DSS.

This module provides functions for creating, updating, deleting, building and
inspecting datasets in Dataiku DSS projects through the dataiku-api-client.
"""

from typing import Any, Optional

from dataiku_mcp.client import get_project
from dataiku_mcp.tools._common import (
    BUILD_MODES,
    error,
    iso,
    job_summary,
    ok,
    wait_for_job,
)


def create_dataset(
    project_key: str,
    dataset_name: str,
    dataset_type: str,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Create a new dataset in a Dataiku DSS project.

    Args:
        project_key: The project key where the dataset will be created
        dataset_name: Name of the dataset to create
        dataset_type: 'managed', 'filesystem', 'sql', 's3', 'uploaded', or any
            raw DSS dataset type (e.g. 'HDFS', 'Snowflake')
        params: Optional parameters dict containing:
            - connection: Connection name
            - path: Path in connection (filesystem, s3)
            - table / schema / catalog: SQL table location (sql)
            - sql_type: DSS SQL dataset type, e.g. 'PostgreSQL',
              'Snowflake', 'Oracle' (required for sql)
            - bucket: Bucket name (s3, optional)
            - format_type / format_params: File format (file-based datasets)
            - store_into: Connection for managed datasets

    Returns:
        Dict with status and dataset details or error message
    """
    params = dict(params or {})
    kind = dataset_type.lower()

    try:
        project = get_project(project_key)

        if kind == "managed":
            builder = project.new_managed_dataset(dataset_name)
            builder = builder.with_store_into(
                params.get("store_into", "filesystem_managed"),
                format_option_id=params.get("format_type"),
            )
            dataset = builder.create()

        elif kind == "filesystem":
            if not params.get("path"):
                return error(
                    "Path is required for filesystem datasets",
                    "invalid_argument",
                )
            dataset = project.create_filesystem_dataset(
                dataset_name,
                params.get("connection", "filesystem_managed"),
                params["path"],
            )

        elif kind == "sql":
            missing = [
                k for k in ("connection", "table", "sql_type") if not params.get(k)
            ]
            if missing:
                return error(
                    f"Missing parameters for SQL dataset: {missing}",
                    "invalid_argument",
                )
            dataset = project.create_sql_table_dataset(
                dataset_name,
                params["sql_type"],
                params["connection"],
                params["table"],
                params.get("schema"),
                params.get("catalog"),
            )

        elif kind == "s3":
            if not params.get("connection") or not params.get("path"):
                return error(
                    "Connection and path are required for S3 datasets",
                    "invalid_argument",
                )
            dataset = project.create_s3_dataset(
                dataset_name,
                params["connection"],
                params["path"],
                params.get("bucket"),
            )

        elif kind == "uploaded":
            dataset = project.create_upload_dataset(
                dataset_name, params.get("connection")
            )

        else:
            format_type = params.pop("format_type", None)
            format_params = params.pop("format_params", None)
            dataset = project.create_dataset(
                dataset_name,
                dataset_type,
                params=params,
                formatType=format_type,
                formatParams=format_params,
            )

        # File format for file-based datasets created above.
        if kind in ("filesystem", "s3") and params.get("format_type"):
            settings = dataset.get_settings()
            settings.set_format(
                params["format_type"], params.get("format_params")
            )
            settings.save()

        return ok(
            dataset_name=dataset.name,
            dataset_type=dataset_type,
            project_key=project_key,
            message=f"Dataset '{dataset_name}' created successfully",
        )

    except Exception as e:
        return error(f"Failed to create dataset '{dataset_name}': {e}")


def update_dataset(
    project_key: str, dataset_name: str, **kwargs: Any
) -> dict[str, Any]:
    """
    Update an existing dataset's settings.

    Args:
        project_key: The project key containing the dataset
        dataset_name: Name of the dataset to update
        **kwargs: Update parameters including:
            - description, tags, custom_fields: metadata
            - format_type, format_params: file format (file-based datasets)
            - connection, path: location (file-based datasets)
            - connection, table, schema, catalog: location (SQL datasets)

    Returns:
        Dict with status and update details or error message
    """
    supported = {
        "description",
        "tags",
        "custom_fields",
        "format_type",
        "format_params",
        "connection",
        "path",
        "table",
        "schema",
        "catalog",
    }
    unknown = sorted(set(kwargs) - supported)
    if unknown:
        return error(
            f"Unsupported fields: {unknown}. Supported: {sorted(supported)}",
            "invalid_argument",
        )

    try:
        settings = get_project(project_key).get_dataset(dataset_name).get_settings()
        raw_params = settings.get_raw_params()
        updated_fields = []

        if "description" in kwargs:
            settings.description = kwargs["description"]
            updated_fields.append("description")
        if "tags" in kwargs:
            settings.tags = kwargs["tags"]
            updated_fields.append("tags")
        if "custom_fields" in kwargs:
            settings.custom_fields = {
                **(settings.custom_fields or {}),
                **kwargs["custom_fields"],
            }
            updated_fields.append("custom_fields")

        is_fs = hasattr(settings, "set_connection_and_path")
        is_sql = hasattr(settings, "set_table")

        if "format_type" in kwargs or "format_params" in kwargs:
            if not is_fs:
                return error(
                    f"Dataset '{dataset_name}' (type {settings.type}) has no "
                    "file format",
                    "invalid_argument",
                )
            settings.set_format(
                kwargs.get("format_type", settings.get_raw().get("formatType")),
                kwargs.get("format_params"),
            )
            updated_fields.append("format")

        location_keys = {"connection", "path", "table", "schema", "catalog"}
        if location_keys & set(kwargs):
            connection = kwargs.get("connection", raw_params.get("connection"))
            if is_fs:
                settings.set_connection_and_path(
                    connection, kwargs.get("path", raw_params.get("path"))
                )
            elif is_sql:
                settings.set_table(
                    connection,
                    kwargs.get("schema", raw_params.get("schema")),
                    kwargs.get("table", raw_params.get("table")),
                    kwargs.get("catalog", raw_params.get("catalog")),
                )
            else:
                return error(
                    f"Location of dataset type {settings.type} cannot be "
                    "changed with this tool",
                    "invalid_argument",
                )
            updated_fields.append("location")

        settings.save()

        return ok(
            dataset_name=dataset_name,
            updated_fields=updated_fields,
            message=f"Dataset '{dataset_name}' updated successfully",
        )

    except Exception as e:
        return error(f"Failed to update dataset '{dataset_name}': {e}")


def delete_dataset(
    project_key: str, dataset_name: str, drop_data: bool = False
) -> dict[str, Any]:
    """
    Delete a dataset from a Dataiku DSS project.

    Args:
        project_key: The project key containing the dataset
        dataset_name: Name of the dataset to delete
        drop_data: Whether to also drop the underlying data (default: False)

    Returns:
        Dict with status and deletion details or error message
    """
    try:
        dataset = get_project(project_key).get_dataset(dataset_name)
        dataset_type = dataset.get_settings().type
        dataset.delete(drop_data=drop_data)

        return ok(
            deleted_dataset={"name": dataset_name, "type": dataset_type},
            drop_data=drop_data,
            message=f"Dataset '{dataset_name}' deleted successfully",
        )

    except Exception as e:
        return error(f"Failed to delete dataset '{dataset_name}': {e}")


def build_dataset(
    project_key: str,
    dataset_name: str,
    mode: Optional[str] = None,
    partition: Optional[str] = None,
    wait: bool = True,
) -> dict[str, Any]:
    """
    Build a dataset to refresh its content.

    Args:
        project_key: The project key containing the dataset
        dataset_name: Name of the dataset to build
        mode: Optional build mode (default NON_RECURSIVE_FORCED_BUILD):
            RECURSIVE_BUILD, NON_RECURSIVE_FORCED_BUILD, RECURSIVE_FORCED_BUILD
        partition: Optional partition to build (for partitioned datasets)
        wait: Wait for the job to finish (False returns the job id at once)

    Returns:
        Dict with the job state. "status" is "error" if the job did not
        finish with state DONE.
    """
    if mode and mode not in BUILD_MODES:
        return error(
            f"Invalid build mode. Must be one of: {list(BUILD_MODES)}",
            "invalid_argument",
        )

    try:
        dataset = get_project(project_key).get_dataset(dataset_name)
        # build(wait=True) raises on failure: wait here to keep the job state.
        job = dataset.build(
            job_type=mode or "NON_RECURSIVE_FORCED_BUILD",
            partitions=partition,
            wait=False,
        )
        if wait:
            wait_for_job(job)
        job_info = job_summary(job)

    except Exception as e:
        return error(f"Failed to build dataset '{dataset_name}': {e}")

    if not wait:
        return ok(
            dataset_name=dataset_name,
            job=job_info,
            message=f"Job {job.id} started; follow it with get_job_details",
        )

    if job_info["state"] != "DONE":
        return error(
            f"Build of '{dataset_name}' (job {job.id}) ended with state "
            f"{job_info['state']}; see get_job_details for the log",
            "job_failed",
            dataset_name=dataset_name,
            job=job_info,
        )

    return ok(
        dataset_name=dataset_name,
        job=job_info,
        build_mode=mode,
        partition=partition,
        message=f"Dataset '{dataset_name}' built successfully",
    )


def inspect_dataset_schema(
    project_key: str, dataset_name: str
) -> dict[str, Any]:
    """
    Inspect the schema of a dataset.

    Args:
        project_key: The project key containing the dataset
        dataset_name: Name of the dataset to inspect

    Returns:
        Dict with dataset schema information or error message
    """
    try:
        dataset = get_project(project_key).get_dataset(dataset_name)
        schema = dataset.get_schema()

        columns = []
        for col in schema.get("columns", []):
            info = {
                "name": col.get("name"),
                "type": col.get("type"),
                "meaning": col.get("meaning"),
                "comment": col.get("comment", ""),
            }
            if col.get("maxLength") is not None:
                info["max_length"] = col.get("maxLength")
            if col.get("type") == "array":
                info["array_content"] = col.get("arrayContent")
            elif col.get("type") == "map":
                info["map_keys"] = col.get("mapKeys")
                info["map_values"] = col.get("mapValues")
            elif col.get("type") == "object":
                info["object_fields"] = col.get("objectFields", [])
            columns.append(info)

        return ok(
            dataset_name=dataset_name,
            schema={
                "columns": columns,
                "user_modified": schema.get("userModified", False),
                "column_count": len(columns),
            },
        )

    except Exception as e:
        return error(
            f"Failed to inspect schema for dataset '{dataset_name}': {e}"
        )


def check_dataset_metrics(
    project_key: str, dataset_name: str
) -> dict[str, Any]:
    """
    Get the last computed value of every metric of a dataset.

    Args:
        project_key: The project key containing the dataset
        dataset_name: Name of the dataset to check metrics for

    Returns:
        Dict {metric_id: {"value", "partition", "computed_on"}}
    """
    try:
        dataset = get_project(project_key).get_dataset(dataset_name)
        raw = dataset.get_last_metric_values().get_raw() or {}

        metrics = {}
        for item in raw.get("metrics", []):
            metric_id = (item.get("metric") or {}).get("id")
            values = item.get("lastValues") or []
            if not metric_id or not values:
                continue
            # Global value first (NP = not partitioned, ALL = whole dataset).
            point = next(
                (v for v in values if v.get("partition") in ("NP", "ALL")),
                values[0],
            )
            metrics[metric_id] = {
                "value": point.get("value"),
                "partition": point.get("partition"),
                "computed_on": iso(point.get("time")),
            }

        return ok(
            dataset_name=dataset_name,
            metrics=metrics,
            has_metrics=bool(metrics),
        )

    except Exception as e:
        return error(
            f"Failed to check metrics for dataset '{dataset_name}': {e}"
        )


def list_datasets(
    project_key: str, dataset_type: Optional[str] = None
) -> dict[str, Any]:
    """
    List all datasets in a project, optionally filtered by type.

    Args:
        project_key: The project key to list datasets from
        dataset_type: Optional filter by dataset type (e.g. 'PostgreSQL')

    Returns:
        Dict with list of datasets or error message
    """
    try:
        all_datasets = get_project(project_key).list_datasets()

        datasets = [
            {
                "name": d.get("name"),
                "type": d.get("type"),
                "managed": d.get("managed", False),
                "connection": (d.get("params") or {}).get("connection"),
                "partitioned": bool(
                    (d.get("partitioning") or {}).get("dimensions")
                ),
                "tags": d.get("tags", []),
            }
            for d in all_datasets
            if not dataset_type or d.get("type") == dataset_type
        ]

        return ok(
            datasets=datasets,
            total_count=len(datasets),
            project_key=project_key,
        )

    except Exception as e:
        return error(
            f"Failed to list datasets in project '{project_key}': {e}"
        )


def get_dataset_info(project_key: str, dataset_name: str) -> dict[str, Any]:
    """
    Get detailed information about a dataset.

    Args:
        project_key: The project key containing the dataset
        dataset_name: Name of the dataset to inspect

    Returns:
        Dict with dataset information or error message
    """
    try:
        dataset = get_project(project_key).get_dataset(dataset_name)
        settings = dataset.get_settings()
        raw = settings.get_raw()
        params = settings.get_raw_params() or {}
        partitioning = raw.get("partitioning") or {}

        info = {
            "name": dataset_name,
            "type": settings.type,
            "managed": raw.get("managed", False),
            "description": settings.description or "",
            "tags": settings.tags or [],
            "custom_fields": settings.custom_fields or {},
            "connection": params.get("connection"),
            "path": params.get("path"),
            "schema": params.get("schema"),
            "table": params.get("table"),
            "catalog": params.get("catalog"),
            "format_type": raw.get("formatType"),
            "partitioning": [
                {"name": d.get("name"), "type": d.get("type")}
                for d in partitioning.get("dimensions", [])
            ],
            "column_count": len(settings.schema_columns or []),
        }

        try:
            build = dataset.get_info()
            info["last_build"] = {
                "start_time": iso(build.last_build_start_time),
                "end_time": iso(build.last_build_end_time),
                "successful": build.is_last_build_successful,
            }
        except Exception as e:  # No build information on some dataset types
            info["last_build"] = {"error": str(e)}

        return ok(dataset_info=info)

    except Exception as e:
        return error(f"Failed to get dataset info for '{dataset_name}': {e}")


def clear_dataset(
    project_key: str, dataset_name: str, partition: Optional[str] = None
) -> dict[str, Any]:
    """
    Clear the data from a dataset.

    Args:
        project_key: The project key containing the dataset
        dataset_name: Name of the dataset to clear
        partition: Optional partitions to clear (for partitioned datasets)

    Returns:
        Dict with status and clear operation details or error message
    """
    try:
        dataset = get_project(project_key).get_dataset(dataset_name)
        dataset.clear(partitions=partition)

        return ok(
            dataset_name=dataset_name,
            partition=partition,
            message=f"Dataset '{dataset_name}' cleared successfully",
        )

    except Exception as e:
        return error(f"Failed to clear dataset '{dataset_name}': {e}")
