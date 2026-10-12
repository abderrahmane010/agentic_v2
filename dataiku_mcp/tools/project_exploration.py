"""
Project exploration tools for Dataiku MCP integration.
"""

import re
from collections import Counter
from itertools import islice
from typing import Any, Dict, List, Optional

from dataiku_mcp.client import get_project
from dataiku_mcp.tools._common import error, ok
from dataiku_mcp.tools.classification_dataset import _cartographier_flow_interne

MAX_SAMPLE_ROWS = 1000
NUMERIC_TYPES = ("tinyint", "smallint", "int", "bigint", "float", "double")


def get_project_flow(project_key: str) -> Dict[str, Any]:
    """
    Get the data flow of a project as a graph (datasets, recipes, edges).

    Args:
        project_key: The project key

    Returns:
        Dict with nodes, edges, root nodes (no producer) and leaf nodes
        (no consumer)
    """
    try:
        graph = _cartographier_flow_interne(project_key)
    except Exception as e:
        return error(f"Failed to get project flow of '{project_key}': {e}")

    nodes = [
        {
            "id": n["id"],
            "name": n["nom"],
            "kind": "dataset" if n["categorie"] == "dataset" else "recipe",
            "type": n.get("type"),
            "connection": n.get("connexion"),
        }
        for n in graph["noeuds"]
    ]
    edges = [
        {"from": a["source"], "to": a["cible"]} for a in graph["aretes"]
    ]

    has_input = {e["to"] for e in edges}
    has_output = {e["from"] for e in edges}
    roots = sorted(n["id"] for n in nodes if n["id"] not in has_input)
    leaves = sorted(n["id"] for n in nodes if n["id"] not in has_output)

    result = ok(
        project_key=project_key,
        flow={"nodes": nodes, "edges": edges},
        root_nodes=roots,
        leaf_nodes=leaves,
        flow_stats={
            "datasets": graph["statistiques"]["nb_datasets"],
            "recipes": graph["statistiques"]["nb_recettes"],
            "edges": len(edges),
            "root_nodes": len(roots),
            "leaf_nodes": len(leaves),
        },
    )
    if graph["erreurs"]:
        result["warnings"] = [
            f"Recipe {e['recette']}: {e['erreur']}" for e in graph["erreurs"]
        ]
    return result


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
        
        if object_types is None:
            object_types = ["datasets", "recipes", "scenarios"]
        
        # Compile regex pattern
        try:
            pattern = re.compile(search_term, re.IGNORECASE)
        except re.error:
            # If regex fails, use simple string matching
            pattern = None
        
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
                        "type": dataset.get("type"),
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
                        "type": recipe.get("type"),
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
                        "id": scenario.get("id"),
                        "type": scenario.get("type"),
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
        return error(f"Failed to search project objects: {e}")


def get_dataset_sample(
    project_key: str,
    dataset_name: str,
    rows: int = 100,
    columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Get the first rows of a dataset, with simple per-column statistics.

    Args:
        project_key: The project key
        dataset_name: Name of the dataset
        rows: Number of sample rows (max 1000)
        columns: Specific columns to include (optional)

    Returns:
        Dict containing sample data, schema and column statistics
    """
    rows = max(1, min(int(rows), MAX_SAMPLE_ROWS))

    try:
        dataset = get_project(project_key).get_dataset(dataset_name)
        schema_columns = dataset.get_schema().get("columns", [])
        all_names = [c["name"] for c in schema_columns]

        if columns:
            unknown = [c for c in columns if c not in all_names]
            if unknown:
                return error(
                    f"Unknown columns: {unknown}", "invalid_argument"
                )
        selected = columns or all_names
        positions = [all_names.index(c) for c in selected]

        sample_data = []
        for row in islice(dataset.iter_rows(), rows):
            sample_data.append({all_names[i]: row[i] for i in positions})

    except Exception as e:
        return error(f"Failed to read sample of '{dataset_name}': {e}")

    column_stats = []
    for col in schema_columns:
        if col["name"] not in selected:
            continue
        values = [r.get(col["name"]) for r in sample_data]
        non_null = [v for v in values if v not in (None, "")]
        stat = {
            "name": col["name"],
            "type": col.get("type"),
            "meaning": col.get("meaning"),
            "null_count": len(values) - len(non_null),
            "distinct_count": len({str(v) for v in non_null}),
        }
        if col.get("type") in NUMERIC_TYPES:
            numbers = []
            for v in non_null:
                try:
                    numbers.append(float(v))
                except (TypeError, ValueError):
                    pass
            if numbers:
                stat["min"] = min(numbers)
                stat["max"] = max(numbers)
                stat["mean"] = sum(numbers) / len(numbers)
        elif non_null:
            stat["most_common"] = Counter(
                str(v) for v in non_null
            ).most_common(5)
        column_stats.append(stat)

    return ok(
        project_key=project_key,
        dataset_name=dataset_name,
        sample_stats={
            "requested_rows": rows,
            "actual_rows": len(sample_data),
            "total_columns": len(all_names),
            "column_names": selected,
        },
        column_stats=column_stats,
        sample_data=sample_data,
    )
