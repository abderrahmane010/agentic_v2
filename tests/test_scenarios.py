from dataiku_mcp.tools import advanced_scenarios, scenarios


def test_list_scenarios_with_triggers(dss):
    result = scenarios.list_scenarios("PROJ")
    assert result["status"] == "ok", result
    sc1 = next(s for s in result["scenarios"] if s["id"] == "SC1")
    assert [t["type"] for t in sc1["triggers"]] == ["temporal", "ds_modified"]
    assert sc1["triggers"][1]["datasets"] == ["PROJ.out"]
    assert scenarios.list_scenarios("PROJ", active_only=True)["total_count"] == 1


def test_get_scenario_info(dss):
    result = scenarios.get_scenario_info("PROJ", "SC1")
    assert result["status"] == "ok", result
    info = result["scenario_info"]
    assert info["name"] == "Daily build"
    assert info["step_count"] == 2
    assert info["last_run"]["run_id"] == "run-2"
    assert info["last_run"]["outcome"] == "FAILED"
    assert info["next_run"].startswith("2027")


def test_run_history(dss):
    result = scenarios.get_scenario_run_history("PROJ", "SC1")
    assert result["status"] == "ok", result
    assert [r["outcome"] for r in result["run_history"]] == ["FAILED", "SUCCESS"]
    assert result["run_history"][1]["duration_seconds"] == 30.0


def test_add_daily_trigger(dss):
    result = scenarios.add_scenario_trigger("PROJ", "SC1", "daily", hour=5, minute=30)
    assert result["status"] == "ok", result
    trigger = dss.state["scenarios"]["SC1"]["triggers"][-1]
    assert trigger["params"]["frequency"] == "Daily"
    assert trigger["params"]["hour"] == 5


def test_add_raw_trigger(dss):
    raw = dss.state["scenarios"]["SC1"]["triggers"][1]
    result = scenarios.add_scenario_trigger("PROJ", "SC2", "raw", trigger=raw)
    assert result["status"] == "ok", result
    added = dss.state["scenarios"]["SC2"]["triggers"][0]
    assert added["type"] == "ds_modified"
    assert "id" not in added


def test_add_unsupported_trigger(dss):
    result = scenarios.add_scenario_trigger("PROJ", "SC1", "dataset")
    assert result["error_type"] == "invalid_argument"


def test_remove_trigger(dss):
    result = scenarios.remove_scenario_trigger("PROJ", "SC1", 0)
    assert result["status"] == "ok", result
    assert result["remaining_triggers"] == 1
    assert dss.state["scenarios"]["SC1"]["triggers"][0]["id"] == "t2"
    assert scenarios.remove_scenario_trigger("PROJ", "SC1", 5)["status"] == "error"


def test_update_scenario(dss):
    result = scenarios.update_scenario(
        "PROJ", "SC1", active=False, description="d", step_script="print(2)", step_index=1
    )
    assert result["status"] == "ok", result
    saved = dss.state["scenarios"]["SC1"]
    assert saved["active"] is False
    assert saved["params"]["steps"][1]["params"]["script"] == "print(2)"


def test_update_python_scenario_script(dss):
    result = scenarios.update_scenario("PROJ", "SC2", script="print('new')")
    assert result["status"] == "ok", result
    assert dss.state["scenario_scripts"]["SC2"] == "print('new')"


def test_update_step_script_on_wrong_step(dss):
    result = scenarios.update_scenario("PROJ", "SC1", step_script="x", step_index=0)
    assert result["error_type"] == "invalid_argument"


def test_create_and_delete_scenario(dss):
    created = scenarios.create_scenario("PROJ", "New one", "step_based")
    assert created["status"] == "ok", created
    deleted = scenarios.delete_scenario("PROJ", created["scenario_id"])
    assert deleted["status"] == "ok", deleted
    assert deleted["deleted_scenario"]["name"] == "New one"


def test_get_scenario_logs(dss):
    result = advanced_scenarios.get_scenario_logs("PROJ", "SC1", max_chars=20)
    assert result["status"] == "ok", result
    assert result["run_info"]["run_id"] == "run-2"
    assert result["first_error"] == {"message": "Table missing"}
    assert result["steps"][0]["job_ids"] == ["JOB1"]
    assert result["scenario_log"].endswith("END OF SCENARIO LOG")
    assert "truncated" in result["scenario_log"]
    assert result["job_logs"][0]["job_id"] == "JOB1"


def test_get_scenario_logs_specific_run(dss):
    result = advanced_scenarios.get_scenario_logs("PROJ", "SC1", run_id="run-1")
    assert result["status"] == "ok", result
    assert result["run_info"]["outcome"] == "SUCCESS"


def test_get_scenario_steps(dss):
    result = advanced_scenarios.get_scenario_steps("PROJ", "SC1")
    assert result["status"] == "ok", result
    assert result["steps"][0]["items"][0]["item_id"] == "out"
    assert result["steps"][1]["code"] == "print(1)"
    python = advanced_scenarios.get_scenario_steps("PROJ", "SC2")
    assert python["script"] == "print('scenario')"


def test_clone_scenario_is_inactive_by_default(dss):
    result = advanced_scenarios.clone_scenario(
        "PROJ", "SC1", "Copy", {"step_modifications": {"1": {"code": "print(3)"}}}
    )
    assert result["status"] == "ok", result
    clone = dss.state["scenarios"][result["new_scenario_id"]]
    assert clone["active"] is False
    assert len(clone["triggers"]) == 2
    assert clone["params"]["steps"][1]["params"]["script"] == "print(3)"
    # Source untouched
    assert dss.state["scenarios"]["SC1"]["params"]["steps"][1]["params"]["script"] == "print(1)"


def test_clone_python_scenario_copies_script(dss):
    result = advanced_scenarios.clone_scenario("PROJ", "SC2", "Py copy")
    assert result["status"] == "ok", result
    assert dss.state["scenario_scripts"][result["new_scenario_id"]] == "print('scenario')"
