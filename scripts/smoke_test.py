#!/usr/bin/env python3
"""
Smoke test des outils MCP contre une vraie instance DSS.

N'appelle QUE des outils en lecture : aucun objet DSS n'est créé, modifié,
construit ou supprimé. Chaque outil est appelé sur un projet réel et le
script affiche OK / ERREUR avec le message renvoyé.

Usage:
    python scripts/smoke_test.py [PROJECT_KEY] [--json]

Sans PROJECT_KEY, la clé est lue dans DSS_PROJECT_KEY (.env). Le script
choisit lui-même un dataset, une recette et un scénario du projet.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Allow running the script directly without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataiku_mcp.client import get_dss_version, list_projects  # noqa: E402
from dataiku_mcp.tools import (  # noqa: E402
    advanced_scenarios,
    classification_dataset,
    code_development,
    datasets,
    environment_config,
    monitoring_debug,
    productivity,
    project_exploration,
    recipes,
    scenarios,
)


def _first(items, key):
    return items[0][key] if items else None


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("project_key", nargs="?", default=os.getenv("DSS_PROJECT_KEY"))
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if not args.project_key:
        print("Donner la clé projet en argument ou dans DSS_PROJECT_KEY", file=sys.stderr)
        return 2

    pk = args.project_key
    print(f"DSS {get_dss_version()} - {len(list_projects())} projets visibles - projet {pk}")

    ds = datasets.list_datasets(pk)
    rc = recipes.list_recipes(pk)
    sc = scenarios.list_scenarios(pk)
    dataset = _first(ds.get("datasets", []), "name")
    recipe = _first(rc.get("recipes", []), "name")
    code_recipe = next(
        (r["name"] for r in rc.get("recipes", [])
         if r["type"] in ("python", "pyspark", "sql_script", "sql_query", "r")),
        None,
    )
    scenario = _first(sc.get("scenarios", []), "id")
    jobs = monitoring_debug.get_recent_runs(pk, limit=20).get("runs", [])
    job_id = next((r["id"] for r in jobs if r["kind"] == "job"), None)

    checks = [
        ("list_datasets", lambda: ds),
        ("list_recipes", lambda: rc),
        ("list_scenarios", lambda: sc),
        ("get_project_flow", lambda: project_exploration.get_project_flow(pk)),
        ("classer_datasets_flow", lambda: {"status": "ok", **classification_dataset.classer_datasets_flow(pk)}),
        ("search_project_objects", lambda: project_exploration.search_project_objects(pk, "a")),
        ("get_project_variables", lambda: environment_config.get_project_variables(pk)),
        ("get_code_environments", lambda: environment_config.get_code_environments(pk)),
        ("get_connections", lambda: environment_config.get_connections(pk)),
        ("get_recent_runs", lambda: monitoring_debug.get_recent_runs(pk)),
        ("export_project_config", lambda: productivity.export_project_config(pk)),
        ("duplicate_project_structure (dry run)", lambda: productivity.duplicate_project_structure(pk, pk + "_COPY")),
    ]
    if dataset:
        checks += [
            ("get_dataset_info", lambda: datasets.get_dataset_info(pk, dataset)),
            ("inspect_dataset_schema", lambda: datasets.inspect_dataset_schema(pk, dataset)),
            ("check_dataset_metrics", lambda: datasets.check_dataset_metrics(pk, dataset)),
            ("get_dataset_sample", lambda: project_exploration.get_dataset_sample(pk, dataset, rows=5)),
        ]
    if recipe:
        checks += [
            ("get_recipe_info", lambda: recipes.get_recipe_info(pk, recipe)),
            ("get_recipe_code", lambda: code_development.get_recipe_code(pk, recipe)),
            ("get_generated_sql", lambda: code_development.get_generated_sql(pk, recipe)),
        ]
    if code_recipe:
        checks += [
            ("validate_recipe_syntax", lambda: code_development.validate_recipe_syntax(pk, code_recipe)),
            ("dry_run_recipe", lambda: code_development.test_recipe_dry_run(pk, code_recipe, 5)),
        ]
    if scenario:
        checks += [
            ("get_scenario_info", lambda: scenarios.get_scenario_info(pk, scenario)),
            ("get_scenario_run_history", lambda: scenarios.get_scenario_run_history(pk, scenario)),
            ("get_scenario_steps", lambda: advanced_scenarios.get_scenario_steps(pk, scenario)),
            ("get_scenario_logs", lambda: advanced_scenarios.get_scenario_logs(pk, scenario)),
        ]
    if job_id:
        checks.append(("get_job_details", lambda: monitoring_debug.get_job_details(pk, job_id)))

    report = []
    for name, check in checks:
        start = time.monotonic()
        try:
            result = check()
            status = result.get("status")
            message = result.get("message", "")
            warnings = result.get("warnings", [])
        except Exception as e:  # a tool must never raise: report it
            status, message, warnings = "exception", repr(e), []
        report.append({
            "tool": name,
            "status": status,
            "seconds": round(time.monotonic() - start, 2),
            "message": message if status != "ok" else "",
            "warnings": warnings,
        })

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for r in report:
            mark = "OK    " if r["status"] == "ok" else "ERREUR"
            print(f"{mark} {r['tool']:<40} {r['seconds']:>6}s {r['message']}")
            for w in r["warnings"][:3]:
                print(f"       avertissement : {w}")
        print(f"\nObjets testés : dataset={dataset} recette={recipe} "
              f"recette_code={code_recipe} scénario={scenario} job={job_id}")

    failures = [r for r in report if r["status"] != "ok"]
    if not args.json:
        print(f"\n{len(report) - len(failures)}/{len(report)} outils OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
