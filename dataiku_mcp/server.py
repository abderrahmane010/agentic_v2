"""
MCP Server for Dataiku DSS integration.

Ne pas ajouter `from __future__ import annotations` dans ce fichier :
FastMCP doit pouvoir lire les annotations réelles des outils décorés.
"""

import json
import logging
import sys
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from dataiku_mcp.client import get_project, list_projects
from dataiku_mcp.securite import (
    filtrer_projets,
    mode_lecture_seule,
    outil_securise,
    projets_autorises,
    verifier_projet,
)
from dataiku_mcp.tools import (
    advanced_scenarios,
    classification_dataset as flow_classification,
    code_development,
    datasets,
    dependances_projets,
    moteurs,
    environment_config,
    inventaire_migration,
    monitoring_debug,
    productivity,
    project_exploration,
    recipes,
    scenarios,
)

# Logs sur stderr : stdout est réservé au protocole MCP (transport stdio).
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "Dataiku DSS MCP Server",
    instructions=(
        "Serveur MCP pour Dataiku DSS. Fournit des outils pour explorer les "
        "projets, le Flow, les datasets, les recettes et les scénarios. "
        "Les outils qui modifient DSS sont bloqués quand le serveur est en "
        "lecture seule (DSS_READ_ONLY=true)."
    ),
)


# ===========================================================================
# Project tools
# ===========================================================================
@mcp.tool()
def list_dss_projects() -> Dict[str, Any]:
    """List the keys of the Dataiku projects this server may access."""
    try:
        projects = filtrer_projets(list_projects())
        return {"status": "ok", "projects": projects, "count": len(projects)}
    except Exception as exc:
        return {"status": "error", "error_type": "dss_error", "message": str(exc)}


# ===========================================================================
# Recipe tools
# ===========================================================================
@mcp.tool()
@outil_securise()
def list_recipes(
    project_key: str, recipe_type: Optional[str] = None
) -> Dict[str, Any]:
    """List the recipes of a project with their inputs and outputs.

    Args:
        project_key: The project key
        recipe_type: Optional filter (e.g. 'python', 'join', 'sql_query')
    """
    return recipes.list_recipes(project_key, recipe_type)


@mcp.tool()
@outil_securise()
def get_recipe_info(project_key: str, recipe_name: str) -> Dict[str, Any]:
    """Get the type, inputs, outputs, engine and metadata of a recipe.

    Args:
        project_key: The project key
        recipe_name: Name of the recipe
    """
    return recipes.get_recipe_info(project_key, recipe_name)


@mcp.tool()
@outil_securise(ecriture=True)
def create_recipe(
    project_key: str,
    recipe_type: str,
    recipe_name: str,
    inputs: List[str],
    outputs: List[Dict[str, Any]],
    code: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new recipe in a Dataiku project.

    Args:
        project_key: The project key
        recipe_type: DSS recipe type (e.g. 'python', 'sql_script',
            'sql_query', 'pyspark', 'join', 'grouping', 'sync')
        recipe_name: Name for the new recipe
        inputs: List of input dataset names
        outputs: List of output dataset configurations
        code: Optional code for the recipe
    """
    return recipes.create_recipe(
        project_key, recipe_type, recipe_name, inputs, outputs, code
    )


@mcp.tool()
@outil_securise(ecriture=True)
def update_recipe(
    project_key: str,
    recipe_name: str,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """Update an existing recipe.

    Args:
        project_key: The project key
        recipe_name: Name of the recipe to update
        settings: Fields to update: code, description, tags,
            custom_fields, params (merged into the recipe params)
    """
    return recipes.update_recipe(project_key, recipe_name, **settings)


@mcp.tool()
@outil_securise(ecriture=True)
def delete_recipe(project_key: str, recipe_name: str) -> Dict[str, Any]:
    """Delete a recipe from a project.

    Args:
        project_key: The project key
        recipe_name: Name of the recipe to delete
    """
    return recipes.delete_recipe(project_key, recipe_name)


@mcp.tool()
@outil_securise(ecriture=True)
def run_recipe(
    project_key: str,
    recipe_name: str,
    build_mode: Optional[str] = None,
    wait: bool = True,
) -> Dict[str, Any]:
    """Run a recipe to build its outputs.

    Args:
        project_key: The project key
        recipe_name: Name of the recipe to run
        build_mode: RECURSIVE_BUILD, NON_RECURSIVE_FORCED_BUILD (default) or
            RECURSIVE_FORCED_BUILD
        wait: Wait for the job to finish; False returns the job id at once
            (follow it with get_job_details)
    """
    return recipes.run_recipe(project_key, recipe_name, build_mode, wait)
# ===========================================================================
# Dataset tools
# ===========================================================================
@mcp.tool()
@outil_securise()
def list_datasets(
    project_key: str, dataset_type: Optional[str] = None
) -> Dict[str, Any]:
    """List the datasets of a project (type, connection, partitioning).

    Args:
        project_key: The project key
        dataset_type: Optional filter on the DSS type (e.g. 'PostgreSQL')
    """
    return datasets.list_datasets(project_key, dataset_type)


@mcp.tool()
@outil_securise()
def get_dataset_info(project_key: str, dataset_name: str) -> Dict[str, Any]:
    """Get the settings, location, partitioning and last build of a dataset.

    Args:
        project_key: The project key
        dataset_name: Name of the dataset
    """
    return datasets.get_dataset_info(project_key, dataset_name)


@mcp.tool()
@outil_securise(ecriture=True)
def create_dataset(
    project_key: str,
    dataset_name: str,
    dataset_type: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a new dataset in a project.

    Args:
        project_key: The project key
        dataset_name: Name for the new dataset
        dataset_type: 'managed', 'filesystem', 'sql', 's3', 'uploaded' or a
            raw DSS dataset type
        params: Dataset parameters (connection, path, table, schema,
            sql_type, format_type, store_into...)
    """
    return datasets.create_dataset(project_key, dataset_name, dataset_type, params)


@mcp.tool()
@outil_securise(ecriture=True)
def update_dataset(
    project_key: str,
    dataset_name: str,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """Update dataset settings.

    Args:
        project_key: The project key
        dataset_name: Name of the dataset to update
        settings: Dataset settings to update
    """
    return datasets.update_dataset(project_key, dataset_name, **settings)


@mcp.tool()
@outil_securise(ecriture=True)
def delete_dataset(
    project_key: str,
    dataset_name: str,
    drop_data: bool = False,
) -> Dict[str, Any]:
    """Delete a dataset from a project.

    Args:
        project_key: The project key
        dataset_name: Name of the dataset to delete
        drop_data: Whether to drop the underlying data
    """
    return datasets.delete_dataset(project_key, dataset_name, drop_data)


@mcp.tool()
@outil_securise(ecriture=True)
def build_dataset(
    project_key: str,
    dataset_name: str,
    mode: Optional[str] = None,
    partition: Optional[str] = None,
    wait: bool = True,
) -> Dict[str, Any]:
    """Build a dataset.

    Args:
        project_key: The project key
        dataset_name: Name of the dataset to build
        mode: RECURSIVE_BUILD, NON_RECURSIVE_FORCED_BUILD (default) or
            RECURSIVE_FORCED_BUILD
        partition: Optional partition specification
        wait: Wait for the job to finish; False returns the job id at once
            (follow it with get_job_details)
    """
    return datasets.build_dataset(project_key, dataset_name, mode, partition, wait)


@mcp.tool()
@outil_securise(ecriture=True)
def clear_dataset(
    project_key: str,
    dataset_name: str,
    partition: Optional[str] = None,
) -> Dict[str, Any]:
    """Delete the data of a dataset (or of some partitions); keeps the dataset.

    Args:
        project_key: The project key
        dataset_name: Name of the dataset to clear
        partition: Optional partitions to clear
    """
    return datasets.clear_dataset(project_key, dataset_name, partition)


@mcp.tool()
@outil_securise()
def inspect_dataset_schema(project_key: str, dataset_name: str) -> Dict[str, Any]:
    """Get dataset schema information.

    Args:
        project_key: The project key
        dataset_name: Name of the dataset
    """
    return datasets.inspect_dataset_schema(project_key, dataset_name)


@mcp.tool()
@outil_securise()
def check_dataset_metrics(project_key: str, dataset_name: str) -> Dict[str, Any]:
    """Get latest dataset metrics.

    Args:
        project_key: The project key
        dataset_name: Name of the dataset
    """
    return datasets.check_dataset_metrics(project_key, dataset_name)


# ===========================================================================
# Scenario tools
# ===========================================================================
@mcp.tool()
@outil_securise()
def list_scenarios(
    project_key: str,
    scenario_type: Optional[str] = None,
    active_only: bool = False,
) -> Dict[str, Any]:
    """List the scenarios of a project with their triggers.

    Args:
        project_key: The project key
        scenario_type: Optional filter ('step_based' or 'custom_python')
        active_only: Only scenarios whose auto-triggers are active
    """
    return scenarios.list_scenarios(project_key, scenario_type, active_only)


@mcp.tool()
@outil_securise()
def get_scenario_info(project_key: str, scenario_id: str) -> Dict[str, Any]:
    """Get the settings, triggers, reporters, next run and last run of a scenario.

    Args:
        project_key: The project key
        scenario_id: ID of the scenario
    """
    return scenarios.get_scenario_info(project_key, scenario_id)


@mcp.tool()
@outil_securise()
def get_scenario_run_history(
    project_key: str, scenario_id: str, limit: int = 10
) -> Dict[str, Any]:
    """Get the last runs of a scenario (outcome, dates, duration, trigger).

    Args:
        project_key: The project key
        scenario_id: ID of the scenario
        limit: Number of runs to return
    """
    return scenarios.get_scenario_run_history(project_key, scenario_id, limit)


@mcp.tool()
@outil_securise(ecriture=True)
def create_scenario(
    project_key: str,
    scenario_name: str,
    scenario_type: str,
    definition: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new scenario in a project.

    Args:
        project_key: The project key
        scenario_name: Name for the new scenario
        scenario_type: Type of scenario ('step_based' or 'custom_python')
        definition: Optional scenario definition
    """
    return scenarios.create_scenario(
        project_key, scenario_name, scenario_type, definition
    )


@mcp.tool()
@outil_securise(ecriture=True)
def update_scenario(
    project_key: str,
    scenario_id: str,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """Update scenario settings.

    Args:
        project_key: The project key
        scenario_id: ID of the scenario to update
        settings: Fields to update: name, description, active, tags,
            params, script (custom_python), step_script + step_index
    """
    return scenarios.update_scenario(project_key, scenario_id, **settings)


@mcp.tool()
@outil_securise(ecriture=True)
def delete_scenario(project_key: str, scenario_id: str) -> Dict[str, Any]:
    """Delete a scenario from a project.

    Args:
        project_key: The project key
        scenario_id: ID of the scenario to delete
    """
    return scenarios.delete_scenario(project_key, scenario_id)


@mcp.tool()
@outil_securise(ecriture=True)
def add_scenario_trigger(
    project_key: str,
    scenario_id: str,
    trigger_type: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Add a trigger to a scenario.

    Args:
        project_key: The project key
        scenario_id: ID of the scenario
        trigger_type: 'periodic', 'hourly', 'daily', 'monthly' or 'raw'
        params: Trigger parameters (e.g. {"hour": 2, "minute": 0} for daily,
            {"trigger": {...}} for raw: a trigger dict copied from
            get_scenario_info, for dataset or SQL triggers)
    """
    return scenarios.add_scenario_trigger(
        project_key, scenario_id, trigger_type, **(params or {})
    )


@mcp.tool()
@outil_securise(ecriture=True)
def remove_scenario_trigger(
    project_key: str,
    scenario_id: str,
    trigger_idx: int,
) -> Dict[str, Any]:
    """Remove a trigger from a scenario.

    Args:
        project_key: The project key
        scenario_id: ID of the scenario
        trigger_idx: Index of the trigger to remove
    """
    return scenarios.remove_scenario_trigger(project_key, scenario_id, trigger_idx)


@mcp.tool()
@outil_securise(ecriture=True)
def run_scenario(
    project_key: str, scenario_id: str, wait: bool = True
) -> Dict[str, Any]:
    """Run a scenario manually.

    Args:
        project_key: The project key
        scenario_id: ID of the scenario to run
        wait: Wait for the run to finish; False returns once requested
    """
    return scenarios.run_scenario(project_key, scenario_id, wait)
#----------scenario avancé---------------
@mcp.tool()
@outil_securise()
def get_scenario_logs(
    project_key: str,
    scenario_id: str,
    run_id: Optional[str] = None,
    max_chars: int = 20000,
) -> Dict[str, Any]:
    """Get the step outcomes, first error and logs of a scenario run.

    Args:
        project_key: The project key
        scenario_id: ID of the scenario
        run_id: Specific run ID (defaults to latest)
        max_chars: Maximum size of each log (the end is kept)
    """
    return advanced_scenarios.get_scenario_logs(
        project_key, scenario_id, run_id, max_chars
    )


@mcp.tool()
@outil_securise()
def get_scenario_steps(project_key: str, scenario_id: str) -> Dict[str, Any]:
    """Get detailed step configuration including Python code.

    Args:
        project_key: The project key
        scenario_id: ID of the scenario
    """
    return advanced_scenarios.get_scenario_steps(project_key, scenario_id)


@mcp.tool()
@outil_securise(ecriture=True)
def clone_scenario(
    project_key: str,
    source_scenario_id: str,
    new_scenario_name: str,
    modifications: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Clone an existing scenario. The clone is INACTIVE unless
    modifications contains "active": true.

    Args:
        project_key: The project key
        source_scenario_id: Source scenario ID to clone
        new_scenario_name: Name for the new scenario
        modifications: Optional modifications to apply
    """
    return advanced_scenarios.clone_scenario(
        project_key, source_scenario_id, new_scenario_name, modifications
    )


# ===========================================================================
# Code development tools
# ===========================================================================
@mcp.tool()
@outil_securise()
def inventaire_moteurs(
    project_key: str,
    recipe_name: Optional[str] = None,
    moteur_cible: Optional[str] = None,
    details: bool = False,
    inclure_code: bool = False,
) -> Dict[str, Any]:
    """Execution engines of the recipes of a project (the "Engine" menu
    above RUN): configured engine, engine actually selected by DSS,
    available and unavailable engines with DSS's reason, and whether each
    recipe can switch to a target engine (e.g. moteur_cible="SPARK").
    Read-only: nothing is changed in DSS.

    Args:
        project_key: The project key
        recipe_name: Optional, a single recipe
        moteur_cible: Optional target engine to evaluate (SPARK, HIVE,
            IMPALA, SQL, DSS...)
        details: Also return the raw engine status from DSS (diagnostic)
        inclure_code: Also analyse code and plugin recipes (by default only
            visual recipes, the ones with an engine choice)
    """
    return moteurs.inventaire_moteurs(
        project_key, recipe_name, moteur_cible, details, inclure_code
    )


@mcp.tool()
@outil_securise()
def get_recipe_code(project_key: str, recipe_name: str) -> Dict[str, Any]:
    """Extract actual Python/SQL code from recipes.

    Args:
        project_key: The project key
        recipe_name: Name of the recipe
    """
    return code_development.get_recipe_code(project_key, recipe_name)


@mcp.tool()
@outil_securise()
def validate_recipe_syntax(
    project_key: str,
    recipe_name: str,
    code: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate Python/SQL syntax before execution.

    Args:
        project_key: The project key
        recipe_name: Name of the recipe
        code: Optional code to validate
    """
    return code_development.validate_recipe_syntax(project_key, recipe_name, code)


@mcp.tool()
@outil_securise()
def dry_run_recipe(
    project_key: str,
    recipe_name: str,
    sample_rows: int = 100,
) -> Dict[str, Any]:
    """Test recipe logic without actual execution.

    Args:
        project_key: The project key
        recipe_name: Name of the recipe
        sample_rows: Number of sample rows to test with
    """
    return code_development.test_recipe_dry_run(project_key, recipe_name, sample_rows)


@mcp.tool()
@outil_securise()
def get_generated_sql(
    project_key: str,
    recipe_name: str,
    partition: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract generated SQL from visual recipes (Shaker, Join, SQL-based...).

    For Shaker recipes, returns the recipe configuration since SQL is
    generated dynamically at runtime.

    Args:
        project_key: The project key
        recipe_name: Name of the recipe
        partition: Optional partition specification
    """
    return code_development.get_generated_sql(project_key, recipe_name, partition)


# ===========================================================================
# Project exploration tools
# ===========================================================================
@mcp.tool()
@outil_securise()
def get_project_flow(project_key: str) -> Dict[str, Any]:
    """Get complete data flow/pipeline structure.

    Args:
        project_key: The project key
    """
    return project_exploration.get_project_flow(project_key)


@mcp.tool()
@outil_securise()
def classer_datasets_flow(
    project_key: str,
    details: bool = False,
) -> Dict[str, Any]:
    """List ALL datasets (tables) of a project classified by their position
    in the Flow: sources, intermediates, finals and isolated datasets.
    Use this by default when asked for the datasets / tables of a project.

    Classification is topological (based on recipe dependencies),
    not necessarily business meaning. Managed folders, models and datasets
    shared from other projects are reported separately.

    Args:
        project_key: The project key
        details: Also return producing/consuming recipes for each dataset
    """
    try:
        return {
            "status": "ok",
            **flow_classification.classer_datasets_flow(project_key, details),
        }
    except Exception as exc:
        return {"status": "error", "error_type": "dss_error", "message": str(exc)}


@mcp.tool()
@outil_securise()
def search_project_objects(
    project_key: str,
    search_term: str,
    object_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Search datasets, recipes, scenarios whose name contains a term.
    To list everything, prefer list_datasets / list_recipes / list_scenarios.

    Args:
        project_key: The project key
        search_term: Text or pattern to search (e.g. 'client', '*client*')
        object_types: Subset of ["datasets", "recipes", "scenarios"]
    """
    return project_exploration.search_project_objects(
        project_key, search_term, object_types
    )


@mcp.tool()
@outil_securise()
def get_dataset_sample(
    project_key: str,
    dataset_name: str,
    rows: int = 100,
    columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Get the first rows of a dataset with per-column statistics.

    Warning: returns real data to the client (possible personal data).

    Args:
        project_key: The project key
        dataset_name: Name of the dataset
        rows: Number of sample rows (max 1000)
        columns: Specific columns to include
    """
    return project_exploration.get_dataset_sample(
        project_key, dataset_name, rows, columns
    )


@mcp.tool()
@outil_securise()
def dependances_inter_projets(
    project_key: Optional[str] = None,
    inclure_scenarios: bool = True,
    details: bool = False,
    analyser_code: bool = True,
) -> Dict[str, Any]:
    """Dependencies BETWEEN Dataiku projects (which project uses data of
    which other project), cycles, proposed migration waves and interface
    tables (datasets of a project used by other projects, e.g. a table that
    is final in its project but the source of another one).
    Links come from recipes, scenarios, shared physical storage (same
    table / path) and recipe code. Use it to plan a migration.

    Args:
        project_key: Optional. Focus on one project (its providers,
            consumers, prerequisites, wave and interface tables). Omit for
            the whole instance.
        inclure_scenarios: Also analyse scenarios (slower)
        details: Return every object of each link and unused shares
        analyser_code: Also search recipe code for references to other
            projects (one API call per code recipe)
    """
    return dependances_projets.dependances_inter_projets(
        project_key, inclure_scenarios, details, analyser_code
    )


@mcp.tool()
@outil_securise()
def inventaire_technique_migration(
    project_key: Optional[str] = None,
    analyser_code: bool = True,
    details: bool = False,
) -> Dict[str, Any]:
    """Technical inventory before a Cloudera -> Databricks migration:
    storage (HDFS/Hive...), recipe engines (Hive, Impala, Spark...),
    Cloudera-specific code (hdfs://, Kerberos, Hive SQL...), plugins and a
    complexity score (Simple / Moyen / Complexe) with reasons.

    Args:
        project_key: Optional. One project; omit for a summary of all projects
        analyser_code: Scan recipe and scenario code (slower)
        details: Return the per-dataset / per-recipe detail
    """
    return inventaire_migration.inventaire_technique_migration(
        project_key, analyser_code, details
    )


# ===========================================================================
# Environment configuration tools
# ===========================================================================
@mcp.tool()
@outil_securise()
def get_code_environments(project_key: Optional[str] = None) -> Dict[str, Any]:
    """List available Python/R environments.

    Args:
        project_key: Project identifier (optional)
    """
    return environment_config.get_code_environments(project_key)


@mcp.tool()
@outil_securise()
def get_project_variables(project_key: str) -> Dict[str, Any]:
    """Get project-level variables and configuration.

    Args:
        project_key: The project key
    """
    return environment_config.get_project_variables(project_key)


@mcp.tool()
@outil_securise()
def get_connections(project_key: Optional[str] = None) -> Dict[str, Any]:
    """List available data connections.

    Args:
        project_key: Project identifier (optional)
    """
    return environment_config.get_connections(project_key)


# ===========================================================================
# Monitoring and debug tools
# ===========================================================================
@mcp.tool()
@outil_securise()
def get_recent_runs(
    project_key: str,
    limit: int = 50,
    status_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Get recent run history across all scenarios/recipes.

    Args:
        project_key: The project key
        limit: Number of recent runs to retrieve
        status_filter: Filter by status
    """
    return monitoring_debug.get_recent_runs(project_key, limit, status_filter)


@mcp.tool()
@outil_securise()
def get_job_details(
    project_key: str, job_id: str, max_log_chars: int = 20000
) -> Dict[str, Any]:
    """Get the state, activities and log of a job.

    Args:
        project_key: The project key
        job_id: Job identifier
        max_log_chars: Maximum log size (the end is kept)
    """
    return monitoring_debug.get_job_details(project_key, job_id, max_log_chars)


@mcp.tool()
@outil_securise(ecriture=True)
def cancel_running_jobs(project_key: str, job_ids: List[str]) -> Dict[str, Any]:
    """Cancel running jobs/scenarios.

    Args:
        project_key: The project key
        job_ids: List of job IDs to cancel
    """
    return monitoring_debug.cancel_running_jobs(project_key, job_ids)


# ===========================================================================
# Productivity tools
# ===========================================================================
@mcp.tool()
@outil_securise(
    ecriture=True,
    champs_projet=("source_project_key", "target_project_key"),
)
def duplicate_project_structure(
    source_project_key: str,
    target_project_key: str,
    include_data: bool = False,
    target_project_name: Optional[str] = None,
    connection_remapping: Optional[Dict[str, str]] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Duplicate a project with the native DSS duplication.

    Args:
        source_project_key: Source project identifier
        target_project_key: Key of the new project (must not exist)
        include_data: Whether to copy the data of managed datasets
        target_project_name: Name of the new project (defaults to its key)
        connection_remapping: {source connection: target connection}
        dry_run: Only describe what would be duplicated (default True)
    """
    return productivity.duplicate_project_structure(
        source_project_key,
        target_project_key,
        include_data,
        target_project_name,
        connection_remapping,
        dry_run,
    )


@mcp.tool()
@outil_securise()
def export_project_config(
    project_key: str,
    export_format: str = "json",
) -> Dict[str, Any]:
    """Export project configuration as JSON/YAML.

    Args:
        project_key: The project key
        export_format: Export format ('json' or 'yaml')
    """
    return productivity.export_project_config(project_key, export_format)


@mcp.tool()
@outil_securise(ecriture=True)
def batch_update_objects(
    project_key: str,
    object_type: str,
    pattern: str,
    updates: Dict[str, Any],
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Apply the same update to every object whose name matches a pattern.

    Args:
        project_key: The project key
        object_type: 'datasets', 'recipes' or 'scenarios'
        pattern: Regular expression matched against the object name
        updates: Fields accepted by update_dataset / update_recipe /
            update_scenario
        dry_run: Only list the matching objects (default True)
    """
    return productivity.batch_update_objects(
        project_key, object_type, pattern, updates, dry_run
    )


# ===========================================================================
# Resources
# ===========================================================================
@mcp.resource("dss://projects")
def list_available_projects() -> str:
    """List the Dataiku projects this server is allowed to access."""
    return json.dumps(
        {"projects": filtrer_projets(list_projects())},
        ensure_ascii=False,
    )


@mcp.resource("dss://project/{project_key}")
def get_project_info(project_key: str) -> str:
    """Get basic information about a specific project."""
    try:
        cle = verifier_projet(project_key)
        metadata = get_project(cle).get_metadata()
        return json.dumps(
            {
                "key": cle,
                "name": metadata.get("label", cle),
                "description": metadata.get("description", ""),
                "tags": metadata.get("tags", []),
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.warning("get_project_info(%s) : %s", project_key, exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def create_server() -> FastMCP:
    """Create and configure the MCP server."""
    if mode_lecture_seule():
        # Inutile d'exposer au LLM des outils qui seraient refusés.
        for outil in mcp._tool_manager.list_tools():
            if getattr(outil.fn, "outil_ecriture", False):
                mcp._tool_manager.remove_tool(outil.name)

    autorises = projets_autorises()
    logger.info(
        "Serveur prêt - lecture seule : %s - projets autorisés : %s",
        mode_lecture_seule(),
        ", ".join(sorted(autorises)) if autorises else "tous",
    )
    return mcp


if __name__ == "__main__":
    create_server().run()