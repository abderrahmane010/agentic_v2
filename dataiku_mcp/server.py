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
    environment_config,
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
        recipe_type: Type of recipe (e.g. 'python', 'sql', 'join')
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
        settings: Recipe settings to update, e.g. {"code": "..."}
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
) -> Dict[str, Any]:
    """Run a recipe to build its outputs.
 
    Args:
        project_key: The project key
        recipe_name: Name of the recipe to run
        build_mode: Optional build mode
    """
    return recipes.run_recipe(project_key, recipe_name, build_mode)
# ===========================================================================
# Dataset tools
# ===========================================================================
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
        dataset_type: Type of dataset (e.g. 'Filesystem', 'PostgreSQL')
        params: Dataset configuration parameters
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
) -> Dict[str, Any]:
    """Build a dataset.
 
    Args:
        project_key: The project key
        dataset_name: Name of the dataset to build
        mode: Optional build mode
        partition: Optional partition specification
    """
    return datasets.build_dataset(project_key, dataset_name, mode, partition)
 
 
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
        settings: Scenario settings to update
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
        trigger_type: Type of trigger to add
        params: Trigger parameters
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
def run_scenario(project_key: str, scenario_id: str) -> Dict[str, Any]:
    """Run a scenario manually.
 
    Args:
        project_key: The project key
        scenario_id: ID of the scenario to run
    """
    return scenarios.run_scenario(project_key, scenario_id)
#----------scenario avancé---------------
@mcp.tool()
@outil_securise()
def get_scenario_logs(
    project_key: str,
    scenario_id: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Get detailed run logs and error messages for failed scenarios.
 
    Args:
        project_key: The project key
        scenario_id: ID of the scenario
        run_id: Specific run ID (defaults to latest)
    """
    return advanced_scenarios.get_scenario_logs(project_key, scenario_id, run_id)
 
 
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
    """Clone an existing scenario with modifications.
 
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
def classer_datasets_flow(project_key: str) -> Dict[str, Any]:
    """Classify the project's datasets by their position in the Flow:
    sources, intermediates, finals and isolated datasets.
 
    Classification is topological (based on recipe dependencies),
    not necessarily business meaning. Managed folders, models and datasets
    shared from other projects are reported separately.
 
    Args:
        project_key: The project key
    """
    return flow_classification.classer_datasets_flow(project_key)
 
 
@mcp.tool()
@outil_securise()
def search_project_objects(
    project_key: str,
    search_term: str,
    object_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Search for datasets, recipes, scenarios by name/pattern.
 
    Args:
        project_key: The project key
        search_term: Search pattern
        object_types: List of object types to search
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
    """Get sample data from datasets.
 
    Args:
        project_key: The project key
        dataset_name: Name of the dataset
        rows: Number of sample rows
        columns: Specific columns to include
    """
    return project_exploration.get_dataset_sample(
        project_key, dataset_name, rows, columns
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
def get_job_details(project_key: str, job_id: str) -> Dict[str, Any]:
    """Get detailed job execution information.
 
    Args:
        project_key: The project key
        job_id: Job identifier
    """
    return monitoring_debug.get_job_details(project_key, job_id)
 
 
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
) -> Dict[str, Any]:
    """Copy project structure to new project.
 
    Args:
        source_project_key: Source project identifier
        target_project_key: Target project identifier
        include_data: Whether to copy data
    """
    return productivity.duplicate_project_structure(
        source_project_key, target_project_key, include_data
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
) -> Dict[str, Any]:
    """Update multiple objects with similar changes.
 
    Args:
        project_key: The project key
        object_type: Type of objects to update
        pattern: Pattern to match objects
        updates: Updates to apply
    """
    return productivity.batch_update_objects(project_key, object_type, pattern, updates)
 
 
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