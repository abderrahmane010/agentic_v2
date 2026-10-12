"""
Faux serveur DSS pour les tests.

Les tests utilisent un vrai ``dataikuapi.DSSClient`` dont seule la couche
HTTP (``_perform_http``) est remplacée par ``FakeDSS``. Toute méthode
inexistante de dataikuapi lève donc une AttributeError dans les tests, et
toute route non simulée lève une erreur explicite.
"""

import copy
import io
import json
import re
from typing import Any, Callable

PROJECT = "PROJ"


def _role(*refs: str) -> dict[str, Any]:
    return {"main": {"items": [{"ref": r} for r in refs]}}


def initial_state() -> dict[str, Any]:
    """Projet PROJ : raw_in -> compute_mid (python) -> mid -> join_out -> out."""
    return {
        "projects": [PROJECT, "OTHER"],
        "connections": {
            "pg": {
                "name": "pg",
                "type": "PostgreSQL",
                "allowWrite": True,
                "params": {"host": "db.local", "port": 5432, "password": "s3cret"},
            },
            "dbx": {"name": "dbx", "type": "Databricks", "params": {"host": "x"}},
        },
        "datasets": {
            "raw_in": {
                "name": "raw_in",
                "projectKey": PROJECT,
                "type": "PostgreSQL",
                "managed": False,
                "params": {"connection": "pg", "table": "raw", "schema": "public"},
                "schema": {
                    "columns": [
                        {"name": "id", "type": "bigint"},
                        {"name": "label", "type": "string"},
                    ]
                },
                "partitioning": {"dimensions": []},
                "tags": ["source"],
            },
            "mid": {
                "name": "mid",
                "projectKey": PROJECT,
                "type": "Filesystem",
                "managed": True,
                "formatType": "csv",
                "params": {"connection": "filesystem_managed", "path": "/mid"},
                "schema": {"columns": [{"name": "id", "type": "bigint"}]},
                "partitioning": {
                    "dimensions": [{"name": "day", "type": "time"}]
                },
                "tags": [],
            },
            "out": {
                "name": "out",
                "projectKey": PROJECT,
                "type": "dbx_table",
                "managed": True,
                "params": {"connection": "dbx"},
                "schema": {"columns": [{"name": "id", "type": "bigint"}]},
                "tags": [],
            },
        },
        "recipes": {
            "compute_mid": {
                "recipe": {
                    "name": "compute_mid",
                    "projectKey": PROJECT,
                    "type": "python",
                    "params": {"engineType": "DSS"},
                    "inputs": _role("raw_in"),
                    "outputs": _role("mid"),
                    "tags": [],
                },
                "payload": "import dataiku\nprint('hello')\n",
            },
            "join_out": {
                "recipe": {
                    "name": "join_out",
                    "projectKey": PROJECT,
                    "type": "join",
                    "params": {},
                    "inputs": _role("mid", "OTHER.ref_table"),
                    "outputs": _role("out"),
                    "tags": ["join"],
                },
                "payload": json.dumps({"joins": []}),
            },
        },
        "scenarios": {
            "SC1": {
                "id": "SC1",
                "projectKey": PROJECT,
                "name": "Daily build",
                "type": "step_based",
                "active": True,
                "tags": [],
                "triggers": [
                    {
                        "id": "t1",
                        "type": "temporal",
                        "name": "nightly",
                        "active": True,
                        "params": {"frequency": "Daily", "hour": 2, "minute": 0},
                    },
                    {
                        "id": "t2",
                        "type": "ds_modified",
                        "name": "on out",
                        "active": True,
                        "params": {
                            "datasets": [
                                {"projectKey": PROJECT, "datasetName": "out"}
                            ]
                        },
                    },
                ],
                "reporters": [],
                "params": {
                    "steps": [
                        {
                            "id": "s1",
                            "name": "build",
                            "type": "build_flowitem",
                            "params": {
                                "builds": [
                                    {"type": "DATASET", "itemId": "out"}
                                ]
                            },
                        },
                        {
                            "id": "s2",
                            "name": "py",
                            "type": "custom_python",
                            "params": {"script": "print(1)"},
                        },
                    ]
                },
            },
            "SC2": {
                "id": "SC2",
                "projectKey": PROJECT,
                "name": "Python scenario",
                "type": "custom_python",
                "active": False,
                "tags": [],
                "triggers": [],
                "reporters": [],
                "params": {},
            },
        },
        "scenario_scripts": {"SC2": "print('scenario')"},
        "scenario_runs": {
            "SC1": [
                {
                    "runId": "run-2",
                    "scenario": {"projectKey": PROJECT, "id": "SC1"},
                    "start": 1_700_000_100_000,
                    "end": 1_700_000_160_000,
                    "result": {"outcome": "FAILED"},
                    "trigger": {"trigger": {"type": "temporal", "name": "nightly"}},
                },
                {
                    "runId": "run-1",
                    "scenario": {"projectKey": PROJECT, "id": "SC1"},
                    "start": 1_700_000_000_000,
                    "end": 1_700_000_030_000,
                    "result": {"outcome": "SUCCESS"},
                    "trigger": {"trigger": {"type": "manual", "name": "manual"}},
                },
            ],
            "SC2": [],
        },
        "jobs": {
            "JOB1": {
                "baseStatus": {
                    "state": "DONE",
                    "def": {"id": "JOB1", "type": "NON_RECURSIVE_FORCED_BUILD"},
                    "jobStartTime": 1_700_000_000_000,
                    "jobEndTime": 1_700_000_010_000,
                },
                "activities": {"a1": {"state": "DONE", "recipeName": "compute_mid"}},
            },
            "JOB_RUNNING": {
                "baseStatus": {
                    "state": "RUNNING",
                    "def": {"id": "JOB_RUNNING", "type": "RECURSIVE_BUILD"},
                }
            },
        },
        # State given to the next job started (DONE or FAILED).
        "next_job_state": "DONE",
        "variables": {
            "standard": {"env": "prod", "db_password": "x"},
            "local": {"api_token": "y", "threshold": 3},
        },
        "rows": {"raw_in": [["1", "a"], ["2", "b"], ["3", "a"]]},
    }


class FakeResponse:
    def __init__(self, data: Any = None, text: str | None = None):
        self._data = data
        self.text = text if text is not None else json.dumps(data)
        self.raw = io.BytesIO(self.text.encode("utf-8"))
        self.status_code = 200

    def json(self) -> Any:
        return self._data

    def close(self) -> None:
        pass


class FakeDSS:
    """Routeur HTTP en mémoire imitant l'API publique de DSS."""

    def __init__(self) -> None:
        self.state = initial_state()
        self.calls: list[tuple[str, str]] = []
        self.routes: list[tuple[str, re.Pattern[str], Callable[..., Any]]] = []
        self._register()

    # ------------------------------------------------------------------
    def __call__(self, method, path, params=None, body=None, stream=False,
                 files=None, raw_body=None, headers=None):
        self.calls.append((method, path))
        data = json.loads(body) if isinstance(body, str) else body
        for route_method, pattern, handler in self.routes:
            match = pattern.fullmatch(path)
            if route_method == method and match:
                result = handler(*match.groups(), params=params or {}, body=data)
                if isinstance(result, FakeResponse):
                    return result
                return FakeResponse(result)
        raise AssertionError(f"Route DSS non simulée : {method} {path}")

    def route(self, method: str, pattern: str):
        def decorator(handler):
            self.routes.append((method, re.compile(pattern), handler))
            return handler
        return decorator

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] in ("POST", "PUT", "DELETE")]

    # ------------------------------------------------------------------
    def _register(self) -> None:  # noqa: C901 - one handler per route
        st = self.state
        P = r"/projects/([^/]+)"

        def check(project: str) -> None:
            if project not in st["projects"]:
                raise AssertionError(f"Projet inconnu : {project}")

        @self.route("GET", r"/instance-info")
        def instance_info(params, body):
            return {"dssVersion": "14.0.0"}

        @self.route("GET", r"/projects/")
        def list_projects(params, body):
            return [{"projectKey": k} for k in st["projects"]]

        @self.route("GET", r"/admin/connections/")
        def list_connections(params, body):
            return copy.deepcopy(st["connections"])

        @self.route("GET", r"/admin/code-envs/")
        def list_code_envs(params, body):
            return [{"envLang": "PYTHON", "envName": "py311", "deploymentMode": "DESIGN_MANAGED"}]

        # Project ------------------------------------------------------
        @self.route("GET", P + r"/variables/")
        def variables(project, params, body):
            return copy.deepcopy(st["variables"])

        @self.route("GET", P + r"/metadata")
        def metadata(project, params, body):
            return {"label": "My project", "tags": ["t"], "customFields": {}}

        @self.route("GET", P + r"/settings")
        def project_settings(project, params, body):
            return {"settings": {"codeEnvs": {"python": {"mode": "INHERIT"}}}}

        @self.route("POST", P + r"/duplicate/")
        def duplicate(project, params, body):
            return {"sourceProjectKey": project, "targetProjectKey": body["targetProjectKey"]}

        @self.route("GET", P + r"/flow/graph/")
        def flow_graph(project, params, body):
            nodes = {}
            for name, r in st["recipes"].items():
                outs = [i["ref"] for role in r["recipe"]["outputs"].values() for i in role["items"]]
                nodes[name] = {"ref": name, "type": "RUNNABLE_RECIPE", "successors": outs, "predecessors": []}
                for o in outs:
                    nodes[o] = {"ref": o, "type": "COMPUTABLE_DATASET", "successors": [], "predecessors": [name]}
            return {"nodes": nodes}

        # Datasets -----------------------------------------------------
        @self.route("GET", P + r"/datasets/")
        def list_datasets(project, params, body):
            check(project)
            return copy.deepcopy(list(st["datasets"].values()))

        @self.route("POST", P + r"/datasets/")
        def create_dataset(project, params, body):
            st["datasets"][body["name"]] = {**body, "schema": {"columns": []}, "tags": []}
            return {}

        @self.route("POST", P + r"/datasets/managed")
        def create_managed(project, params, body):
            name = body["name"]
            st["datasets"][name] = {"name": name, "type": "Filesystem", "managed": True,
                                    "params": {"connection": body["creationSettings"]["connectionId"]},
                                    "schema": {"columns": []}, "tags": []}
            return {"name": name}

        @self.route("GET", P + r"/datasets/([^/]+)")
        def get_dataset(project, name, params, body):
            return copy.deepcopy(st["datasets"][name])

        @self.route("PUT", P + r"/datasets/([^/]+)")
        def put_dataset(project, name, params, body):
            st["datasets"][name] = body
            return {}

        @self.route("DELETE", P + r"/datasets/([^/]+)")
        def delete_dataset(project, name, params, body):
            del st["datasets"][name]
            return {}

        @self.route("GET", P + r"/datasets/([^/]+)/schema")
        def schema(project, name, params, body):
            return copy.deepcopy(st["datasets"][name]["schema"])

        @self.route("GET", P + r"/datasets/([^/]+)/info")
        def info(project, name, params, body):
            return {"lastBuild": {"buildStartTime": 1_700_000_000_000,
                                  "buildEndTime": 1_700_000_005_000, "buildSuccess": True}}

        @self.route("GET", P + r"/datasets/([^/]+)/metrics/last/(.+)")
        def metrics(project, name, partition, params, body):
            return {"metrics": [{
                "metric": {"id": "records:COUNT_RECORDS"},
                "lastValues": [{"partition": "NP", "value": "3", "time": 1_700_000_000_000}],
            }]}

        @self.route("DELETE", P + r"/datasets/([^/]+)/data")
        def clear(project, name, params, body):
            return {}

        @self.route("GET", P + r"/datasets/([^/]+)/data/")
        def data(project, name, params, body):
            rows = st["rows"].get(name, [])
            return FakeResponse(text="".join("\t".join(r) + "\n" for r in rows))

        @self.route("GET", P + r"/datasets/([^/]+)/finish-streaming/")
        def finish(project, name, params, body):
            return {}

        # Recipes ------------------------------------------------------
        @self.route("GET", P + r"/recipes/")
        def list_recipes(project, params, body):
            return [copy.deepcopy(r["recipe"]) for r in st["recipes"].values()]

        @self.route("POST", P + r"/recipes/")
        def create_recipe(project, params, body):
            proto = body["recipePrototype"]
            st["recipes"][proto["name"]] = {
                "recipe": {**proto, "params": {}, "tags": []},
                "payload": body.get("creationSettings", {}).get("script", ""),
            }
            return {"name": proto["name"]}

        @self.route("GET", P + r"/recipes/([^/]+)")
        def get_recipe(project, name, params, body):
            return copy.deepcopy(st["recipes"][name])

        @self.route("PUT", P + r"/recipes/([^/]+)")
        def put_recipe(project, name, params, body):
            st["recipes"][name] = body
            return {}

        @self.route("DELETE", P + r"/recipes/([^/]+)")
        def delete_recipe(project, name, params, body):
            del st["recipes"][name]
            return {}

        # Jobs ---------------------------------------------------------
        @self.route("GET", P + r"/jobs/")
        def list_jobs(project, params, body):
            return copy.deepcopy(list(st["jobs"].values()))

        @self.route("POST", P + r"/jobs/")
        def start_job(project, params, body):
            job_id = f"JOB_{len(st['jobs'])}"
            st["jobs"][job_id] = {"baseStatus": {
                "state": st["next_job_state"],
                "def": {"id": job_id, "type": body["type"]},
                "jobStartTime": 1_700_000_000_000,
                "jobEndTime": 1_700_000_001_000,
            }, "definition": body}
            return {"id": job_id}

        @self.route("GET", P + r"/jobs/([^/]+)/")
        def job_status(project, job_id, params, body):
            return copy.deepcopy(st["jobs"][job_id])

        @self.route("GET", P + r"/jobs/([^/]+)/log")
        def job_log(project, job_id, params, body):
            return FakeResponse(text=f"log of {job_id}\nERROR boom")

        @self.route("POST", P + r"/jobs/([^/]+)/abort")
        def abort(project, job_id, params, body):
            st["jobs"][job_id]["baseStatus"]["state"] = "ABORTED"
            return {}

        # Scenarios ----------------------------------------------------
        @self.route("GET", P + r"/scenarios/")
        def list_scenarios(project, params, body):
            return [
                {"id": s["id"], "name": s["name"], "type": s["type"], "active": s["active"]}
                for s in st["scenarios"].values()
            ]

        @self.route("POST", P + r"/scenarios/")
        def create_scenario(project, params, body):
            scenario_id = re.sub(r"\W", "", body["name"]).upper()
            st["scenarios"][scenario_id] = {
                "triggers": [], "reporters": [], "params": {}, "active": False,
                **copy.deepcopy(body), "id": scenario_id, "projectKey": project,
            }
            st["scenario_runs"][scenario_id] = []
            return {"id": scenario_id}

        @self.route("GET", P + r"/scenarios/([^/]+)")
        def get_scenario(project, scenario_id, params, body):
            return copy.deepcopy(st["scenarios"][scenario_id])

        @self.route("PUT", P + r"/scenarios/([^/]+)")
        def put_scenario(project, scenario_id, params, body):
            st["scenarios"][scenario_id] = body
            return {}

        @self.route("DELETE", P + r"/scenarios/([^/]+)")
        def delete_scenario(project, scenario_id, params, body):
            del st["scenarios"][scenario_id]
            return {}

        @self.route("GET", P + r"/scenarios/([^/]+)/payload")
        def get_payload(project, scenario_id, params, body):
            return {"script": st["scenario_scripts"].get(scenario_id, "")}

        @self.route("PUT", P + r"/scenarios/([^/]+)/payload")
        def put_payload(project, scenario_id, params, body):
            st["scenario_scripts"][scenario_id] = body["script"]
            return {}

        @self.route("GET", P + r"/scenarios/([^/]+)/light")
        def light(project, scenario_id, params, body):
            return {"running": False, "nextRun": 1_800_000_000_000}

        @self.route("GET", P + r"/scenarios/([^/]+)/get-last-runs")
        def last_runs(project, scenario_id, params, body):
            return copy.deepcopy(st["scenario_runs"][scenario_id][: int(params.get("limit", 10))])

        @self.route("GET", P + r"/scenarios/([^/]+)/([^/]+)/")
        def run_details(project, scenario_id, run_id, params, body):
            run = next(r for r in st["scenario_runs"][scenario_id] if r["runId"] == run_id)
            return {"scenarioRun": copy.deepcopy(run), "stepRuns": [
                {"step": {"name": "build", "type": "build_flowitem"},
                 "result": {"outcome": "FAILED", "thrown": {"message": "Table missing"}},
                 "additionalReportItems": [{"type": "JOB_EXECUTED", "jobId": "JOB1", "outcome": "FAILED"}]},
            ]}

        @self.route("GET", P + r"/scenarios/([^/]+)/([^/]+)/log")
        def run_log(project, scenario_id, run_id, params, body):
            return FakeResponse(text="x" * 50 + "END OF SCENARIO LOG")
