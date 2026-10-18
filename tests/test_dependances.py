"""Dépendances inter-projets : liens déclarés, stockage, code, interfaces."""

import pytest

from dataiku_mcp.tools import dependances_projets as dp
from dataiku_mcp.tools import liens_caches


def role(*refs):
    return {"main": {"items": [{"ref": r} for r in refs]}}


def ds(name, connection, **params):
    return {"name": name, "type": "x", "params": {"connection": connection, **params}}


def recette(name, entrees, sorties, type_="sync", code=""):
    return {"name": name, "type": type_, "inputs": role(*entrees),
            "outputs": role(*sorties), "code": code}


PROJETS = {
    "SRC": {
        "datasets": [
            ds("ventes", "pg", schema="dw", table="ventes"),
            ds("ref", "pg", schema="dw", table="ref"),
            ds("partage", "hdfs", path="/shared/t"),
            ds("exports", "hdfs", path="/${projectKey}/exports"),
        ],
        "recettes": [
            recette("build_ventes", ["ref"], ["ventes", "partage", "exports"]),
        ],
    },
    "AEL": {
        "datasets": [
            ds("out_ael", "pg", schema="ael", table="out"),
            ds("ref_ael", "pg", schema="dw", table="ref"),
        ],
        "recettes": [
            recette("r1", ["SRC.ventes", "ref_ael"], ["out_ael"], "python",
                    'spark.read.parquet("hdfs:///data/dss/SRC/exports/day=1")'),
        ],
    },
    "RPT": {
        "datasets": [
            ds("ventes_copy", "pg", schema="DW", table="ventes"),
            ds("tmp", "hdfs", path="/shared/t"),
        ],
        "recettes": [recette("agg", ["ventes_copy"], ["tmp"])],
        "scenarios": [{
            "id": "S1",
            "triggers": [{"type": "ds_modified", "params": {"datasets": [
                {"projectKey": "AEL", "datasetName": "out_ael"}]}}],
        }],
    },
    "PY": {
        "datasets": [ds("res", "pg", schema="py", table="res")],
        "recettes": [recette(
            "calc", [], ["res"], "python",
            'a = dataiku.Dataset("AEL.out_ael")\nq = "SELECT * FROM dw.ventes v"',
        )],
    },
}


class Objet:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


class Projet:
    def __init__(self, cle):
        self.cle = cle
        self.d = PROJETS[cle]

    def list_datasets(self):
        return self.d["datasets"]

    def list_recipes(self):
        return [{k: v for k, v in r.items() if k != "code"} for r in self.d["recettes"]]

    def get_recipe(self, nom):
        r = next(r for r in self.d["recettes"] if r["name"] == nom)
        settings = Objet(
            str_payload=r["code"],
            get_flat_input_refs=lambda: [i["ref"] for i in r["inputs"]["main"]["items"]],
            get_flat_output_refs=lambda: [i["ref"] for i in r["outputs"]["main"]["items"]],
        )
        return Objet(get_settings=lambda: settings)

    def list_scenarios(self):
        return [{"id": s["id"]} for s in self.d.get("scenarios", [])]

    def get_scenario(self, scenario_id):
        raw = {"projectKey": self.cle,
               **next(s for s in self.d["scenarios"] if s["id"] == scenario_id)}
        return Objet(get_settings=lambda: Objet(get_raw=lambda: raw))

    def get_settings(self):
        return Objet(get_raw=lambda: {})


@pytest.fixture
def instance(monkeypatch):
    monkeypatch.setattr(dp, "list_projects", lambda: list(PROJETS))
    monkeypatch.setattr(dp, "get_project", Projet)
    monkeypatch.setenv("DSS_ALLOWED_PROJECTS", "")


def liens(resultat):
    return {(l["fournisseur"], l["consommateur"]): l for l in resultat["liens"]}


def test_liens_et_vagues(instance):
    r = dp.dependances_inter_projets(details=True)
    tous = liens(r)
    assert "recette" in tous[("SRC", "AEL")]["via"]
    assert "stockage" in tous[("SRC", "RPT")]["via"]
    assert set(tous[("SRC", "PY")]["via"]) == {"code"}
    assert set(tous[("AEL", "PY")]["via"]) == {"code"}
    assert "code" in tous[("SRC", "AEL")]["via"]  # chemin HDFS dans le code
    vagues = {v["vague"]: v["projets"] for v in r["vagues"]}
    assert vagues == {1: ["SRC"], 2: ["AEL"], 3: ["PY", "RPT"]}


def test_trigger_dataset_nomme(instance):
    """Point 4 : l'objet d'un trigger ds_modified n'est plus '?'."""
    r = dp.dependances_inter_projets(details=True)
    assert liens(r)[("AEL", "RPT")]["objets"] == ["out_ael"]
    assert liens(r)[("AEL", "RPT")]["usages"]["out_ael"] == ["scenario:S1"]


def test_tables_interface(instance):
    r = dp.dependances_inter_projets()
    interfaces = {(t["projet"], t["dataset"]): t for t in r["tables_interface"]}
    ventes = interfaces[("SRC", "ventes")]
    assert ventes["statut_local"] == "finale"
    assert ventes["emplacement"] == "table:pg|dw.ventes"
    assert [c["projet"] for c in ventes["consommateurs"]] == ["AEL", "PY", "RPT"]
    assert interfaces[("AEL", "out_ael")]["statut_local"] == "finale"
    assert r["statistiques"]["nb_tables_interface"] == len(interfaces)


def test_emplacements_partages(instance):
    constats = dp.dependances_inter_projets()["emplacements_partages"]
    multiples = constats["ecritures_multiples"]
    assert [m["emplacement"] for m in multiples] == ["chemin:hdfs|/shared/t"]
    assert multiples[0]["ecrivains"] == ["RPT.tmp", "SRC.partage"]
    externes = constats["sources_externes_partagees"]
    assert [e["emplacement"] for e in externes] == ["table:pg|dw.ref"]


def test_vue_projet(instance):
    r = dp.dependances_inter_projets("PY")
    assert r["vague"] == 3
    assert r["prerequis_migration"] == ["AEL", "SRC"]
    assert {t["dataset"] for t in r["tables_interface_consommees"]} == {"ventes", "out_ael"}
    src = dp.dependances_inter_projets("SRC")
    assert {t["dataset"] for t in src["tables_interface_produites"]} == {"ventes", "exports"}


def test_sans_analyse_du_code(instance):
    r = dp.dependances_inter_projets(analyser_code=False)
    assert ("SRC", "PY") not in liens(r)
    assert ("AEL", "PY") not in liens(r)


@pytest.mark.parametrize("params, attendu", [
    ({"connection": "pg", "schema": "A", "table": "T"}, "table:pg|a.t"),
    ({"connection": "hive", "database": "db", "table": "t"}, "table:hive|db.t"),
    ({"connection": "h", "path": "//${projectKey}//x/"}, "chemin:h|/p/x"),
    ({"connection": "pg", "table": "${autre}_t"}, None),
    ({"path": "/x"}, None),
])
def test_emplacement(params, attendu):
    assert liens_caches.emplacement("P", {"params": params}) == attendu


def test_chat_interfaces_et_rapport(instance, capsys, monkeypatch, tmp_path):
    import asyncio

    from scripts import chat_llm
    from tests.test_chat_llm import SessionEnMemoire

    monkeypatch.setattr(chat_llm, "RACINE", tmp_path)
    session = SessionEnMemoire()

    asyncio.run(chat_llm.COMMANDES["/interfaces"](session, "/interfaces"))
    sortie = capsys.readouterr().out
    assert "SRC.ventes (finale) → AEL [recette], PY [code], RPT [stockage]" in sortie
    assert "AEL.out_ael (finale) → PY [code], RPT [scenario]" in sortie
    assert "chemin:hdfs|/shared/t : RPT.tmp, SRC.partage" in sortie

    asyncio.run(chat_llm.COMMANDES["/interfaces"](session, "/interfaces PY"))
    assert "Tables d'autres projets utilisées par PY (2)" in capsys.readouterr().out

    asyncio.run(chat_llm.COMMANDES["/dependances"](session, "/dependances"))
    assert "tables d'interface" in capsys.readouterr().out
    rapport = next((tmp_path / "rapports").glob("dependances_inter_projets_*.md"))
    contenu = rapport.read_text(encoding="utf-8")
    assert "## Tables d'interface" in contenu
    assert "| SRC | ventes | finale | table:pg|dw.ventes |" in contenu
