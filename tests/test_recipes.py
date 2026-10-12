from dataiku_mcp.tools import recipes


def test_list_recipes_flattens_inputs_outputs(dss):
    result = recipes.list_recipes("PROJ")
    assert result["status"] == "ok"
    by_name = {r["name"]: r for r in result["recipes"]}
    assert by_name["compute_mid"]["inputs"] == ["raw_in"]
    assert by_name["join_out"]["inputs"] == ["mid", "OTHER.ref_table"]
    assert recipes.list_recipes("PROJ", "join")["total_count"] == 1


def test_get_recipe_info(dss):
    result = recipes.get_recipe_info("PROJ", "compute_mid")
    assert result["status"] == "ok", result
    info = result["recipe_info"]
    assert info["type"] == "python"
    assert info["inputs"] == ["raw_in"]
    assert info["outputs"] == ["mid"]
    assert info["is_code_recipe"] is True


def test_run_recipe_success_waits_and_reports_job(dss):
    result = recipes.run_recipe("PROJ", "compute_mid")
    assert result["status"] == "ok", result
    assert result["job"]["state"] == "DONE"
    started = dss.state["jobs"][result["job"]["job_id"]]["definition"]
    assert started["type"] == "NON_RECURSIVE_FORCED_BUILD"
    assert started["outputs"][0]["id"] == "mid"


def test_run_recipe_failure_is_reported_once(dss):
    dss.state["next_job_state"] = "FAILED"
    result = recipes.run_recipe("PROJ", "compute_mid")
    assert result["status"] == "error"
    assert result["error_type"] == "job_failed"
    assert result["job"]["state"] == "FAILED"
    # A single job was started: no retry, no double execution.
    assert len([c for c in dss.writes() if c[1].endswith("/jobs/")]) == 1


def test_run_recipe_rejects_invalid_mode(dss):
    result = recipes.run_recipe("PROJ", "compute_mid", build_mode="BAD")
    assert result["error_type"] == "invalid_argument"
    assert dss.writes() == []


def test_update_recipe_code_and_tags(dss):
    result = recipes.update_recipe(
        "PROJ", "compute_mid", code="print(2)", tags=["x"], params={"engineType": "SPARK"}
    )
    assert result["status"] == "ok", result
    saved = dss.state["recipes"]["compute_mid"]
    assert saved["payload"] == "print(2)"
    assert saved["recipe"]["tags"] == ["x"]
    assert saved["recipe"]["params"]["engineType"] == "SPARK"


def test_update_recipe_code_refused_on_visual_recipe(dss):
    result = recipes.update_recipe("PROJ", "join_out", code="SELECT 1")
    assert result["error_type"] == "invalid_argument"


def test_update_recipe_unknown_field(dss):
    result = recipes.update_recipe("PROJ", "compute_mid", engine_type="SPARK")
    assert result["error_type"] == "invalid_argument"


def test_delete_recipe(dss):
    result = recipes.delete_recipe("PROJ", "join_out")
    assert result["status"] == "ok", result
    assert result["deleted_recipe"] == {"name": "join_out", "type": "join"}
    assert "join_out" not in dss.state["recipes"]


def test_create_python_recipe_with_code(dss):
    result = recipes.create_recipe(
        "PROJ", "python", "new_recipe", ["raw_in"], ["mid"], code="print('x')"
    )
    assert result["status"] == "ok", result
    assert "new_recipe" in dss.state["recipes"]


def test_unknown_recipe_returns_error(dss):
    assert recipes.get_recipe_info("PROJ", "missing")["status"] == "error"
