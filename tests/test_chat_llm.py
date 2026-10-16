"""Commandes directes du chat, exécutées sur le vrai serveur MCP en mémoire."""

import asyncio
from types import SimpleNamespace

import pytest

from dataiku_mcp import server
from scripts import chat_llm


class SessionEnMemoire:
    """Imite mcp.ClientSession en appelant directement le serveur FastMCP."""

    async def call_tool(self, nom, arguments):
        contenu, _ = await server.mcp.call_tool(nom, arguments)
        return SimpleNamespace(content=contenu)


def lancer(commande, capsys, monkeypatch=None, tmp_path=None):
    if tmp_path is not None:
        monkeypatch.setattr(chat_llm, "RACINE", tmp_path)
    nom = commande.split()[0]
    asyncio.run(chat_llm.COMMANDES[nom](SessionEnMemoire(), commande))
    return capsys.readouterr().out


def test_projets(dss, capsys):
    assert "- PROJ" in lancer("/projets", capsys)


def test_scenarios(dss, capsys):
    sortie = lancer("/scenarios PROJ", capsys)
    assert "SC1 — Daily build [step_based, ✅ actif]" in sortie
    assert "planifié Daily à 02:00" in sortie
    assert "sur modification de PROJ.out" in sortie
    assert "dernier run : FAILED" in sortie


def test_echecs(dss, capsys):
    sortie = lancer("/echecs PROJ", capsys)
    assert "1 en échec" in sortie
    assert "Daily build — FAILED" in sortie


def test_logs(dss, capsys):
    sortie = lancer("/logs PROJ SC1", capsys)
    assert "Première erreur : Table missing" in sortie
    assert "ERROR boom" in sortie


def test_connexions(dss, capsys):
    sortie = lancer("/connexions PROJ", capsys)
    assert "Databricks (1) : dbx" in sortie
    assert "pg : 1 dataset(s), 1 recette(s)" in sortie


def test_export(dss, capsys, monkeypatch, tmp_path):
    sortie = lancer("/export PROJ", capsys, monkeypatch, tmp_path)
    assert "3 datasets, 2 recettes, 2 scénarios" in sortie
    fichiers = list((tmp_path / "rapports").glob("config_PROJ_*.yaml"))
    assert len(fichiers) == 1
    assert "compute_mid" in fichiers[0].read_text(encoding="utf-8")


def test_tables(dss, capsys):
    sortie = asyncio.run(chat_llm._afficher_tables(SessionEnMemoire(), "/tables PROJ"))
    assert sortie is None
    assert "Tables finales (1)" in capsys.readouterr().out


@pytest.mark.parametrize("commande", ["/scenarios", "/logs PROJ", "/export"])
def test_usage(commande, dss, capsys):
    assert "Usage" in lancer(commande, capsys)


def test_erreur_affichee(dss, capsys, monkeypatch):
    monkeypatch.setenv("DSS_ALLOWED_PROJECTS", "OTHER")
    assert "Erreur : Accès au projet 'PROJ' refusé" in lancer("/scenarios PROJ", capsys)


def test_aide_cite_toutes_les_commandes():
    for commande in chat_llm.COMMANDES:
        assert commande in chat_llm.AIDE


def test_prompt_cite_les_outils_principaux():
    for outil in ("get_scenario_info", "get_scenario_logs", "get_recent_runs",
                  "get_dataset_info", "get_recipe_code", "get_connections"):
        assert outil in chat_llm.PROMPT_SYSTEME


def test_outils_du_prompt_existent():
    import re

    noms = {t.name for t in asyncio.run(server.mcp.list_tools())}
    cites = set(re.findall(r"\b(?:get|list|classer|check|inspect|search|export|"
                           r"dependances|inventaire)_[a-z_]+", chat_llm.PROMPT_SYSTEME))
    assert cites and cites <= noms, cites - noms
