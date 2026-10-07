"""
Project exploration tools for Dataiku MCP integration.
"""

import re
import json
from typing import Dict, Any, List, Optional
from dataiku_mcp.client import get_client, get_project

def get_project_flow(
    project_key: str
) -> Dict[str, Any]:
    """
    Get complete data flow/pipeline structure.
    
    Args:
        project_key: The project key
        
    Returns:
        Dict containing flow structure and dependencies
    """
    try:
        project = get_project(project_key)
        
        # Get all project objects
        datasets = project.list_datasets()
        recipes = project.list_recipes()
        
        # Build flow structure
        flow_nodes = []
        flow_edges = []
        
        # Add datasets as nodes
        for dataset in datasets:
            dataset_info = {
                "id": dataset["name"],
                "name": dataset["name"],
                "type": "dataset",
                "dataset_type": dataset["type"],
                "tags": dataset.get("tags", [])
            }
            flow_nodes.append(dataset_info)
        
        # Add recipes as nodes and create edges
        for recipe in recipes:
            recipe_info = {
                "id": recipe["name"],
                "name": recipe["name"],
                "type": "recipe",
                "recipe_type": recipe["type"],
                "tags": recipe.get("tags", [])
            }
            flow_nodes.append(recipe_info)
            
            # Get recipe details for inputs/outputs
            try:
                recipe_obj = project.get_recipe(recipe["name"])
                recipe_def = recipe_obj.get_definition()
                
                # Create edges from inputs to recipe
                for input_def in recipe_def.get("inputs", []):
                    input_ref = input_def["ref"]
                    flow_edges.append({
                        "from": input_ref,
                        "to": recipe["name"],
                        "type": "input"
                    })
                
                # Create edges from recipe to outputs
                for output_def in recipe_def.get("outputs", []):
                    output_ref = output_def["ref"]
                    flow_edges.append({
                        "from": recipe["name"],
                        "to": output_ref,
                        "type": "output"
                    })
                    
            except Exception as e:
                # Skip recipes that can't be accessed
                continue
        
        # Calculate dependencies
        dependencies = {}
        for edge in flow_edges:
            if edge["type"] == "input":
                # Recipe depends on dataset
                recipe_name = edge["to"]
                dataset_name = edge["from"]
                
                if recipe_name not in dependencies:
                    dependencies[recipe_name] = {"depends_on": [], "used_by": []}
                dependencies[recipe_name]["depends_on"].append(dataset_name)
                
                if dataset_name not in dependencies:
                    dependencies[dataset_name] = {"depends_on": [], "used_by": []}
                dependencies[dataset_name]["used_by"].append(recipe_name)
            
            elif edge["type"] == "output":
                # Dataset depends on recipe
                recipe_name = edge["from"]
                dataset_name = edge["to"]
                
                if dataset_name not in dependencies:
                    dependencies[dataset_name] = {"depends_on": [], "used_by": []}
                dependencies[dataset_name]["depends_on"].append(recipe_name)
                
                if recipe_name not in dependencies:
                    dependencies[recipe_name] = {"depends_on": [], "used_by": []}
                dependencies[recipe_name]["used_by"].append(dataset_name)
        
        # Find root nodes (no dependencies) and leaf nodes (no dependents)
        root_nodes = []
        leaf_nodes = []
        
        for node_id, deps in dependencies.items():
            if not deps["depends_on"]:
                root_nodes.append(node_id)
            if not deps["used_by"]:
                leaf_nodes.append(node_id)
        
        # Calculate flow statistics
        flow_stats = {
            "total_nodes": len(flow_nodes),
            "total_edges": len(flow_edges),
            "datasets": len(datasets),
            "recipes": len(recipes),
            "root_nodes": len(root_nodes),
            "leaf_nodes": len(leaf_nodes)
        }
        
        return {
            "status": "ok",
            "project_key": project_key,
            "flow": {
                "nodes": flow_nodes,
                "edges": flow_edges
            },
            "dependencies": dependencies,
            "root_nodes": root_nodes,
            "leaf_nodes": leaf_nodes,
            "flow_stats": flow_stats
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get project flow: {str(e)}"
        }


_TOUS_TYPES = ["datasets", "recipes", "scenarios"]


def _normaliser_types(object_types: Optional[List[str]]) -> List[str]:
    """Accepte 'dataset', 'Datasets', 'recipe', 'all'... (tolérant aux LLM)."""
    if not object_types:
        return list(_TOUS_TYPES)

    types = []
    for brut in object_types:
        t = str(brut).strip().lower()
        if t in ("all", "*", "tous", "tout"):
            return list(_TOUS_TYPES)
        if not t.endswith("s"):
            t += "s"
        if t in _TOUS_TYPES and t not in types:
            types.append(t)
    return types or list(_TOUS_TYPES)


def _compiler_motif(search_term: str) -> "re.Pattern[str]":
    """Compile le terme de recherche.

    - vide, '*', '.*', 'all' : tout correspond ;
    - joker style glob ('*table*', 'client?') : converti en regex ;
    - sinon regex, ou recherche littérale si la regex est invalide.
    """
    if search_term in ("", "*", ".*", "all", "tous"):
        return re.compile("")

    if ("*" in search_term or "?" in search_term) and not re.search(
        r"[\\\[\](){}+^$|.]", search_term
    ):
        motif = re.escape(search_term).replace(r"\*", ".*").replace(r"\?", ".")
        return re.compile(motif, re.IGNORECASE)

    try:
        return re.compile(search_term, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(search_term), re.IGNORECASE)


def search_project_objects(
    project_key: str,
    search_term: str,
    object_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Search for datasets, recipes, scenarios by name/pattern.
    
    Args:
        project_key: The project key
        search_term: Search pattern (supports regex)
        object_types: List of object types to search ["datasets", "recipes", "scenarios"]
        
    Returns:
        Dict containing search results
    """
    try:
        project = get_project(project_key)
        
        object_types = _normaliser_types(object_types)
        search_term = (search_term or "").strip()
        pattern = _compiler_motif(search_term)
        
        search_results = {}
        
        # Search datasets
        if "datasets" in object_types:
            datasets = project.list_datasets()
            matching_datasets = []
            
            for dataset in datasets:
                name = dataset["name"]
                description = dataset.get("description") or ""
                tags = dataset.get("tags") or []
                
                # Check if matches
                matches = False
                if pattern:
                    matches = (pattern.search(name) or 
                              pattern.search(description) or 
                              any(pattern.search(tag) for tag in tags))
                else:
                    matches = (search_term.lower() in name.lower() or 
                              search_term.lower() in description.lower() or 
                              any(search_term.lower() in tag.lower() for tag in tags))
                
                if matches:
                    matching_datasets.append({
                        "name": name,
                        "type": dataset["type"],
                        "description": description,
                        "tags": tags,
                        "match_type": "name" if search_term.lower() in name.lower() else "metadata"
                    })
            
            search_results["datasets"] = matching_datasets
        
        # Search recipes
        if "recipes" in object_types:
            recipes = project.list_recipes()
            matching_recipes = []
            
            for recipe in recipes:
                name = recipe["name"]
                description = recipe.get("description") or ""
                tags = recipe.get("tags") or []
                
                # Check if matches
                matches = False
                if pattern:
                    matches = (pattern.search(name) or 
                              pattern.search(description) or 
                              any(pattern.search(tag) for tag in tags))
                else:
                    matches = (search_term.lower() in name.lower() or 
                              search_term.lower() in description.lower() or 
                              any(search_term.lower() in tag.lower() for tag in tags))
                
                if matches:
                    matching_recipes.append({
                        "name": name,
                        "type": recipe["type"],
                        "description": description,
                        "tags": tags,
                        "match_type": "name" if search_term.lower() in name.lower() else "metadata"
                    })
            
            search_results["recipes"] = matching_recipes
        
        # Search scenarios
        if "scenarios" in object_types:
            scenarios = project.list_scenarios()
            matching_scenarios = []
            
            for scenario in scenarios:
                name = scenario["name"]
                description = scenario.get("description") or ""
                tags = scenario.get("tags") or []
                
                # Check if matches
                matches = False
                if pattern:
                    matches = (pattern.search(name) or 
                              pattern.search(description) or 
                              any(pattern.search(tag) for tag in tags))
                else:
                    matches = (search_term.lower() in name.lower() or 
                              search_term.lower() in description.lower() or 
                              any(search_term.lower() in tag.lower() for tag in tags))
                
                if matches:
                    matching_scenarios.append({
                        "name": name,
                        "id": scenario["id"],
                        "type": scenario["type"],
                        "description": description,
                        "tags": tags,
                        "active": scenario.get("active", False),
                        "match_type": "name" if search_term.lower() in name.lower() else "metadata"
                    })
            
            search_results["scenarios"] = matching_scenarios
        
        # Calculate search statistics
        total_matches = sum(len(results) for results in search_results.values())
        search_stats = {
            "search_term": search_term,
            "object_types_searched": object_types,
            "total_matches": total_matches,
            "matches_by_type": {obj_type: len(results) for obj_type, results in search_results.items()}
        }
        
        return {
            "status": "ok",
            "project_key": project_key,
            "search_stats": search_stats,
            "results": search_results
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to search project objects: {str(e)}"
        }


def get_dataset_sample(
    project_key: str,
    dataset_name: str,
    rows: int = 100,
    columns: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Get sample data from datasets.
    
    Args:
        project_key: The project key
        dataset_name: Name of the dataset
        rows: Number of sample rows
        columns: Specific columns to include (optional)
        
    Returns:
        Dict containing sample data and schema
    """
    try:
        project = get_project(project_key)
        dataset = project.get_dataset(dataset_name)
        
        # Get dataset schema
        schema = dataset.get_schema()
        schema_columns = schema.get("columns", [])
        
        # Filter columns if specified
        if columns:
            # Validate that all requested columns exist
            available_columns = [col["name"] for col in schema_columns]
            invalid_columns = [col for col in columns if col not in available_columns]
            
            if invalid_columns:
                return {
                    "status": "error",
                    "message": f"Invalid columns: {invalid_columns}. Available columns: {available_columns}"
                }
            
            # Filter schema to requested columns
            filtered_schema_columns = [col for col in schema_columns if col["name"] in columns]
        else:
            filtered_schema_columns = schema_columns
            columns = [col["name"] for col in schema_columns]
        
        # Get sample data
        try:
            if columns and len(columns) < len(schema_columns):
                # If specific columns requested, get dataframe and select columns
                df = dataset.get_dataframe(limit=rows)
                df = df[columns]
                sample_data = df.to_dict('records')
            else:
                # Get full sample
                df = dataset.get_dataframe(limit=rows)
                sample_data = df.to_dict('records')
                
            actual_rows = len(sample_data)
            
        except Exception as e:
            # Fallback to row iterator if dataframe fails
            try:
                sample_data = []
                for i, row in enumerate(dataset.iter_rows()):
                    if i >= rows:
                        break
                    
                    # Filter to requested columns if specified
                    if columns:
                        filtered_row = {col: row.get(col) for col in columns}
                        sample_data.append(filtered_row)
                    else:
                        sample_data.append(row)
                
                actual_rows = len(sample_data)
                
            except Exception as e2:
                return {
                    "status": "error",
                    "message": f"Failed to read sample data: {str(e2)}"
                }
        
        # Calculate sample statistics
        sample_stats = {
            "requested_rows": rows,
            "actual_rows": actual_rows,
            "requested_columns": len(columns) if columns else len(schema_columns),
            "total_columns": len(schema_columns),
            "column_names": columns if columns else [col["name"] for col in schema_columns]
        }
        
        # Generate column statistics for numeric columns
        column_stats = []
        for col in filtered_schema_columns:
            col_name = col["name"]
            col_type = col["type"]
            
            col_stat = {
                "name": col_name,
                "type": col_type,
                "meaning": col.get("meaning", ""),
                "description": col.get("description", "")
            }
            
            # Calculate basic statistics for the column
            if sample_data:
                values = [row.get(col_name) for row in sample_data]
                non_null_values = [v for v in values if v is not None]
                
                col_stat["null_count"] = len(values) - len(non_null_values)
                col_stat["null_percentage"] = (len(values) - len(non_null_values)) / len(values) * 100 if values else 0
                
                if non_null_values:
                    if col_type in ["int", "bigint", "float", "double"]:
                        # Numeric statistics
                        try:
                            numeric_values = [float(v) for v in non_null_values if v is not None]
                            if numeric_values:
                                col_stat["min"] = min(numeric_values)
                                col_stat["max"] = max(numeric_values)
                                col_stat["mean"] = sum(numeric_values) / len(numeric_values)
                        except:
                            pass
                    
                    elif col_type == "string":
                        # String statistics
                        string_values = [str(v) for v in non_null_values]
                        if string_values:
                            col_stat["unique_count"] = len(set(string_values))
                            col_stat["avg_length"] = sum(len(s) for s in string_values) / len(string_values)
                            col_stat["max_length"] = max(len(s) for s in string_values)
                            col_stat["min_length"] = min(len(s) for s in string_values)
                            
                            # Most common values
                            from collections import Counter
                            value_counts = Counter(string_values)
                            col_stat["most_common"] = value_counts.most_common(5)
            
            column_stats.append(col_stat)
        
        # Get dataset metadata
        dataset_settings = dataset.get_settings()
        dataset_info = {
            "name": dataset_name,
            "type": dataset_settings.get_raw()["type"],
            "format": dataset_settings.get_raw().get("formatType", "unknown"),
            "connection": dataset_settings.get_raw().get("params", {}).get("connection", "unknown")
        }
        
        return {
            "status": "ok",
            "project_key": project_key,
            "dataset_info": dataset_info,
            "sample_stats": sample_stats,
            "schema": {
                "columns": filtered_schema_columns,
                "column_count": len(filtered_schema_columns)
            },
            "column_stats": column_stats,
            "sample_data": sample_data
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get dataset sample: {str(e)}"
        }