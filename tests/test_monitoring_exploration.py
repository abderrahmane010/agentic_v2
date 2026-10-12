from dataiku_mcp.tools import (
    classification_dataset,
    environment_config,
    monitoring_debug,
    project_exploration,
)


# Monitoring -------------------------------------------------------------
def test_get_recent_runs(dss):
    result = monitoring_debug.get_recent_runs("PROJ")
    assert result["status"] == "ok", result
    kinds = {r["kind"] for r in result["runs"]}
    assert kinds == {"scenario", "job"}
    assert result["summary"]["failed_runs"] == 1
    failed = monitoring_debug.get_recent_runs("PROJ", status_filter="failed")
    assert [r["id"] for r in failed["runs"]] == ["SC1"]


def test_get_job_details(dss):
    result = monitoring_debug.get_job_details("PROJ", "JOB1")
    assert result["status"] == "ok", result
    assert result["job"]["state"] == "DONE"
    assert result["activities"][0]["recipe"] == "compute_mid"
    assert "ERROR boom" in result["log"]


def test_cancel_running_jobs(dss):
    result = monitoring_debug.cancel_running_jobs("PROJ", ["JOB_RUNNING", "JOB1"])
    assert [j["job_id"] for j in result["cancelled_jobs"]] == ["JOB_RUNNING"]
    assert result["failed_cancellations"][0]["job_id"] == "JOB1"
    assert dss.state["jobs"]["JOB_RUNNING"]["baseStatus"]["state"] == "ABORTED"


# Exploration ------------------------------------------------------------
def test_get_project_flow_has_edges(dss):
    result = project_exploration.get_project_flow("PROJ")
    assert result["status"] == "ok", result
    edges = {(e["from"], e["to"]) for e in result["flow"]["edges"]}
    assert ("dataset:raw_in", "recette:compute_mid") in edges
    assert ("recette:compute_mid", "dataset:mid") in edges
    assert ("recette:join_out", "dataset:out") in edges
    assert "dataset:raw_in" in result["root_nodes"]
    assert "dataset:out" in result["leaf_nodes"]
    assert result["flow_stats"]["edges"] == 5


def test_classification(dss):
    result = classification_dataset.classer_datasets_flow("PROJ")
    assert [d["nom"] for d in result["tables_sources"]] == ["OTHER.ref_table", "raw_in"]
    assert [d["nom"] for d in result["tables_intermediaires"]] == ["mid"]
    assert [d["nom"] for d in result["tables_finales"]] == ["out"]


def test_get_dataset_sample(dss):
    result = project_exploration.get_dataset_sample("PROJ", "raw_in", rows=2)
    assert result["status"] == "ok", result
    assert result["sample_data"] == [{"id": 1, "label": "a"}, {"id": 2, "label": "b"}]
    stats = {c["name"]: c for c in result["column_stats"]}
    assert stats["id"]["max"] == 2


def test_get_dataset_sample_columns(dss):
    result = project_exploration.get_dataset_sample("PROJ", "raw_in", columns=["label"])
    assert result["sample_data"][0] == {"label": "a"}
    bad = project_exploration.get_dataset_sample("PROJ", "raw_in", columns=["nope"])
    assert bad["error_type"] == "invalid_argument"


def test_search_project_objects(dss):
    result = project_exploration.search_project_objects("PROJ", "out")
    assert result["status"] == "ok", result
    assert [d["name"] for d in result["results"]["datasets"]] == ["out"]
    assert [r["name"] for r in result["results"]["recipes"]] == ["join_out"]


# Environment ------------------------------------------------------------
def test_get_connections_lists_and_hides_secrets(dss):
    result = environment_config.get_connections("PROJ")
    assert result["status"] == "ok", result
    pg = next(c for c in result["connections"] if c["name"] == "pg")
    assert pg["type"] == "PostgreSQL"
    assert pg["parameters"] == {"host": "db.local", "port": 5432}
    assert result["connection_types"]["Databricks"] == ["dbx"]
    usage = result["project_connection_usage"]
    assert usage["pg"] == {"datasets": ["raw_in"], "recipes": ["compute_mid"]}


def test_get_project_variables_masks_secrets(dss):
    result = environment_config.get_project_variables("PROJ")
    assert result["status"] == "ok", result
    assert result["variables"]["standard"] == {"env": "prod", "db_password": "***HIDDEN***"}
    assert result["variables"]["local"]["api_token"] == "***HIDDEN***"
    assert result["variables"]["local"]["threshold"] == 3


def test_get_code_environments(dss):
    result = environment_config.get_code_environments("PROJ")
    assert result["status"] == "ok", result
    assert result["environments"][0]["name"] == "py311"
    assert result["project_code_envs"]["python"]["mode"] == "INHERIT"
