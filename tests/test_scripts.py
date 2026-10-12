import sys

from scripts import list_databricks_scenario_projects, smoke_test
from dataiku_mcp.client import get_client


def test_smoke_test_passes_and_writes_nothing(dss, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["smoke_test.py", "PROJ"])
    assert smoke_test.main() == 0, capsys.readouterr().out
    assert dss.writes() == []


def test_list_databricks_scenario_projects(dss):
    results = list_databricks_scenario_projects.find_projects_with_databricks_scenario_trigger(
        get_client()
    )
    assert results == [{
        "project_key": "PROJ",
        "databricks_datasets": ["out"],
        "scenarios": [{
            "scenario_id": "SC1",
            "scenario_name": "Daily build",
            "dataset": "out",
            "trigger_type": "ds_modified",
        }],
    }]
