import json

import yaml

from dataiku_mcp.tools import code_development, productivity


# Productivity -----------------------------------------------------------
def test_duplicate_is_dry_run_by_default(dss):
    result = productivity.duplicate_project_structure("PROJ", "PROJ_COPY")
    assert result["status"] == "ok", result
    assert result["dry_run"] is True
    assert result["duplication_summary"]["recipes"] == 2
    assert dss.writes() == []


def test_duplicate_uses_native_duplication(dss):
    result = productivity.duplicate_project_structure(
        "PROJ", "PROJ_COPY", include_data=True,
        connection_remapping={"pg": "pg_test"}, dry_run=False,
    )
    assert result["status"] == "ok", result
    assert result["duplication_summary"]["duplication_mode"] == "FULL"
    assert dss.writes() == [("POST", "/projects/PROJ/duplicate/")]


def test_export_project_config(dss):
    result = productivity.export_project_config("PROJ", "yaml")
    assert result["status"] == "ok", result
    config = yaml.safe_load(result["content"])
    recipes = {r["name"]: r for r in config["recipes"]}
    assert recipes["compute_mid"]["code"].startswith("import dataiku")
    assert recipes["join_out"]["payload"] == {"joins": []}
    assert config["variables"]["standard"]["db_password"] == "***HIDDEN***"
    scenarios = {s["id"]: s for s in config["scenarios"]}
    assert scenarios["SC2"]["script"] == "print('scenario')"
    assert json.loads(productivity.export_project_config("PROJ")["content"])


def test_batch_update_dry_run_then_apply(dss):
    dry = productivity.batch_update_objects("PROJ", "datasets", "^r", {"tags": ["batch"]})
    assert dry["matching_objects"] == ["raw_in"]
    assert dss.writes() == []
    applied = productivity.batch_update_objects(
        "PROJ", "datasets", "^r", {"tags": ["batch"]}, dry_run=False
    )
    assert applied["status"] == "ok", applied
    assert dss.state["datasets"]["raw_in"]["tags"] == ["batch"]


def test_batch_update_scenarios_by_name(dss):
    result = productivity.batch_update_objects(
        "PROJ", "scenarios", "python", {"active": True}, dry_run=False
    )
    assert result["updated_objects"] == ["SC2"]
    assert dss.state["scenarios"]["SC2"]["active"] is True


def test_batch_update_invalid_pattern(dss):
    result = productivity.batch_update_objects("PROJ", "datasets", "(", {"tags": []})
    assert result["error_type"] == "invalid_argument"


# Code development -------------------------------------------------------
def test_get_recipe_code_python(dss):
    result = code_development.get_recipe_code("PROJ", "compute_mid")
    assert result["status"] == "ok", result
    assert result["code"].startswith("import dataiku")
    assert result["code_info"]["language"] == "python"
    assert result["recipe_info"]["inputs"] == ["raw_in"]


def test_get_recipe_code_visual(dss):
    result = code_development.get_recipe_code("PROJ", "join_out")
    assert result["status"] == "ok", result
    assert result["code_info"]["type"] == "visual_recipe_config"
    assert json.loads(result["code"])["payload"] == {"joins": []}


def test_validate_recipe_syntax(dss):
    ok = code_development.validate_recipe_syntax("PROJ", "compute_mid")
    assert ok["status"] == "ok", ok
    bad = code_development.validate_recipe_syntax("PROJ", "compute_mid", code="def (:")
    assert bad["valid"] is False
    visual = code_development.validate_recipe_syntax("PROJ", "join_out")
    assert visual["error_type"] == "invalid_argument"


def test_dry_run_recipe(dss):
    result = code_development.test_recipe_dry_run("PROJ", "compute_mid", sample_rows=2)
    assert result["status"] == "ok", result
    checks = result["test_results"]["input_checks"]
    assert checks[0]["status"] == "ok"
    assert checks[0]["sample_rows"] == 2


def test_get_generated_sql_visual(dss):
    result = code_development.get_generated_sql("PROJ", "join_out")
    assert result["status"] == "ok", result
    assert result["recipe_info"]["outputs"] == ["out"]


def test_visual_recipe_with_empty_payload(dss):
    dss.state["recipes"]["join_out"]["payload"] = ""
    code = code_development.get_recipe_code("PROJ", "join_out")
    assert code["status"] == "ok", code
    export = productivity.export_project_config("PROJ")
    assert "warnings" not in export, export.get("warnings")
    recipes = {r["name"]: r for r in export["config"]["recipes"]}
    assert recipes["join_out"]["payload"] is None


def test_visual_recipe_with_non_json_payload(dss):
    dss.state["recipes"]["join_out"]["payload"] = "not json"
    export = productivity.export_project_config("PROJ")
    recipes = {r["name"]: r for r in export["config"]["recipes"]}
    assert recipes["join_out"]["payload"] == "not json"
