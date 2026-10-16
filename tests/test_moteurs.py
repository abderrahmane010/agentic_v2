"""Inventaire des moteurs d'exécution des recettes (lecture seule)."""

import asyncio

from dataiku_mcp.tools import moteurs


def par_recette(resultat):
    return {r["recette"]: r for r in resultat["recettes"]}


def test_moteurs_recette_visuelle(dss):
    r = moteurs.inventaire_moteurs("PROJ")
    assert r["status"] == "ok", r
    join = par_recette(r)["join_out"]
    assert join["moteur_selectionne"] == "DSS"
    assert join["moteur_configure"] == "AUTO (choix de DSS)"
    assert [m["moteur"] for m in join["moteurs_disponibles"]] == ["DSS", "SPARK"]
    assert join["moteurs_disponibles"][1]["avertissement"].startswith("Input dataset")
    assert join["moteurs_indisponibles"] == [{
        "moteur": "SQL", "libelle": "In-database", "niveau": "ERROR",
        "raison": "Inputs and outputs are not in the same database",
    }]


def test_recette_de_code(dss):
    code = par_recette(moteurs.inventaire_moteurs("PROJ"))["compute_mid"]
    assert code["moteur_selectionne"].startswith("PYTHON")
    assert code["recette_de_code"] is True


def test_bascule_vers_spark(dss):
    r = moteurs.inventaire_moteurs("PROJ", moteur_cible="spark")
    recettes = par_recette(r)
    assert recettes["join_out"]["bascule"]["possible"] is True
    assert "avertissement" in recettes["join_out"]["bascule"]["raison"]
    assert recettes["compute_mid"]["bascule"]["possible"] is False
    bascule = r["synthese"]["bascule_vers"]
    assert bascule["possibles"] == ["join_out"]
    assert [i["recette"] for i in bascule["impossibles"]] == ["compute_mid"]


def test_bascule_impossible_avec_raison(dss):
    join = moteurs.inventaire_moteurs("PROJ", "join_out", "SQL")["recettes"][0]
    assert join["bascule"] == {
        "cible": "SQL", "possible": False,
        "raison": "Inputs and outputs are not in the same database",
    }
    hive = moteurs.inventaire_moteurs("PROJ", "join_out", "HIVE")["recettes"][0]
    assert hive["bascule"]["possible"] is False
    assert "non proposé" in hive["bascule"]["raison"]


def test_lecture_seule(dss):
    moteurs.inventaire_moteurs("PROJ", moteur_cible="SPARK")
    assert dss.writes() == []


def test_recette_inconnue(dss):
    assert moteurs.inventaire_moteurs("PROJ", "nope")["error_type"] == "not_found"


def test_commande_chat(dss, capsys):
    from scripts import chat_llm
    from tests.test_chat_llm import SessionEnMemoire

    asyncio.run(chat_llm.COMMANDES["/moteurs"](SessionEnMemoire(), "/moteurs PROJ SPARK"))
    sortie = capsys.readouterr().out
    assert "join_out [join] : DSS (configuré : AUTO (choix de DSS))" in sortie
    assert "❌ SQL : Inputs and outputs are not in the same database" in sortie
    assert "🟢 vers SPARK" in sortie
    assert "1 possibles, 1 impossibles" in sortie


def test_transferts_rapides_regroupes(dss):
    join = moteurs.inventaire_moteurs("PROJ", "join_out")["recettes"][0]
    assert join["transferts_rapides_non_applicables"] == ["S3_TO_REDSHIFT", "TDCH"]
    assert [m["moteur"] for m in join["moteurs_indisponibles"]] == ["SQL"]


def test_recette_de_plugin(dss):
    dss.state["recipes"]["hive_ext"] = {
        "recipe": {"name": "hive_ext", "projectKey": "PROJ",
                   "type": "CustomCode_create-hive-external-table-recipe",
                   "params": {}, "inputs": {}, "outputs": {}, "tags": []},
        "payload": "",
    }
    dss.state["recipe_status"]["hive_ext"] = {
        "selectedEngine": {"type": "SPARK"},
        "engines": [{"type": "SPARK", "statusWarnLevel": "ERROR"}],
    }
    r = moteurs.inventaire_moteurs("PROJ", details=True)
    plugin = par_recette(r)["hive_ext"]
    assert plugin["plugin"] == "create-hive-external-table-recipe"
    assert "plugin" in plugin["note"]
    assert plugin["statut_brut"]["selectedEngine"] == {"type": "SPARK"}
    assert r["synthese"]["recettes_plugin"] == ["hive_ext (create-hive-external-table-recipe)"]


def test_recette_code_moteur_impose(dss):
    code = par_recette(moteurs.inventaire_moteurs("PROJ"))["compute_mid"]
    assert code["moteur_configure"] == "imposé par le type de recette"
