from dataiku_mcp.tools import datasets


def test_list_datasets(dss):
    result = datasets.list_datasets("PROJ")
    assert result["status"] == "ok"
    by_name = {d["name"]: d for d in result["datasets"]}
    assert by_name["raw_in"]["connection"] == "pg"
    assert by_name["mid"]["partitioned"] is True
    assert datasets.list_datasets("PROJ", "PostgreSQL")["total_count"] == 1


def test_get_dataset_info(dss):
    result = datasets.get_dataset_info("PROJ", "mid")
    assert result["status"] == "ok", result
    info = result["dataset_info"]
    assert info["type"] == "Filesystem"
    assert info["path"] == "/mid"
    assert info["partitioning"] == [{"name": "day", "type": "time"}]
    assert info["last_build"]["successful"] is True


def test_inspect_schema(dss):
    result = datasets.inspect_dataset_schema("PROJ", "raw_in")
    assert result["status"] == "ok"
    assert [c["name"] for c in result["schema"]["columns"]] == ["id", "label"]


def test_check_metrics(dss):
    result = datasets.check_dataset_metrics("PROJ", "raw_in")
    assert result["status"] == "ok", result
    assert result["metrics"]["records:COUNT_RECORDS"]["value"] == "3"


def test_build_dataset_success(dss):
    result = datasets.build_dataset("PROJ", "mid", mode="RECURSIVE_BUILD")
    assert result["status"] == "ok", result
    assert result["job"]["state"] == "DONE"


def test_build_dataset_failure_keeps_job_state(dss):
    dss.state["next_job_state"] = "FAILED"
    result = datasets.build_dataset("PROJ", "mid")
    assert result["status"] == "error"
    assert result["error_type"] == "job_failed"
    assert result["job"]["state"] == "FAILED"


def test_build_dataset_no_wait(dss):
    result = datasets.build_dataset("PROJ", "mid", wait=False)
    assert result["status"] == "ok"
    assert result["job"]["job_id"].startswith("JOB_")


def test_update_dataset_metadata_and_location(dss):
    result = datasets.update_dataset(
        "PROJ", "raw_in", description="raw table", tags=["a"], table="raw_v2"
    )
    assert result["status"] == "ok", result
    saved = dss.state["datasets"]["raw_in"]
    assert saved["description"] == "raw table"
    assert saved["tags"] == ["a"]
    assert saved["params"]["table"] == "raw_v2"
    assert saved["params"]["connection"] == "pg"


def test_update_dataset_format_refused_on_sql(dss):
    result = datasets.update_dataset("PROJ", "raw_in", format_type="csv")
    assert result["error_type"] == "invalid_argument"


def test_delete_dataset(dss):
    result = datasets.delete_dataset("PROJ", "out")
    assert result["status"] == "ok", result
    assert result["deleted_dataset"]["type"] == "dbx_table"


def test_clear_dataset(dss):
    assert datasets.clear_dataset("PROJ", "mid")["status"] == "ok"


def test_create_sql_dataset_requires_sql_type(dss):
    result = datasets.create_dataset(
        "PROJ", "new_sql", "sql", {"connection": "pg", "table": "t"}
    )
    assert result["error_type"] == "invalid_argument"


def test_create_sql_dataset(dss):
    result = datasets.create_dataset(
        "PROJ", "new_sql", "sql",
        {"connection": "pg", "table": "t", "sql_type": "PostgreSQL"},
    )
    assert result["status"] == "ok", result
    assert dss.state["datasets"]["new_sql"]["type"] == "PostgreSQL"


def test_create_managed_dataset(dss):
    result = datasets.create_dataset("PROJ", "new_managed", "managed")
    assert result["status"] == "ok", result
