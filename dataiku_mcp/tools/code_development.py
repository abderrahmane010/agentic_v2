"""
Code and recipe development tools for Dataiku MCP integration.
"""

import ast
import re
import json
import tempfile
import traceback
from typing import Dict, Any, List, Optional
from dataiku_mcp.client import get_client, get_project

def get_recipe_code(
    project_key: str,
    recipe_name: str
) -> Dict[str, Any]:
    """
    Extract actual Python/SQL code from recipes.
    
    Args:
        project_key: The project key
        recipe_name: Name of the recipe
        
    Returns:
        Dict containing code and recipe information
    """
    try:
        project = get_project(project_key)
        recipe = project.get_recipe(recipe_name)
        settings = recipe.get_settings()
        
        # Get recipe metadata
        try:
            recipe_definition = recipe.get_definition()
            recipe_type = recipe_definition.get("type", "unknown")
            inputs = [inp["ref"] for inp in recipe_definition.get("inputs", [])]
            outputs = [out["ref"] for out in recipe_definition.get("outputs", [])]
        except AttributeError:
            # Fallback for older API versions
            try:
                recipe_def_payload = recipe.get_definition_and_payload()
                payload = recipe_def_payload.get_payload()
                if isinstance(payload, dict):
                    recipe_type = payload.get("type", "unknown")
                else:
                    recipe_type = "unknown"
                inputs = []
                outputs = []
            except:
                recipe_type = "unknown"
                inputs = []
                outputs = []
        
        recipe_info = {
            "name": recipe_name,
            "type": recipe_type,
            "engine": settings.get_recipe_params().get("engine", "unknown"),
            "inputs": inputs,
            "outputs": outputs
        }
        
        # Extract code based on recipe type
        code = ""
        code_info = {}
        
        if recipe_type in ["python", "r", "scala"]:
            # Code recipes
            code = settings.get_code()
            code_info = {
                "language": recipe_type,
                "line_count": len(code.split('\n')) if code else 0,
                "char_count": len(code) if code else 0
            }
            
        elif recipe_type == "sql":
            # SQL recipes
            code = settings.get_code()
            code_info = {
                "language": "sql",
                "line_count": len(code.split('\n')) if code else 0,
                "char_count": len(code) if code else 0
            }
            
        elif recipe_type == "pyspark":
            # PySpark recipes
            code = settings.get_code()
            code_info = {
                "language": "python",
                "engine": "pyspark",
                "line_count": len(code.split('\n')) if code else 0,
                "char_count": len(code) if code else 0
            }
            
        elif recipe_type in ["join", "grouping", "window", "distinct", "sort", "topn", "sync"]:
            # Visual recipes - extract configuration as "pseudo-code"
            recipe_params = settings.get_recipe_params()
            code = json.dumps(recipe_params, indent=2)
            code_info = {
                "language": "json",
                "type": "visual_recipe_config",
                "line_count": len(code.split('\n')) if code else 0,
                "char_count": len(code) if code else 0
            }
            
        else:
            # Other recipe types
            try:
                code = settings.get_code()
                code_info = {
                    "language": "unknown",
                    "line_count": len(code.split('\n')) if code else 0,
                    "char_count": len(code) if code else 0
                }
            except:
                # For recipes without code, get the configuration
                recipe_params = settings.get_recipe_params()
                code = json.dumps(recipe_params, indent=2)
                code_info = {
                    "language": "json",
                    "type": "recipe_config",
                    "line_count": len(code.split('\n')) if code else 0,
                    "char_count": len(code) if code else 0
                }
        
        return {
            "status": "ok",
            "recipe_info": recipe_info,
            "code": code,
            "code_info": code_info
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get recipe code for '{recipe_name}': {str(e)}"
        }


def validate_recipe_syntax(
    project_key: str,
    recipe_name: str,
    code: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate Python/SQL syntax before execution.
    
    Args:
        project_key: The project key
        recipe_name: Name of the recipe
        code: Optional code to validate (if not provided, gets from recipe)
        
    Returns:
        Dict containing validation results
    """
    try:
        project = get_project(project_key)
        recipe = project.get_recipe(recipe_name)
        
        # Get code to validate
        if code is None:
            settings = recipe.get_settings()
            code = settings.get_code()
        
        if not code or not code.strip():
            return {
                "status": "ok",
                "valid": True,
                "message": "No code to validate (empty recipe)",
                "errors": []
            }
        
        try:
            recipe_definition = recipe.get_definition()
            recipe_type = recipe_definition.get("type", "unknown")
        except AttributeError:
            # Fallback for older API versions
            recipe_def_payload = recipe.get_definition_and_payload()
            recipe_type = recipe_def_payload.get_payload().get("type", "unknown")
        validation_results = {
            "recipe_name": recipe_name,
            "recipe_type": recipe_type,
            "code_length": len(code),
            "line_count": len(code.split('\n'))
        }
        
        errors = []
        warnings = []
        
        # Validate based on recipe type
        if recipe_type in ["python", "pyspark"]:
            # Python syntax validation
            try:
                ast.parse(code)
                validation_results["python_ast_valid"] = True
            except SyntaxError as e:
                errors.append({
                    "type": "syntax_error",
                    "line": e.lineno,
                    "column": e.offset,
                    "message": str(e.msg),
                    "text": e.text.strip() if e.text else ""
                })
                validation_results["python_ast_valid"] = False
            except Exception as e:
                errors.append({
                    "type": "parse_error",
                    "message": f"Failed to parse Python code: {str(e)}"
                })
                validation_results["python_ast_valid"] = False
            
            # Check for common Dataiku patterns
            if "dataiku" not in code.lower():
                warnings.append({
                    "type": "missing_dataiku_import",
                    "message": "Code doesn't seem to import dataiku package"
                })
            
            # Check for input/output dataset handling
            if "get_dataframe" not in code and "iter_rows" not in code:
                warnings.append({
                    "type": "no_input_handling",
                    "message": "Code doesn't seem to handle input datasets"
                })
            
            if "write_with_schema" not in code and "write_dataframe" not in code:
                warnings.append({
                    "type": "no_output_handling",
                    "message": "Code doesn't seem to write to output datasets"
                })
                
        elif recipe_type == "sql":
            # SQL syntax validation (basic)
            sql_errors = []
            
            # Basic SQL syntax checks
            if not re.search(r'\bSELECT\b', code, re.IGNORECASE):
                sql_errors.append({
                    "type": "missing_select",
                    "message": "SQL code should contain a SELECT statement"
                })
            
            # Check for balanced parentheses
            if code.count('(') != code.count(')'):
                sql_errors.append({
                    "type": "unbalanced_parentheses",
                    "message": "Unbalanced parentheses in SQL code"
                })
            
            # Check for unterminated strings
            single_quotes = code.count("'") - code.count("\\'")
            double_quotes = code.count('"') - code.count('\\"')
            
            if single_quotes % 2 != 0:
                sql_errors.append({
                    "type": "unterminated_string",
                    "message": "Unterminated single-quoted string"
                })
            
            if double_quotes % 2 != 0:
                sql_errors.append({
                    "type": "unterminated_string",
                    "message": "Unterminated double-quoted string"
                })
            
            errors.extend(sql_errors)
            validation_results["sql_basic_valid"] = len(sql_errors) == 0
            
        elif recipe_type == "r":
            # R syntax validation (basic)
            r_errors = []
            
            # Check for balanced parentheses and brackets
            if code.count('(') != code.count(')'):
                r_errors.append({
                    "type": "unbalanced_parentheses",
                    "message": "Unbalanced parentheses in R code"
                })
            
            if code.count('[') != code.count(']'):
                r_errors.append({
                    "type": "unbalanced_brackets",
                    "message": "Unbalanced brackets in R code"
                })
            
            if code.count('{') != code.count('}'):
                r_errors.append({
                    "type": "unbalanced_braces",
                    "message": "Unbalanced braces in R code"
                })
            
            errors.extend(r_errors)
            validation_results["r_basic_valid"] = len(r_errors) == 0
            
        else:
            # For other recipe types, just check if it's valid JSON (for visual recipes)
            try:
                json.loads(code)
                validation_results["json_valid"] = True
            except json.JSONDecodeError as e:
                validation_results["json_valid"] = False
                # This might not be JSON, which is fine for some recipe types
        
        # Overall validation result
        is_valid = len(errors) == 0
        
        return {
            "status": "ok",
            "valid": is_valid,
            "validation_results": validation_results,
            "errors": errors,
            "warnings": warnings,
            "error_count": len(errors),
            "warning_count": len(warnings)
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to validate recipe syntax: {str(e)}"
        }


def test_recipe_dry_run(
    project_key: str,
    recipe_name: str,
    sample_rows: int = 100
) -> Dict[str, Any]:
    """
    Test recipe logic without actual execution.
    
    Args:
        project_key: The project key
        recipe_name: Name of the recipe
        sample_rows: Number of sample rows to test with
        
    Returns:
        Dict containing test results
    """
    try:
        project = get_project(project_key)
        recipe = project.get_recipe(recipe_name)
        settings = recipe.get_settings()
        
        # Get recipe information
        try:
            recipe_def = recipe.get_definition()
            inputs = [inp["ref"] for inp in recipe_def["inputs"]]
            outputs = [out["ref"] for out in recipe_def["outputs"]]
            recipe_type = recipe_def.get("type", "unknown")
        except AttributeError:
            # Fallback for older API versions
            try:
                recipe_def_payload = recipe.get_definition_and_payload()
                payload = recipe_def_payload.get_payload()
                if isinstance(payload, dict):
                    recipe_type = payload.get("type", "unknown")
                else:
                    recipe_type = "unknown"
                inputs = []
                outputs = []
            except:
                recipe_type = "unknown"
                inputs = []
                outputs = []
        test_results = {
            "recipe_name": recipe_name,
            "recipe_type": recipe_type,
            "inputs": inputs,
            "outputs": outputs,
            "sample_rows": sample_rows
        }
        
        # Check if inputs exist and are accessible
        input_checks = []
        for input_name in inputs:
            try:
                input_dataset = project.get_dataset(input_name)
                schema = input_dataset.get_schema()
                
                # Try to get sample data
                try:
                    sample_df = input_dataset.get_dataframe(limit=sample_rows)
                    input_info = {
                        "name": input_name,
                        "status": "ok",
                        "schema_columns": len(schema["columns"]),
                        "sample_rows": len(sample_df),
                        "sample_columns": list(sample_df.columns) if hasattr(sample_df, 'columns') else []
                    }
                except Exception as e:
                    input_info = {
                        "name": input_name,
                        "status": "warning",
                        "message": f"Could not read sample data: {str(e)}",
                        "schema_columns": len(schema["columns"]) if schema else 0
                    }
                
                input_checks.append(input_info)
                
            except Exception as e:
                input_checks.append({
                    "name": input_name,
                    "status": "error",
                    "message": f"Input dataset not accessible: {str(e)}"
                })
        
        test_results["input_checks"] = input_checks
        
        # Check if outputs are properly configured
        output_checks = []
        for output_name in outputs:
            try:
                output_dataset = project.get_dataset(output_name)
                output_info = {
                    "name": output_name,
                    "status": "ok",
                    "exists": True,
                    "type": output_dataset.get_settings().get_raw()["type"]
                }
            except Exception as e:
                output_info = {
                    "name": output_name,
                    "status": "warning",
                    "exists": False,
                    "message": f"Output dataset will be created: {str(e)}"
                }
            
            output_checks.append(output_info)
        
        test_results["output_checks"] = output_checks
        
        # For Python recipes, try to validate the code structure
        if recipe_type in ["python", "pyspark"]:
            try:
                code = settings.get_code()
                
                # Parse the code to check for basic structure
                tree = ast.parse(code)
                
                # Check for dataiku imports
                has_dataiku_import = False
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == "dataiku":
                                has_dataiku_import = True
                    elif isinstance(node, ast.ImportFrom):
                        if node.module == "dataiku":
                            has_dataiku_import = True
                
                # Check for dataset operations
                has_input_read = "get_dataframe" in code or "iter_rows" in code
                has_output_write = "write_with_schema" in code or "write_dataframe" in code
                
                code_analysis = {
                    "has_dataiku_import": has_dataiku_import,
                    "has_input_read": has_input_read,
                    "has_output_write": has_output_write,
                    "line_count": len(code.split('\n')),
                    "ast_valid": True
                }
                
                test_results["code_analysis"] = code_analysis
                
            except Exception as e:
                test_results["code_analysis"] = {
                    "ast_valid": False,
                    "error": str(e)
                }
        
        # Generate test summary
        input_errors = sum(1 for check in input_checks if check["status"] == "error")
        output_errors = sum(1 for check in output_checks if check["status"] == "error")
        
        test_summary = {
            "overall_status": "ok" if input_errors == 0 and output_errors == 0 else "warning",
            "input_errors": input_errors,
            "output_errors": output_errors,
            "ready_for_execution": input_errors == 0,
            "recommendations": []
        }
        
        # Add recommendations
        if input_errors > 0:
            test_summary["recommendations"].append("Fix input dataset access issues before running")
        
        if recipe_type in ["python", "pyspark"]:
            code_analysis = test_results.get("code_analysis", {})
            if not code_analysis.get("has_dataiku_import", False):
                test_summary["recommendations"].append("Add 'import dataiku' to your code")
            if not code_analysis.get("has_input_read", False):
                test_summary["recommendations"].append("Add code to read input datasets")
            if not code_analysis.get("has_output_write", False):
                test_summary["recommendations"].append("Add code to write output datasets")
        
        test_results["test_summary"] = test_summary
        
        return {
            "status": "ok",
            "test_results": test_results
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to perform dry run test: {str(e)}"
        }


def get_generated_sql(
    project_key: str,
    recipe_name: str,
    partition: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extract generated SQL from visual recipes (Shaker, Join, SQL-based recipes, etc.).
    
    This tool attempts to retrieve the actual SQL query that Dataiku will execute
    for recipes that use SQL engines. For Shaker recipes, it provides the recipe
    configuration since SQL is generated dynamically at runtime.
    
    Args:
        project_key: The project key
        recipe_name: Name of the recipe
        partition: Optional partition specification for partitioned datasets
        
    Returns:
        Dict containing generated SQL and recipe information
    """
    try:
        client = get_client()
        project = client.get_project(project_key)
        recipe = project.get_recipe(recipe_name)
        
        # Get recipe metadata
        try:
            recipe_def = recipe.get_definition()
            recipe_type = recipe_def.get("type", "unknown")
            
            # Get inputs from the recipe definition
            inputs_def = recipe_def.get("inputs", {})
            inputs = []
            for role, items in inputs_def.items():
                if isinstance(items, dict) and "items" in items:
                    inputs.extend([item.get("ref") for item in items.get("items", [])])
                elif isinstance(items, list):
                    inputs.extend([item.get("ref") for item in items])
            
            # Get outputs from the recipe definition
            outputs_def = recipe_def.get("outputs", {})
            outputs = []
            for role, items in outputs_def.items():
                if isinstance(items, dict) and "items" in items:
                    outputs.extend([item.get("ref") for item in items.get("items", [])])
                elif isinstance(items, list):
                    outputs.extend([item.get("ref") for item in items])
        except Exception as e:
            recipe_type = "unknown"
            inputs = []
            outputs = []
        
        recipe_info = {
            "name": recipe_name,
            "type": recipe_type,
            "inputs": inputs,
            "outputs": outputs
        }
        
        generated_sql = None
        method_used = None
        shaker_steps = None
        additional_info = {}
        
        # Method 1: For SQL recipe type, get code directly
        if recipe_type == "sql":
            settings = recipe.get_settings()
            generated_sql = settings.get_code()
            method_used = "direct_sql_code"
        
        # Method 2: For Shaker recipes, extract the preparation script and try to get SQL
        elif recipe_type == "shaker":
            try:
                settings = recipe.get_settings()
                raw_payload = settings.get_json_payload()
                
                # Extract the preparation steps (shaker script)
                shaker_script = raw_payload.get("script", {})
                steps = shaker_script.get("steps", [])
                
                if steps:
                    shaker_steps = []
                    for i, step in enumerate(steps):
                        step_info = {
                            "step_number": i + 1,
                            "type": step.get("type", "unknown"),
                            "name": step.get("name", ""),
                            "disabled": step.get("disabled", False),
                            "params": step.get("params", {})
                        }
                        
                        # Extract key information based on step type
                        step_type = step.get("type", "")
                        params = step.get("params", {})
                        
                        if step_type == "ColumnRenamer":
                            step_info["renamings"] = params.get("renamings", [])
                        elif step_type == "FilterOnValue":
                            step_info["column"] = params.get("column", "")
                            step_info["values"] = params.get("values", [])
                            step_info["matchingMode"] = params.get("matchingMode", "")
                            step_info["action"] = params.get("action", "")
                        elif step_type == "CreateColumnWithGREL":
                            step_info["column"] = params.get("column", "")
                            step_info["expression"] = params.get("expression", "")
                        elif step_type == "ColumnsSelector":
                            step_info["columns"] = params.get("columns", [])
                            step_info["keep"] = params.get("keep", True)
                        elif step_type == "FilterOnBadType":
                            step_info["column"] = params.get("column", "")
                            step_info["type"] = params.get("type", "")
                        elif step_type == "RemoveRowsOnEmpty":
                            step_info["columns"] = params.get("columns", [])
                        elif step_type == "FillEmptyWithValue":
                            step_info["column"] = params.get("column", "")
                            step_info["value"] = params.get("value", "")
                        elif step_type == "Unnest":
                            step_info["column"] = params.get("column", "")
                            step_info["separator"] = params.get("separator", "")
                        
                        shaker_steps.append(step_info)
                    
                    # Generate pseudo-SQL from shaker steps
                    generated_sql = _generate_sql_from_shaker_steps(inputs, outputs, shaker_steps)
                    method_used = "shaker_steps_to_sql"
                    additional_info["shaker_steps"] = shaker_steps
                    additional_info["total_steps"] = len(steps)
                
                # Also get engine params
                engine_params = raw_payload.get("engineParams", {})
                additional_info["engine_type"] = engine_params.get("engineType", "unknown")
                
            except Exception as e:
                additional_info["shaker_extraction_error"] = str(e)
        
        # Method 3: For other visual recipes (join, grouping, etc.)
        elif recipe_type in ["join", "grouping", "window", "distinct", "sort", "topn", "split", "vstack", "sampling"]:
            try:
                settings = recipe.get_settings()
                raw_payload = settings.get_json_payload()
                
                # Try to generate SQL based on recipe type
                if recipe_type == "join":
                    generated_sql = _generate_sql_from_join(raw_payload, inputs, outputs)
                    method_used = "join_to_sql"
                elif recipe_type == "grouping":
                    generated_sql = _generate_sql_from_grouping(raw_payload, inputs, outputs)
                    method_used = "grouping_to_sql"
                elif recipe_type == "distinct":
                    generated_sql = _generate_sql_from_distinct(raw_payload, inputs, outputs)
                    method_used = "distinct_to_sql"
                elif recipe_type == "sort":
                    generated_sql = _generate_sql_from_sort(raw_payload, inputs, outputs)
                    method_used = "sort_to_sql"
                elif recipe_type == "sampling":
                    generated_sql = _generate_sql_from_sampling(raw_payload, inputs, outputs)
                    method_used = "sampling_to_sql"
                else:
                    # Fallback: return the raw configuration
                    generated_sql = json.dumps(raw_payload, indent=2)
                    method_used = f"{recipe_type}_config"
                    
            except Exception as e:
                additional_info["visual_recipe_error"] = str(e)
        
        # Method 4: Try to get SQL from job logs (last successful run)
        if generated_sql is None or method_used == "recipe_config_fallback":
            try:
                # Get recent jobs for this recipe
                jobs = project.list_jobs()
                recipe_jobs = []
                
                for job in jobs:
                    job_def = job.get_definition()
                    if job_def.get("type") == "NON_RECURSIVE_FORCED_BUILD":
                        # Check if this job is for our recipe
                        outputs_list = job_def.get("outputs", [])
                        for output_item in outputs_list:
                            if output_item.get("type") == "DATASET":
                                if output_item.get("itemId") in outputs:
                                    recipe_jobs.append(job)
                                    break
                
                # Get the most recent job's logs
                if recipe_jobs:
                    latest_job = recipe_jobs[0]
                    job_status = latest_job.get_status()
                    
                    # Try to get activities/logs
                    try:
                        activities = latest_job.get_log()
                        if activities:
                            # Search for SQL in logs
                            sql_patterns = []
                            for line in activities.split('\n'):
                                if 'SELECT' in line.upper() or 'INSERT' in line.upper():
                                    sql_patterns.append(line)
                            
                            if sql_patterns:
                                additional_info["sql_from_logs"] = sql_patterns[:10]  # First 10 matches
                    except:
                        pass
                        
            except Exception as e:
                additional_info["job_logs_error"] = str(e)
        
        # Fallback: provide recipe configuration
        if generated_sql is None:
            try:
                settings = recipe.get_settings()
                recipe_params = settings.get_recipe_params()
                generated_sql = json.dumps(recipe_params, indent=2)
                method_used = "recipe_config_fallback"
            except:
                generated_sql = "SQL generation not available for this recipe type"
                method_used = "unavailable"
        
        result = {
            "status": "ok" if generated_sql else "warning",
            "recipe_info": recipe_info,
            "generated_sql": generated_sql,
            "method_used": method_used
        }
        
        if shaker_steps:
            result["shaker_steps"] = shaker_steps
            
        if additional_info:
            result["additional_info"] = additional_info
        
        return result
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get generated SQL for '{recipe_name}': {str(e)}",
            "traceback": traceback.format_exc()
        }


def _generate_sql_from_shaker_steps(inputs: List[str], outputs: List[str], steps: List[Dict]) -> str:
    """
    Generate pseudo-SQL from Shaker preparation steps.
    """
    input_table = inputs[0] if inputs else "input_table"
    output_table = outputs[0] if outputs else "output_table"
    
    sql_parts = []
    sql_parts.append(f"-- Generated SQL representation of Shaker recipe")
    sql_parts.append(f"-- Input: {input_table}")
    sql_parts.append(f"-- Output: {output_table}")
    sql_parts.append(f"-- Total steps: {len(steps)}")
    sql_parts.append("")
    
    select_columns = ["*"]
    where_clauses = []
    column_transforms = []
    column_renames = {}
    columns_to_keep = None
    columns_to_remove = []
    
    for step in steps:
        if step.get("disabled"):
            continue
            
        step_type = step.get("type", "")
        params = step.get("params", {})
        
        sql_parts.append(f"-- Step {step.get('step_number')}: {step_type}")
        
        if step_type == "ColumnRenamer":
            for rename in step.get("renamings", []):
                old_name = rename.get("from", "")
                new_name = rename.get("to", "")
                if old_name and new_name:
                    column_renames[old_name] = new_name
                    sql_parts.append(f"--   Rename: {old_name} -> {new_name}")
        
        elif step_type == "FilterOnValue":
            column = step.get("column", "")
            values = step.get("values", [])
            action = step.get("action", "KEEP_ROW")
            matching_mode = step.get("matchingMode", "FULL_STRING")
            
            if column and values:
                if matching_mode == "FULL_STRING":
                    value_list = ", ".join([f"'{v}'" for v in values])
                    if action == "KEEP_ROW":
                        where_clauses.append(f"{column} IN ({value_list})")
                    else:
                        where_clauses.append(f"{column} NOT IN ({value_list})")
                elif matching_mode == "SUBSTRING":
                    conditions = [f"{column} LIKE '%{v}%'" for v in values]
                    if action == "KEEP_ROW":
                        where_clauses.append(f"({' OR '.join(conditions)})")
                    else:
                        where_clauses.append(f"NOT ({' OR '.join(conditions)})")
        
        elif step_type == "CreateColumnWithGREL":
            column = step.get("column", "")
            expression = step.get("expression", "")
            if column and expression:
                column_transforms.append(f"  ({expression}) AS {column}")
                sql_parts.append(f"--   Create column: {column} = {expression}")
        
        elif step_type == "ColumnsSelector":
            columns = step.get("columns", [])
            keep = step.get("keep", True)
            if keep:
                columns_to_keep = columns
                sql_parts.append(f"--   Keep columns: {', '.join(columns)}")
            else:
                columns_to_remove.extend(columns)
                sql_parts.append(f"--   Remove columns: {', '.join(columns)}")
        
        elif step_type == "RemoveRowsOnEmpty":
            columns = step.get("columns", [])
            for col in columns:
                where_clauses.append(f"{col} IS NOT NULL")
                where_clauses.append(f"TRIM({col}) != ''")
        
        elif step_type == "FillEmptyWithValue":
            column = step.get("column", "")
            value = step.get("value", "")
            if column:
                column_transforms.append(f"  COALESCE({column}, '{value}') AS {column}")
        
        elif step_type == "FilterOnBadType":
            column = step.get("column", "")
            type_check = step.get("type", "")
            if column and type_check:
                sql_parts.append(f"--   Filter bad type on {column} (expected: {type_check})")
    
    sql_parts.append("")
    sql_parts.append("-- Equivalent SQL:")
    sql_parts.append(f"INSERT INTO {output_table}")
    sql_parts.append("SELECT")
    
    # Build SELECT clause
    if columns_to_keep:
        select_items = []
        for col in columns_to_keep:
            if col in column_renames:
                select_items.append(f"  {col} AS {column_renames[col]}")
            else:
                select_items.append(f"  {col}")
        sql_parts.append(",\n".join(select_items))
    elif column_transforms:
        sql_parts.append(",\n".join(column_transforms))
    else:
        sql_parts.append("  *")
    
    sql_parts.append(f"FROM {input_table}")
    
    # Add WHERE clauses
    if where_clauses:
        sql_parts.append("WHERE")
        sql_parts.append("  " + "\n  AND ".join(where_clauses))
    
    return "\n".join(sql_parts)


def _generate_sql_from_join(payload: Dict, inputs: List[str], outputs: List[str]) -> str:
    """Generate SQL from a Join recipe configuration."""
    output_table = outputs[0] if outputs else "output_table"
    
    sql_parts = ["-- Generated SQL from Join recipe"]
    
    joins = payload.get("joins", [])
    
    if len(inputs) >= 2:
        left_table = inputs[0]
        right_table = inputs[1]
        
        sql_parts.append(f"INSERT INTO {output_table}")
        sql_parts.append("SELECT *")
        sql_parts.append(f"FROM {left_table} AS left_table")
        
        for join in joins:
            join_type = join.get("type", "LEFT")
            on_conditions = join.get("on", [])
            
            conditions = []
            for cond in on_conditions:
                left_col = cond.get("left", {}).get("column", "")
                right_col = cond.get("right", {}).get("column", "")
                if left_col and right_col:
                    conditions.append(f"left_table.{left_col} = right_table.{right_col}")
            
            sql_parts.append(f"{join_type} JOIN {right_table} AS right_table")
            if conditions:
                sql_parts.append(f"  ON {' AND '.join(conditions)}")
    
    return "\n".join(sql_parts)


def _generate_sql_from_grouping(payload: Dict, inputs: List[str], outputs: List[str]) -> str:
    """Generate SQL from a Grouping recipe configuration."""
    input_table = inputs[0] if inputs else "input_table"
    output_table = outputs[0] if outputs else "output_table"
    
    sql_parts = ["-- Generated SQL from Grouping recipe"]
    
    keys = payload.get("keys", [])
    values = payload.get("values", [])
    
    select_items = []
    
    # Add group by keys
    for key in keys:
        col = key.get("column", "")
        if col:
            select_items.append(col)
    
    # Add aggregations
    for val in values:
        col = val.get("column", "")
        agg_type = val.get("type", "")
        if col and agg_type:
            select_items.append(f"{agg_type}({col}) AS {col}_{agg_type.lower()}")
    
    sql_parts.append(f"INSERT INTO {output_table}")
    sql_parts.append("SELECT")
    sql_parts.append("  " + ",\n  ".join(select_items) if select_items else "  *")
    sql_parts.append(f"FROM {input_table}")
    
    if keys:
        group_cols = [k.get("column", "") for k in keys if k.get("column")]
        if group_cols:
            sql_parts.append(f"GROUP BY {', '.join(group_cols)}")
    
    return "\n".join(sql_parts)


def _generate_sql_from_distinct(payload: Dict, inputs: List[str], outputs: List[str]) -> str:
    """Generate SQL from a Distinct recipe configuration."""
    input_table = inputs[0] if inputs else "input_table"
    output_table = outputs[0] if outputs else "output_table"
    
    columns = payload.get("columns", [])
    
    sql_parts = ["-- Generated SQL from Distinct recipe"]
    sql_parts.append(f"INSERT INTO {output_table}")
    sql_parts.append("SELECT DISTINCT")
    
    if columns:
        sql_parts.append("  " + ", ".join(columns))
    else:
        sql_parts.append("  *")
    
    sql_parts.append(f"FROM {input_table}")
    
    return "\n".join(sql_parts)


def _generate_sql_from_sort(payload: Dict, inputs: List[str], outputs: List[str]) -> str:
    """Generate SQL from a Sort recipe configuration."""
    input_table = inputs[0] if inputs else "input_table"
    output_table = outputs[0] if outputs else "output_table"
    
    orders = payload.get("orders", [])
    
    sql_parts = ["-- Generated SQL from Sort recipe"]
    sql_parts.append(f"INSERT INTO {output_table}")
    sql_parts.append("SELECT *")
    sql_parts.append(f"FROM {input_table}")
    
    if orders:
        order_clauses = []
        for order in orders:
            col = order.get("column", "")
            direction = "DESC" if order.get("desc", False) else "ASC"
            if col:
                order_clauses.append(f"{col} {direction}")
        
        if order_clauses:
            sql_parts.append(f"ORDER BY {', '.join(order_clauses)}")
    
    return "\n".join(sql_parts)


def _generate_sql_from_sampling(payload: Dict, inputs: List[str], outputs: List[str]) -> str:
    """Generate SQL from a Sampling recipe configuration."""
    input_table = inputs[0] if inputs else "input_table"
    output_table = outputs[0] if outputs else "output_table"
    
    sampling_method = payload.get("samplingMethod", "RANDOM")
    max_records = payload.get("maxRecords", 10000)
    
    sql_parts = ["-- Generated SQL from Sampling recipe"]
    sql_parts.append(f"-- Sampling method: {sampling_method}")
    sql_parts.append(f"INSERT INTO {output_table}")
    sql_parts.append("SELECT *")
    sql_parts.append(f"FROM {input_table}")
    
    if sampling_method == "RANDOM":
        sql_parts.append("ORDER BY RAND()")
    
    sql_parts.append(f"LIMIT {max_records}")
    
    return "\n".join(sql_parts)