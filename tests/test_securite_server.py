import asyncio
import json

from dataiku_mcp import server


def call(tool, **arguments):
    """Appelle un outil via FastMCP, comme le ferait un client MCP."""
    _, structured = asyncio.run(server.mcp.call_tool(tool, arguments))
    return structured.get("result", structured)


def test_all_expected_tools_are_exposed():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    for expected in (
        "list_dss_projects",
        "list_datasets",
        "list_recipes",
        "list_scenarios",
        "get_dataset_info",
        "get_recipe_info",
        "get_scenario_info",
        "get_scenario_run_history",
        "clear_dataset",
    ):
        assert expected in names


def test_list_projects_respects_allowlist(dss, monkeypatch):
    monkeypatch.setenv("DSS_ALLOWED_PROJECTS", "PROJ")
    assert call("list_dss_projects")["projects"] == ["PROJ"]


def test_forbidden_project(dss, monkeypatch):
    monkeypatch.setenv("DSS_ALLOWED_PROJECTS", "OTHER")
    result = call("list_datasets", project_key="PROJ")
    assert result["status"] == "error"
    assert result["error_type"] == "forbidden"
    assert dss.calls == []


def test_read_only_blocks_writes(dss, monkeypatch):
    monkeypatch.setenv("DSS_READ_ONLY", "true")
    result = call("delete_dataset", project_key="PROJ", dataset_name="out")
    assert result["error_type"] == "read_only"
    assert "out" in dss.state["datasets"]
    # Reading still works
    assert call("list_datasets", project_key="PROJ")["status"] == "ok"


def test_tool_call_through_mcp(dss):
    result = call("run_recipe", project_key="PROJ", recipe_name="compute_mid", wait=False)
    assert result["status"] == "ok", result


def test_classer_datasets_flow_tool(dss):
    result = call("classer_datasets_flow", project_key="PROJ")
    assert result["status"] == "ok"
    assert result["statistiques"]["nb_tables_finales"] == 1


def test_project_resource(dss):
    contents = asyncio.run(server.mcp.read_resource("dss://project/PROJ"))
    assert json.loads(contents[0].content)["name"] == "My project"
