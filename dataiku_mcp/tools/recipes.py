"""
Recipe management tools for Dataiku DSS.

This module provides functions for creating, updating, deleting, and running recipes
in Dataiku DSS projects through the dataiku-api-client.
"""

from typing import Any, Optional, Union

from dataiku_mcp.client import get_project
from dataiku_mcp.tools._common import (
    BUILD_MODES,
    CODE_RECIPE_TYPES,
    error,
    flat_refs,
    job_summary,
    ok,
    wait_for_job,
)


def create_recipe(
    project_key: str,
    recipe_type: str,
    recipe_name: str,
    inputs: list[str],
    outputs: list[Union[str, dict[str, Any]]],
    code: Optional[str] = None,
) -> dict[str, Any]:
    """
    Create a new recipe in a Dataiku DSS project.

    Args:
        project_key: The project key where the recipe will be created
        recipe_type: DSS recipe type (e.g. 'python', 'sql_script', 'sql_query',
            'pyspark', 'grouping', 'join', 'sync', 'prepare')
        recipe_name: Name of the recipe to create
        inputs: List of input dataset names
        outputs: List of output specifications. Can be:
            - String: name of existing dataset
            - Dict: {"name": str, "new": bool, "connection": str, "append": bool}
        code: Optional code content for code recipes

    Returns:
        Dict with status and recipe details or error message
    """
    try:
        project = get_project(project_key)
        builder = project.new_recipe(recipe_type, name=recipe_name)

        for input_name in inputs:
            builder = builder.with_input(input_name)

        output_names = []
        for output_spec in outputs:
            if isinstance(output_spec, str):
                output_spec = {"name": output_spec}
            if not isinstance(output_spec, dict) or not output_spec.get("name"):
                return error(
                    f"Invalid output specification: {output_spec}",
                    "invalid_argument",
                )

            name = output_spec["name"]
            append = output_spec.get("append", False)
            output_names.append(name)

            if output_spec.get("new", False):
                connection = output_spec.get("connection", "filesystem_managed")
                # Code recipes and visual recipes use different builders.
                if hasattr(builder, "with_new_output_dataset"):
                    builder = builder.with_new_output_dataset(
                        name, connection, append=append
                    )
                elif hasattr(builder, "with_new_output"):
                    builder = builder.with_new_output(
                        name, connection, append=append
                    )
                else:
                    return error(
                        f"Recipe type '{recipe_type}' cannot create a new "
                        "output dataset; create the dataset first",
                        "invalid_argument",
                    )
            else:
                builder = builder.with_output(name, append=append)

        if code and hasattr(builder, "with_script"):
            builder = builder.with_script(code)

        recipe = builder.create()

        # Recipes without a script builder (e.g. sql_query): set the payload.
        if code and not hasattr(builder, "with_script"):
            if recipe_type not in CODE_RECIPE_TYPES:
                return error(
                    f"Recipe '{recipe_name}' was created, but recipe type "
                    f"'{recipe_type}' does not accept code",
                    "invalid_argument",
                    recipe_name=recipe_name,
                )
            settings = recipe.get_settings()
            settings.set_payload(code)
            settings.save()

        return ok(
            recipe_name=recipe.name,
            recipe_type=recipe_type,
            inputs=inputs,
            outputs=output_names,
            message=f"Recipe '{recipe_name}' created successfully",
        )

    except Exception as e:
        return error(f"Failed to create recipe '{recipe_name}': {e}")


def update_recipe(
    project_key: str, recipe_name: str, **kwargs: Any
) -> dict[str, Any]:
    """
    Update an existing recipe's settings or code.

    Args:
        project_key: The project key containing the recipe
        recipe_name: Name of the recipe to update
        **kwargs: Update parameters including:
            - code: New code content (for code recipes)
            - description: Recipe description
            - tags: List of tags
            - custom_fields: Dict of custom metadata fields
            - params: Dict merged into the recipe "params" (engine settings...)

    Returns:
        Dict with status and update details or error message
    """
    supported = {"code", "description", "tags", "custom_fields", "params"}
    unknown = sorted(set(kwargs) - supported)
    if unknown:
        return error(
            f"Unsupported fields: {unknown}. Supported: {sorted(supported)}",
            "invalid_argument",
        )

    try:
        recipe = get_project(project_key).get_recipe(recipe_name)
        settings = recipe.get_settings()
        updated_fields = []

        if "code" in kwargs:
            if settings.type not in CODE_RECIPE_TYPES:
                return error(
                    f"Recipe '{recipe_name}' (type '{settings.type}') is not a "
                    "code recipe",
                    "invalid_argument",
                )
            settings.set_payload(kwargs["code"])
            updated_fields.append("code")

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

        if "params" in kwargs:
            settings.raw_params.update(kwargs["params"])
            updated_fields.append("params")

        settings.save()

        return ok(
            recipe_name=recipe_name,
            updated_fields=updated_fields,
            message=f"Recipe '{recipe_name}' updated successfully",
        )

    except Exception as e:
        return error(f"Failed to update recipe '{recipe_name}': {e}")


def delete_recipe(project_key: str, recipe_name: str) -> dict[str, Any]:
    """
    Delete a recipe from a Dataiku DSS project.

    Args:
        project_key: The project key containing the recipe
        recipe_name: Name of the recipe to delete

    Returns:
        Dict with status and deletion details or error message
    """
    try:
        recipe = get_project(project_key).get_recipe(recipe_name)
        recipe_type = recipe.get_settings().type
        recipe.delete()

        return ok(
            deleted_recipe={"name": recipe_name, "type": recipe_type},
            message=f"Recipe '{recipe_name}' deleted successfully",
        )

    except Exception as e:
        return error(f"Failed to delete recipe '{recipe_name}': {e}")


def run_recipe(
    project_key: str,
    recipe_name: str,
    build_mode: Optional[str] = None,
    wait: bool = True,
) -> dict[str, Any]:
    """
    Run a recipe to build its outputs.

    Args:
        project_key: The project key containing the recipe
        recipe_name: Name of the recipe to run
        build_mode: Optional build mode (default NON_RECURSIVE_FORCED_BUILD):
            RECURSIVE_BUILD, NON_RECURSIVE_FORCED_BUILD, RECURSIVE_FORCED_BUILD
        wait: Wait for the job to finish (False returns the job id at once)

    Returns:
        Dict with the job state. "status" is "error" if the job did not
        finish with state DONE.
    """
    if build_mode and build_mode not in BUILD_MODES:
        return error(
            f"Invalid build_mode. Must be one of: {list(BUILD_MODES)}",
            "invalid_argument",
        )

    try:
        recipe = get_project(project_key).get_recipe(recipe_name)
        job = recipe.run(
            job_type=build_mode or "NON_RECURSIVE_FORCED_BUILD", wait=False
        )
        if wait:
            wait_for_job(job)
        job_info = job_summary(job)

    except Exception as e:
        return error(f"Failed to run recipe '{recipe_name}': {e}")

    if not wait:
        return ok(
            recipe_name=recipe_name,
            job=job_info,
            message=(
                f"Job {job.id} started; follow it with get_job_details"
            ),
        )

    if job_info["state"] != "DONE":
        return error(
            f"Recipe '{recipe_name}' job {job.id} ended with state "
            f"{job_info['state']}; see get_job_details for the log",
            "job_failed",
            recipe_name=recipe_name,
            job=job_info,
        )

    return ok(
        recipe_name=recipe_name,
        job=job_info,
        message=f"Recipe '{recipe_name}' executed successfully",
    )


def get_recipe_info(project_key: str, recipe_name: str) -> dict[str, Any]:
    """
    Get detailed information about a recipe.

    Args:
        project_key: The project key containing the recipe
        recipe_name: Name of the recipe to inspect

    Returns:
        Dict with recipe information or error message
    """
    try:
        recipe = get_project(project_key).get_recipe(recipe_name)
        settings = recipe.get_settings()
        raw = settings.get_recipe_raw_definition()
        version = raw.get("versionTag", {}) or {}
        creation = raw.get("creationTag", {}) or {}

        return ok(
            recipe_info={
                "name": recipe_name,
                "type": settings.type,
                "description": settings.description or "",
                "tags": settings.tags or [],
                "custom_fields": settings.custom_fields or {},
                "inputs": flat_refs(settings.get_recipe_inputs()),
                "outputs": flat_refs(settings.get_recipe_outputs()),
                "zone": raw.get("zone"),
                "engine": (raw.get("params", {}) or {}).get("engineType"),
                "is_code_recipe": settings.type in CODE_RECIPE_TYPES,
                "created_by": (creation.get("lastModifiedBy") or {}).get(
                    "login"
                ),
                "last_modified_by": (version.get("lastModifiedBy") or {}).get(
                    "login"
                ),
                "last_modified_on": version.get("lastModifiedOn"),
            }
        )

    except Exception as e:
        return error(f"Failed to get recipe info for '{recipe_name}': {e}")


def list_recipes(
    project_key: str, recipe_type: Optional[str] = None
) -> dict[str, Any]:
    """
    List all recipes in a project, optionally filtered by type.

    Args:
        project_key: The project key to list recipes from
        recipe_type: Optional filter by recipe type

    Returns:
        Dict with list of recipes or error message
    """
    try:
        all_recipes = get_project(project_key).list_recipes()

        recipes = [
            {
                "name": r.get("name"),
                "type": r.get("type"),
                "tags": r.get("tags", []),
                "inputs": flat_refs(r.get("inputs")),
                "outputs": flat_refs(r.get("outputs")),
            }
            for r in all_recipes
            if not recipe_type or r.get("type") == recipe_type
        ]

        return ok(
            recipes=recipes,
            total_count=len(recipes),
            project_key=project_key,
        )

    except Exception as e:
        return error(
            f"Failed to list recipes in project '{project_key}': {e}"
        )
