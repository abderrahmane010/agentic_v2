"""
Helpers partagés par les outils MCP.

Contrat de réponse commun à tous les outils :
- succès : {"status": "ok", ...}
- erreur : {"status": "error", "message": "...", "error_type": "..."}
"""

from datetime import datetime, timezone
from typing import Any

from dataikuapi.dss.job import DSSJobWaiter

# Types de recettes dont le contenu est du code (payload = script).
CODE_RECIPE_TYPES = {
    "python",
    "r",
    "sql_script",
    "sql_query",
    "pyspark",
    "sparkr",
    "spark_scala",
    "spark_sql_query",
    "shell",
    "cpython",
    "ksql",
    "streaming_spark_scala",
}

BUILD_MODES = (
    "RECURSIVE_BUILD",
    "NON_RECURSIVE_FORCED_BUILD",
    "RECURSIVE_FORCED_BUILD",
)

JOB_TERMINAL_STATES = ("DONE", "FAILED", "ABORTED")


def ok(**data: Any) -> dict[str, Any]:
    """Réponse de succès."""
    return {"status": "ok", **data}


def error(
    message: str, error_type: str = "dss_error", **data: Any
) -> dict[str, Any]:
    """Réponse d'erreur."""
    return {
        "status": "error",
        "error_type": error_type,
        "message": message,
        **data,
    }


def ms_to_iso(value: Any) -> str | None:
    """Convertit un timestamp DSS (millisecondes) en ISO 8601 UTC."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def iso(value: Any) -> str | None:
    """Sérialise une date (datetime ou timestamp ms) en ISO 8601."""
    if isinstance(value, datetime):
        return value.isoformat()
    return ms_to_iso(value)


def flat_refs(role_map: Any) -> list[str]:
    """Aplatit les entrées/sorties d'une recette.

    DSS les décrit par rôle : {"main": {"items": [{"ref": "ds"}, ...]}}.
    """
    refs: list[str] = []
    if not isinstance(role_map, dict):
        return refs
    for role in role_map.values():
        for item in (role or {}).get("items", []) or []:
            ref = item.get("ref")
            if ref:
                refs.append(ref)
    return refs


def wait_for_job(job: Any) -> None:
    """Attend la fin d'un job sans lever d'exception s'il échoue."""
    DSSJobWaiter(job).wait(no_fail=True)


def job_summary(job: Any) -> dict[str, Any]:
    """Résumé d'un job DSS (dataikuapi.dss.job.DSSJob)."""
    status = job.get_status() or {}
    base = status.get("baseStatus", {}) or {}
    definition = base.get("def", {}) or {}
    return {
        "job_id": job.id,
        "state": base.get("state"),
        "type": definition.get("type"),
        "initiator": definition.get("initiator"),
        "start_time": ms_to_iso(base.get("jobStartTime")),
        "end_time": ms_to_iso(base.get("jobEndTime")),
    }


def scenario_run_summary(run: Any) -> dict[str, Any]:
    """Résumé d'un run de scénario (dataikuapi DSSScenarioRun)."""
    raw = getattr(run, "run", {}) or {}
    result = raw.get("result", {}) or {}
    trigger = (raw.get("trigger", {}) or {}).get("trigger", {}) or {}
    end = raw.get("end", 0)
    return {
        "run_id": raw.get("runId"),
        "outcome": result.get("outcome"),
        "running": "result" not in raw,
        "start_time": ms_to_iso(raw.get("start")),
        "end_time": ms_to_iso(end),
        "duration_seconds": (
            round((end - raw["start"]) / 1000, 1)
            if end and raw.get("start")
            else None
        ),
        "trigger_type": trigger.get("type"),
        "trigger_name": trigger.get("name"),
    }


def trigger_datasets(trigger: dict[str, Any]) -> list[str]:
    """Datasets surveillés par un trigger "dataset modifié" (ds_modified).

    Les éléments de params.datasets peuvent être des chaînes ou des dicts
    {"projectKey", "datasetName"} selon la version de DSS.
    """
    params = trigger.get("params", {}) or {}
    names = []
    for item in params.get("datasets", []) or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("datasetName") or item.get("name")
            if name:
                project = item.get("projectKey")
                names.append(f"{project}.{name}" if project else name)
    if params.get("datasetName"):
        names.append(params["datasetName"])
    return names


def trigger_summary(trigger: dict[str, Any], index: int) -> dict[str, Any]:
    """Résumé lisible d'un trigger de scénario (dict brut DSS)."""
    params = trigger.get("params", {}) or {}
    summary = {
        "index": index,
        "id": trigger.get("id"),
        "type": trigger.get("type"),
        "name": trigger.get("name"),
        "active": trigger.get("active", False),
    }
    if trigger.get("type") == "temporal":
        summary["frequency"] = params.get("frequency")
        summary["repeat_every"] = params.get("repeatFrequency")
        summary["hour"] = params.get("hour")
        summary["minute"] = params.get("minute")
        summary["timezone"] = params.get("timezone")
    datasets = trigger_datasets(trigger)
    if datasets:
        summary["datasets"] = datasets
    return summary
