#!/usr/bin/env python3
"""
Chat en terminal avec un LLM (API compatible OpenAI, ex. vLLM) qui
interroge Dataiku DSS via les outils du serveur MCP de ce projet.

Variables d'environnement (.env) :
    VLLM_BASE_URL      URL de l'API, ex. https://.../v1
    VLLM_MODEL         Nom du modèle, ex. Qwen/Qwen2.5-7B-Instruct
    OPENAI_API_KEY     Clé API ("EMPTY" si vLLM sans authentification)
    VLLM_INSECURE_TLS  true pour ignorer le certificat TLS (défaut : false)
    CHAT_READ_ONLY     true pour n'exposer que les outils de lecture
                       (défaut : true)

Usage :
    python scripts/chat_llm.py               (puis /aide pour les commandes)
    python scripts/chat_llm.py --question "Quelles sont les tables finales du projet X ?"
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import APIConnectionError, APIStatusError, AsyncOpenAI

# Permet de lancer le script sans installer le package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataiku_mcp import rapports_migration  # noqa: E402
from dataiku_mcp.tools.dependances_projets import generer_mermaid  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
load_dotenv(RACINE / ".env")

# Limite la taille des résultats d'outils renvoyés au LLM (contexte limité).
TAILLE_MAX_RESULTAT = int(os.environ.get("CHAT_MAX_RESULT_CHARS", "40000"))
NB_MAX_APPELS_OUTILS = 10

PROMPT_SYSTEME = """Tu es un assistant expert de Dataiku DSS.
Tu disposes d'outils pour interroger l'instance DSS (projets, Flow,
datasets, recettes, scénarios, jobs...).
- Utilise les outils pour obtenir des informations réelles, n'invente rien.
- Si la clé projet (project_key) manque, demande-la à l'utilisateur.
- Pour la liste des datasets/tables d'un projet : classer_datasets_flow,
  puis présente-les classés en 4 sections (sources, intermédiaires,
  finales, isolées) avec le nombre de chaque catégorie.
- list_datasets seulement pour une liste brute non classée.
- Pour lister les recettes ou scénarios : list_recipes / list_scenarios.
- Quand tu listes des éléments, donne-les TOUS, sans en omettre ni
  résumer par "...", et indique le total.
- Pour connaître les projets disponibles : list_dss_projects.
- Pour les liens entre projets, l'ordre ou les vagues de migration, ou
  savoir si une table (même "finale") est utilisée par un autre projet :
  dependances_inter_projets (champ tables_interface).
- Pour la complexité de migration vers Databricks, les technologies
  (HDFS, Hive, Impala, Spark) ou le code spécifique Cloudera :
  inventaire_technique_migration.
- Détail d'un dataset (connexion, chemin/table, partitionnement, dernier
  build) : get_dataset_info ; colonnes : inspect_dataset_schema ;
  volumétrie / métriques : check_dataset_metrics ; aperçu des données :
  get_dataset_sample.
- Moteur d'exécution des recettes (menu Engine), moteurs disponibles ou
  non, possibilité de passer d'un moteur à un autre (ex. HIVE vers
  SPARK) : inventaire_moteurs (option moteur_cible).
- Détail d'une recette (type, entrées/sorties, moteur) : get_recipe_info ;
  son code : get_recipe_code ; SQL d'une recette visuelle :
  get_generated_sql.
- Planification et déclencheurs d'un scénario, dernier et prochain run :
  get_scenario_info ; historique des runs : get_scenario_run_history ;
  étapes et code : get_scenario_steps ; cause d'un échec :
  get_scenario_logs.
- Exécutions récentes ou échecs d'un projet : get_recent_runs (option
  status_filter="FAILED") ; détail et log d'un job : get_job_details.
- Connexions, environnements de code, variables : get_connections,
  get_code_environments, get_project_variables.
- Graphe complet du Flow : get_project_flow ; recherche par nom :
  search_project_objects ; configuration complète d'un projet :
  export_project_config.
- Si un outil renvoie "status": "error", explique le message à
  l'utilisateur au lieu d'inventer une réponse.
- Réponds en français, de façon concise et structurée."""


def _vrai(valeur: str | None, defaut: bool) -> bool:
    if valeur is None or not valeur.strip():
        return defaut
    return valeur.strip().lower() in {"1", "true", "yes", "oui", "on"}


def _creer_client_llm() -> tuple[AsyncOpenAI, str]:
    base_url = os.environ.get("VLLM_BASE_URL")
    modele = os.environ.get("VLLM_MODEL")

    if not base_url or not modele:
        sys.exit("VLLM_BASE_URL et VLLM_MODEL doivent être définis dans .env")

    # Certificat d'entreprise : VLLM_CA_BUNDLE=/chemin/ca.pem (recommandé)
    # ou VLLM_INSECURE_TLS=true (désactive la vérification).
    verify: bool | str = not _vrai(os.environ.get("VLLM_INSECURE_TLS"), False)
    ca_bundle = os.environ.get("VLLM_CA_BUNDLE", "").strip()
    if verify and ca_bundle:
        verify = ca_bundle
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=os.environ.get("OPENAI_API_KEY", "EMPTY"),
        http_client=httpx.AsyncClient(verify=verify, timeout=120),
    )
    return client, modele


def _outil_vers_openai(outil: Any) -> dict[str, Any]:
    """Convertit un outil MCP au format 'tools' de l'API OpenAI."""
    return {
        "type": "function",
        "function": {
            "name": outil.name,
            "description": (outil.description or "")[:1000],
            "parameters": outil.inputSchema,
        },
    }


def _texte_resultat(resultat: Any) -> str:
    morceaux = [
        getattr(bloc, "text", "")
        for bloc in resultat.content
        if getattr(bloc, "type", None) == "text"
    ]
    texte = "\n".join(morceaux) or "(résultat vide)"

    # JSON compact (sans indentation) : jusqu'à 2x moins de tokens.
    try:
        texte = json.dumps(
            json.loads(texte), ensure_ascii=False, separators=(",", ":")
        )
    except ValueError:
        pass

    if len(texte) > TAILLE_MAX_RESULTAT:
        texte = texte[:TAILLE_MAX_RESULTAT] + "\n... (résultat tronqué)"
    return texte


_TITRES = {
    "tables_sources": "📥 Tables sources",
    "tables_intermediaires": "🔄 Tables intermédiaires",
    "tables_finales": "📤 Tables finales",
    "tables_isolees": "⚪ Tables isolées",
}


async def _afficher_tables(session: ClientSession, commande: str) -> None:
    """Commande /tables PROJET : affiche la classification complète du Flow
    directement, sans passer par le LLM (aucun dataset oublié)."""
    morceaux = commande.split()
    if len(morceaux) < 2:
        print("Usage : /tables CLE_PROJET")
        return

    resultat = await session.call_tool(
        "classer_datasets_flow", {"project_key": morceaux[1]}
    )
    try:
        donnees = json.loads(_texte_resultat(resultat))
    except ValueError:
        print(_texte_resultat(resultat))
        return

    if "statistiques" not in donnees:
        print(f"Erreur : {donnees.get('message') or donnees.get('error') or donnees}")
        return

    print(f"\nProjet {donnees['projet']} — "
          f"{donnees['statistiques']['nb_datasets_total']} datasets")
    for cle, titre in _TITRES.items():
        elements = donnees.get(cle, [])
        print(f"\n{titre} ({len(elements)})")
        for element in elements:
            connexion = element.get("connexion") or "-"
            print(f"  - {element['nom']}  [{element.get('type')}, {connexion}]")
    autres = donnees.get("autres_objets_flow") or []
    if autres:
        print(f"\n📁 Autres objets du Flow, hors datasets ({len(autres)})")
        for objet in autres:
            print(f"  - {objet['nom']}  [{objet['type']}]")
    for erreur in donnees.get("erreurs_flow", []):
        print(f"\n⚠️  Recette {erreur.get('recette')} : {erreur.get('erreur')}")


def _rapport_dependances_markdown(donnees: dict[str, Any]) -> str:
    """Rapport Markdown (graphe Mermaid affiché par GitLab) pour architectes."""
    stats = donnees["statistiques"]
    lignes = [
        "# Dépendances inter-projets Dataiku",
        "",
        f"Généré le {datetime.now():%d/%m/%Y %H:%M}.",
        "",
        "## Synthèse",
        "",
        f"- Projets analysés : {stats['nb_projets_analyses']}",
        f"- Liens entre projets : {stats['nb_liens']}",
        f"- Projets isolés (migrables à tout moment) : {stats['nb_projets_isoles']}",
        f"- Cycles (projets à migrer ensemble) : {stats['nb_cycles']}",
        f"- Vagues de migration proposées : {stats['nb_vagues']}",
        f"- Tables d'interface entre projets : {stats.get('nb_tables_interface', 0)}",
        f"- Emplacements écrits par plusieurs projets : "
        f"{stats.get('nb_ecritures_multiples', 0)}",
        "",
        "## Graphe",
        "",
        "```mermaid",
        generer_mermaid(donnees),
        "```",
        "",
        "## Vagues de migration proposées",
        "",
    ]
    for vague in donnees["vagues"]:
        lignes.append(f"- **Vague {vague['vague']}** : {', '.join(vague['projets'])}")
    if donnees["projets_isoles"]:
        lignes.append(f"- **Isolés** : {', '.join(donnees['projets_isoles'])}")

    if donnees["cycles"]:
        lignes += ["", "## Cycles (à migrer ensemble)", ""]
        lignes += [f"- {' ↔ '.join(cycle)}" for cycle in donnees["cycles"]]

    lignes += [
        "",
        "## Détail des liens",
        "",
        "Via : recette (entrée de recette), scenario, stockage (même table ou "
        "chemin physique), code (référence dans le code d'une recette).",
        "",
        "| Fournisseur | Consommateur | Nb objets | Via | Objets |",
        "|---|---|---|---|---|",
    ]
    for lien in donnees["liens"]:
        lignes.append(
            f"| {lien['fournisseur']} | {lien['consommateur']} | "
            f"{lien['nb_objets']} | {', '.join(lien['via'])} | "
            f"{', '.join(lien['objets'])} |"
        )

    interfaces = donnees.get("tables_interface") or []
    if interfaces:
        lignes += [
            "",
            "## Tables d'interface (utilisées par d'autres projets)",
            "",
            "Contrats entre projets : migrer le producteur d'abord et garder "
            "nom, schéma et emplacement, ou synchroniser les deux plateformes "
            "pendant la transition.",
            "",
            "| Projet | Dataset | Statut local | Emplacement | Consommateurs (via) |",
            "|---|---|---|---|---|",
        ]
        for table in interfaces:
            conso = ", ".join(
                f"{c['projet']} ({', '.join(sorted({v.split(':')[0] for v in c['via']}))})"
                for c in table["consommateurs"]
            )
            lignes.append(
                f"| {table['projet']} | {table['dataset']} | "
                f"{table['statut_local']} | {table['emplacement'] or '-'} | {conso} |"
            )

    emplacements = donnees.get("emplacements_partages") or {}
    if emplacements.get("ecritures_multiples"):
        lignes += ["", "## ⚠️ Emplacements écrits par plusieurs projets", ""]
        for e in emplacements["ecritures_multiples"]:
            lignes.append(f"- `{e['emplacement']}` : {', '.join(e['ecrivains'])}")
    if emplacements.get("sources_externes_partagees"):
        lignes += ["", "## Sources externes lues par plusieurs projets", ""]
        for e in emplacements["sources_externes_partagees"]:
            lignes.append(f"- `{e['emplacement']}` : {', '.join(e['datasets'])}")

    externes = donnees.get("projets_externes_ou_inaccessibles") or {}
    if externes:
        lignes += ["", "## Projets externes ou inaccessibles", ""]
        for projet, consommateurs in externes.items():
            lignes.append(f"- {projet} → utilisé par {', '.join(consommateurs)}")

    inutilises = donnees.get("partages_declares_non_utilises") or []
    if inutilises:
        lignes += ["", "## Partages déclarés mais non utilisés", ""]
        for partage in inutilises:
            lignes.append(
                f"- {partage['fournisseur']} → {partage['cible']} : "
                f"{', '.join(partage['objets'])}"
            )

    if donnees.get("erreurs"):
        lignes += ["", "## Erreurs de lecture", ""]
        for erreur in donnees["erreurs"]:
            lignes.append(f"- {erreur['projet']} : {erreur['erreur']}")

    lignes += ["", f"> {donnees['note']}", ""]
    return "\n".join(lignes)



def _afficher_erreurs_lecture(erreurs: list[dict[str, str]]) -> None:
    """Signale les objets illisibles : sans eux le résultat peut être incomplet."""
    if not erreurs:
        print("\n✅ Tous les projets ont été lus sans erreur.")
        return
    print(f"\n⚠️  {len(erreurs)} erreur(s) de lecture, résultat possiblement incomplet :")
    for erreur in erreurs[:20]:
        print(f"  - {erreur.get('projet')} : {erreur.get('erreur')}")
    if len(erreurs) > 20:
        print(f"  ... et {len(erreurs) - 20} autre(s) (voir le rapport complet)")

async def _afficher_dependances(session: ClientSession, commande: str) -> None:
    """Commande /dependances [PROJET] : dépendances inter-projets sans LLM.

    Sans projet : vue de toute l'instance + rapport Markdown dans rapports/.
    """
    morceaux = commande.split()
    projet = morceaux[1] if len(morceaux) > 1 else None
    print("⏳ Analyse des projets (peut prendre plusieurs minutes)...")

    arguments: dict[str, Any] = {"details": True}
    if projet:
        arguments["project_key"] = projet

    resultat = await session.call_tool("dependances_inter_projets", arguments)
    morceaux_texte = [
        getattr(b, "text", "") for b in resultat.content
        if getattr(b, "type", None) == "text"
    ]
    try:
        donnees = json.loads("\n".join(morceaux_texte))
    except ValueError:
        print("\n".join(morceaux_texte))
        return

    if donnees.get("status") == "error" or donnees.get("error"):
        print(f"Erreur : {donnees.get('message') or donnees.get('error') or donnees}")
        return

    if projet:
        print(f"\nProjet {projet} — vague {donnees['vague']}")
        print("\n⬆️  Dépend de :")
        for lien in donnees["depend_de"] or []:
            print(f"  - {lien['fournisseur']} ({lien['nb_objets']} objets : "
                  f"{', '.join(lien['objets'][:10])})")
        print("\n⬇️  Utilisé par :")
        for lien in donnees["utilise_par"] or []:
            print(f"  - {lien['consommateur']} ({lien['nb_objets']} objets : "
                  f"{', '.join(lien['objets'][:10])})")
        prerequis = donnees["prerequis_migration"]
        print(f"\n📋 À migrer avant : {', '.join(prerequis) or 'aucun'}")
        if donnees.get("cycle"):
            print(f"🔁 Cycle, à migrer ensemble : {' ↔ '.join(donnees['cycle'])}")
        _afficher_interfaces(donnees.get("tables_interface_produites") or [],
                             "📤 Tables d'interface produites")
        _afficher_interfaces(donnees.get("tables_interface_consommees") or [],
                             "📥 Tables d'interface consommées")
        _afficher_erreurs_lecture(donnees.get("erreurs") or [])
        return

    stats = donnees["statistiques"]
    print(f"\n{stats['nb_projets_analyses']} projets, {stats['nb_liens']} liens, "
          f"{stats['nb_cycles']} cycles, {stats['nb_projets_isoles']} isolés")
    for vague in donnees["vagues"]:
        print(f"  Vague {vague['vague']} : {', '.join(vague['projets'])}")
    for cycle in donnees["cycles"]:
        print(f"  🔁 Cycle : {' ↔ '.join(cycle)}")
    print(f"  {stats.get('nb_tables_interface', 0)} tables d'interface, "
          f"{stats.get('nb_ecritures_multiples', 0)} emplacements écrits par "
          "plusieurs projets (détail : /interfaces)")
    _afficher_erreurs_lecture(donnees.get("erreurs") or [])

    dossier = RACINE / "rapports"
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"dependances_inter_projets_{datetime.now():%Y%m%d_%H%M}.md"
    fichier.write_text(_rapport_dependances_markdown(donnees), encoding="utf-8")
    print(f"\n📄 Rapport complet : {fichier}")


def _via(consommateur: dict[str, Any]) -> str:
    return ", ".join(sorted({v.split(":", 1)[0] for v in consommateur["via"]}))


def _afficher_interfaces(tables: list[dict[str, Any]], titre: str) -> None:
    print(f"\n{titre} ({len(tables)}) :")
    if not tables:
        print("  aucune")
    for table in tables:
        consommateurs = ", ".join(
            f"{c['projet']} [{_via(c)}]" for c in table["consommateurs"]
        )
        print(f"  - {table['projet']}.{table['dataset']} ({table['statut_local']})"
              f" → {consommateurs}")


async def _afficher_tables_interface(session: ClientSession, commande: str) -> None:
    """Commande /interfaces [PROJET] : tables utilisées par d'autres projets."""
    morceaux = commande.split()
    projet = morceaux[1] if len(morceaux) > 1 else None
    print("⏳ Analyse des projets (peut prendre plusieurs minutes)...")
    arguments: dict[str, Any] = {"details": True}
    if projet:
        arguments["project_key"] = projet
    donnees = await _appeler(session, "dependances_inter_projets", arguments)
    if not donnees:
        return

    if projet:
        _afficher_interfaces(donnees["tables_interface_produites"],
                             f"📤 Tables de {projet} utilisées ailleurs")
        _afficher_interfaces(donnees["tables_interface_consommees"],
                             f"📥 Tables d'autres projets utilisées par {projet}")
    else:
        _afficher_interfaces(donnees["tables_interface"], "🔗 Tables d'interface")
        constats = donnees["emplacements_partages"]
        if constats["ecritures_multiples"]:
            print("\n⚠️  Emplacements écrits par plusieurs projets :")
            for e in constats["ecritures_multiples"]:
                print(f"  - {e['emplacement']} : {', '.join(e['ecrivains'])}")
        if constats["sources_externes_partagees"]:
            print("\nℹ️  Sources externes lues par plusieurs projets :")
            for e in constats["sources_externes_partagees"]:
                print(f"  - {e['emplacement']} : {', '.join(e['datasets'])}")
    _afficher_erreurs_lecture(donnees.get("erreurs") or [])
    print("\nStatut local « finale » + consommateurs = contrat entre projets : "
          "à migrer en premier, même nom, schéma et emplacement.")


# Mots reconnus comme moteur cible dans /moteurs (le reste = nom de recette).
MOTEURS_CONNUS = {"DSS", "SPARK", "HIVE", "IMPALA", "SQL", "PIG", "PYTHON", "R"}


async def _afficher_moteurs(session: ClientSession, commande: str) -> None:
    """Commande /moteurs PROJET [RECETTE] [CIBLE] : moteurs des recettes."""
    morceaux = commande.split()
    if len(morceaux) < 2 or len(morceaux) > 5:
        print("Usage : /moteurs PROJET [RECETTE] [MOTEUR_CIBLE] [tout]\n"
              "  ex. /moteurs AEL            recettes visuelles\n"
              "      /moteurs AEL SPARK      recettes visuelles, bascule vers SPARK\n"
              "      /moteurs AEL ma_recette SPARK\n"
              "      /moteurs AEL tout       aussi les recettes de code et de plugin")
        return
    arguments: dict[str, Any] = {"project_key": morceaux[1]}
    for mot in morceaux[2:]:
        if mot.lower() in ("tout", "--tout", "all"):
            arguments["inclure_code"] = True
        elif mot.upper() in MOTEURS_CONNUS:
            arguments["moteur_cible"] = mot
        else:
            arguments["recipe_name"] = mot
    print("⏳ Lecture du statut de chaque recette...")
    donnees = await _appeler(session, "inventaire_moteurs", arguments)
    if not donnees:
        return

    synthese = donnees["synthese"]
    repartition = ", ".join(
        f"{m} {n}" for m, n in sorted(synthese["par_moteur_selectionne"].items())
    )
    if "recipe_name" in arguments:
        portee = f"recette {arguments['recipe_name']}"
    elif arguments.get("inclure_code"):
        portee = f"{synthese['nb_recettes']} recettes"
    else:
        portee = f"{synthese['nb_recettes']} recettes visuelles"
    print(f"\nProjet {morceaux[1]} — {portee} : {repartition}")
    if synthese.get("recettes_plugin"):
        print(f"🧩 Recettes de plugin à examiner : {', '.join(synthese['recettes_plugin'])}")
    for r in donnees["recettes"]:
        dispo = ", ".join(
            m["moteur"]
            + (f" ({m['variante']})" if m.get("variante") else "")
            + (" ⭐ recommandé" if m.get("recommande") else "")
            + (" — imposé" if m.get("impose") else "")
            for m in r["moteurs_disponibles"]
        ) or "-"
        variante = f" / {r['variante_selectionnee']}" if r.get("variante_selectionnee") else ""
        print(f"\n  ⚙️  {r['recette']} [{r['type']}] : {r['moteur_selectionne']}{variante}"
              f" (configuré : {r['moteur_configure']})")
        print(f"     ✅ disponibles : {dispo}")
        for m in r["moteurs_indisponibles"]:
            variante = f" ({m['variante']})" if m.get("variante") else ""
            reco = " (recommandé par DSS)" if m.get("recommande") else ""
            print(f"     ❌ {m['moteur']}{variante}{reco} : {m['raison']}")
        if r.get("transferts_rapides_non_applicables"):
            print(f"     ➖ {len(r['transferts_rapides_non_applicables'])} moteurs de "
                  "transfert rapide (S3_TO_…, …_TO_DATABRICKS) non applicables")
        if r.get("plugin"):
            print(f"     🧩 plugin : {r['plugin']}")
        if r.get("note"):
            print(f"     ℹ️  {r['note']}")
        if r.get("bascule"):
            b = r["bascule"]
            print(f"     {'🟢' if b['possible'] else '🔴'} vers {b['cible']} : {b['raison']}")

    ignorees = synthese.get("recettes_code_ou_plugin_ignorees") or []
    if ignorees:
        print(f"\nℹ️  {len(ignorees)} recette(s) de code/plugin non affichées "
              "(moteur imposé) : ajouter « tout » pour les voir")
    bascule = synthese.get("bascule_vers")
    if bascule:
        print(f"\n📊 Bascule vers {bascule['cible']} : {bascule['deja_sur_cible']} déjà, "
              f"{len(bascule['possibles'])} possibles, "
              f"{len(bascule['impossibles'])} impossibles")
    for e in donnees.get("erreurs", []):
        print(f"⚠️  {e['recette']} : {e['erreur']}")
    print("\nLecture seule : aucune modification dans DSS.")


_ICONES_GRAVITE = {"haute": "🔴", "moyenne": "🟠", "basse": "🟡"}


async def _afficher_migration(session: ClientSession, commande: str) -> None:
    """Commande /migration [PROJET] : inventaire technique sans LLM.

    Écrit aussi un rapport Markdown et des CSV (Excel) dans rapports/.
    """
    morceaux = commande.split()
    projet = morceaux[1] if len(morceaux) > 1 else None
    print("⏳ Inventaire en cours (lecture du code de chaque recette)...")

    arguments: dict[str, Any] = {"details": True}
    if projet:
        arguments["project_key"] = projet

    resultat = await session.call_tool("inventaire_technique_migration", arguments)
    texte = "\n".join(
        getattr(b, "text", "") for b in resultat.content
        if getattr(b, "type", None) == "text"
    )
    try:
        donnees = json.loads(texte)
    except ValueError:
        print(texte)
        return

    if donnees.get("status") == "error" or donnees.get("error"):
        print(f"Erreur : {donnees.get('message') or donnees.get('error') or donnees}")
        return

    dossier = RACINE / "rapports"

    if projet:
        print(f"\nProjet {projet} — complexité {donnees['complexite']} "
              f"(score {donnees['score']})")
        for raison in donnees["raisons"]:
            print(f"  • {raison}")
        st, rc = donnees["stockage"], donnees["recettes"]
        print(f"\n💾 {st['total']} datasets : "
              + ", ".join(f"{k} {v}" for k, v in st["par_categorie"].items()))
        print(f"⚙️  {rc['total']} recettes : "
              + ", ".join(f"{k} {v}" for k, v in rc["par_moteur"].items()))
        if rc["plugins"]:
            print(f"🧩 Plugins : {', '.join(rc['plugins'])}")
        print("\n🔎 Adhérences Cloudera dans le code :")
        if not donnees["adherences_cloudera"]:
            print("  aucune détectée")
        for adh in donnees["adherences_cloudera"]:
            objets = ", ".join(o.split(":", 1)[1] for o in adh["objets"][:5])
            suite = "..." if len(adh["objets"]) > 5 else ""
            print(f"  {_ICONES_GRAVITE[adh['gravite']]} {adh['libelle']} "
                  f"— {objets}{suite}")
        fichiers = rapports_migration.rapport_projet(donnees, dossier)
    else:
        stats = donnees["statistiques"]
        print(f"\n{stats['nb_projets']} projets : {stats['complexes']} complexes, "
              f"{stats['moyens']} moyens, {stats['simples']} simples\n")
        for p in donnees["projets"]:
            print(f"  {p['complexite']:<9} {p['score']:>4}  {p['projet']}")
        fichiers = rapports_migration.rapport_instance(donnees, dossier)

    _afficher_erreurs_lecture(donnees.get("erreurs") or [])
    print("\n📄 Rapports :")
    for fichier in fichiers:
        print(f"  {fichier}")


# ---------------------------------------------------------------------------
# Commandes directes (sans LLM) sur les outils de base
# ---------------------------------------------------------------------------
AIDE = """Commandes directes (sans LLM, sortie complète) :
  /projets                       projets DSS accessibles
  /tables PROJET                 datasets classés source / intermédiaire / final
  /scenarios PROJET              scénarios, déclencheurs, dernier et prochain run
  /echecs PROJET                 exécutions en échec récentes (scénarios et jobs)
  /logs PROJET SCENARIO [RUN]    étapes et première erreur d'un run de scénario
  /connexions [PROJET]           connexions DSS (et leur usage par le projet)
  /export PROJET                 configuration complète du projet -> rapports/
  /dependances [PROJET]          dépendances inter-projets et vagues de migration
  /interfaces [PROJET]           tables d'un projet utilisées par d'autres projets
  /moteurs PROJET [RECETTE] [CIBLE] [tout]
                                 moteurs des recettes visuelles (actuel,
                                 disponibles, bascule vers CIBLE, ex. SPARK) ;
                                 RECETTE : une seule ; tout : + code/plugin
  /migration [PROJET]            inventaire technique avant migration Databricks
  /outils                        outils disponibles pour le LLM
  /aide                          cette aide
  exit                           quitter
Toute autre saisie est envoyée au LLM."""


async def _appeler(
    session: ClientSession, outil: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    """Appelle un outil MCP ; affiche l'erreur et renvoie None si échec."""
    resultat = await session.call_tool(outil, arguments)
    texte = "\n".join(
        getattr(b, "text", "") for b in resultat.content
        if getattr(b, "type", None) == "text"
    )
    try:
        donnees = json.loads(texte)
    except ValueError:
        print(texte)
        return None
    if not isinstance(donnees, dict):
        return {"resultat": donnees}
    if donnees.get("status") == "error" or donnees.get("error"):
        print(f"Erreur : {donnees.get('message') or donnees.get('error')}")
        return None
    return donnees


def _argument(commande: str, position: int, usage: str) -> str | None:
    morceaux = commande.split()
    if len(morceaux) <= position:
        print(f"Usage : {usage}")
        return None
    return morceaux[position]


def _date(valeur: str | None) -> str:
    """ISO 8601 -> 'JJ/MM/AAAA HH:MM' (UTC)."""
    if not valeur:
        return "-"
    try:
        return datetime.fromisoformat(valeur).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return valeur


def _decrire_trigger(trigger: dict[str, Any]) -> str:
    etat = "" if trigger.get("active") else " (inactif)"
    if trigger.get("type") == "temporal":
        heure = ""
        if trigger.get("hour") is not None:
            heure = f" à {trigger['hour']:02d}:{trigger.get('minute') or 0:02d}"
        return (f"planifié {trigger.get('frequency') or ''}{heure}"
                f" ({trigger.get('timezone') or 'SERVER'}){etat}")
    if trigger.get("datasets"):
        return f"sur modification de {', '.join(trigger['datasets'])}{etat}"
    return f"{trigger.get('type')} {trigger.get('name') or ''}{etat}"


async def _afficher_projets(session: ClientSession, commande: str) -> None:
    donnees = await _appeler(session, "list_dss_projects", {})
    if donnees:
        print(f"\n{len(donnees['projects'])} projets :")
        for cle in donnees["projects"]:
            print(f"  - {cle}")


async def _afficher_scenarios(session: ClientSession, commande: str) -> None:
    projet = _argument(commande, 1, "/scenarios PROJET")
    if not projet:
        return
    donnees = await _appeler(session, "list_scenarios", {"project_key": projet})
    if not donnees:
        return
    print(f"\nProjet {projet} — {donnees['total_count']} scénario(s)")
    for sc in donnees["scenarios"]:
        etat = "✅ actif" if sc["active"] else "⏸️  inactif"
        print(f"\n  {sc['id']} — {sc['name']} [{sc['type']}, {etat}]")
        for trigger in sc["triggers"]:
            print(f"     ⏰ {_decrire_trigger(trigger)}")
        info = await _appeler(
            session, "get_scenario_info",
            {"project_key": projet, "scenario_id": sc["id"]},
        )
        if info:
            dernier = info["scenario_info"].get("last_run") or {}
            print(f"     dernier run : {dernier.get('outcome') or '-'} "
                  f"le {_date(dernier.get('start_time'))}"
                  f" — prochain : {_date(info['scenario_info'].get('next_run'))}")
    for avertissement in donnees.get("warnings", []):
        print(f"\n⚠️  {avertissement}")


async def _afficher_echecs(session: ClientSession, commande: str) -> None:
    projet = _argument(commande, 1, "/echecs PROJET")
    if not projet:
        return
    donnees = await _appeler(
        session, "get_recent_runs", {"project_key": projet, "limit": 100}
    )
    if not donnees:
        return
    resume = donnees["summary"]
    taux = resume.get("success_rate")
    print(f"\nProjet {projet} — {resume['total_runs']} exécutions récentes, "
          f"{resume['failed_runs']} en échec"
          + (f", {taux} % de réussite" if taux is not None else ""))
    echecs = donnees["recent_failures"]
    if not echecs:
        print("✅ Aucun échec récent.")
        return
    for run in echecs:
        print(f"  ❌ {run['kind']:<8} {run['name'] or run['id']} — {run['outcome']} "
              f"le {_date(run.get('start_time'))}")
    print("\n→ Cause d'un échec de scénario : /logs PROJET SCENARIO")


async def _afficher_logs(session: ClientSession, commande: str) -> None:
    morceaux = commande.split()
    if len(morceaux) < 3:
        print("Usage : /logs PROJET SCENARIO [RUN_ID]")
        return
    arguments: dict[str, Any] = {
        "project_key": morceaux[1],
        "scenario_id": morceaux[2],
        "max_chars": 3000,
    }
    if len(morceaux) > 3:
        arguments["run_id"] = morceaux[3]
    donnees = await _appeler(session, "get_scenario_logs", arguments)
    if not donnees:
        return
    run = donnees.get("run_info")
    if not run:
        print(donnees.get("message", "Aucun run."))
        return
    print(f"\nRun {run['run_id']} — {run['outcome'] or 'en cours'} "
          f"le {_date(run.get('start_time'))} ({run.get('duration_seconds')} s)")
    for etape in donnees["steps"]:
        icone = "✅" if etape["outcome"] in ("SUCCESS", "WARNING") else "❌"
        print(f"  {icone} {etape['name']} [{etape['type']}] {etape['outcome']}")
    erreur = donnees.get("first_error")
    if erreur:
        print(f"\n🔴 Première erreur : {erreur.get('message') or erreur}")
    for job in donnees.get("job_logs", []):
        lignes = [ligne for ligne in (job["log"] or "").splitlines() if ligne.strip()]
        print(f"\n📄 Fin du log du job {job['job_id']} :")
        for ligne in lignes[-15:]:
            print(f"    {ligne}")


async def _afficher_connexions(session: ClientSession, commande: str) -> None:
    morceaux = commande.split()
    arguments = {"project_key": morceaux[1]} if len(morceaux) > 1 else {}
    donnees = await _appeler(session, "get_connections", arguments)
    if not donnees:
        return
    print(f"\n{donnees['connection_count']} connexions :")
    for type_connexion, noms in sorted(donnees["connection_types"].items()):
        print(f"  {type_connexion} ({len(noms)}) : {', '.join(noms)}")
    usage = donnees.get("project_connection_usage")
    if usage:
        print(f"\nUsage par le projet {morceaux[1]} :")
        for connexion, detail in usage.items():
            print(f"  {connexion} : {len(detail['datasets'])} dataset(s), "
                  f"{len(detail['recipes'])} recette(s)")
    for avertissement in donnees.get("warnings", []):
        print(f"\n⚠️  {avertissement}")


async def _exporter_projet(session: ClientSession, commande: str) -> None:
    projet = _argument(commande, 1, "/export PROJET")
    if not projet:
        return
    print("⏳ Export de la configuration...")
    donnees = await _appeler(
        session, "export_project_config", {"project_key": projet, "export_format": "yaml"}
    )
    if not donnees:
        return
    dossier = RACINE / "rapports"
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"config_{projet}_{datetime.now():%Y%m%d_%H%M}.yaml"
    fichier.write_text(donnees["content"], encoding="utf-8")
    stats = donnees["stats"]
    print(f"\n{stats['datasets']} datasets, {stats['recipes']} recettes, "
          f"{stats['scenarios']} scénarios")
    for avertissement in donnees.get("warnings", []):
        print(f"⚠️  {avertissement}")
    print(f"📄 Configuration : {fichier}")


def _afficher_outils(outils: list[dict[str, Any]]) -> None:
    print(f"\n{len(outils)} outils disponibles pour le LLM :")
    for outil in sorted(outils, key=lambda o: o["function"]["name"]):
        description = (outil["function"]["description"] or "").strip().splitlines()
        print(f"  - {outil['function']['name']} : {description[0] if description else ''}")


COMMANDES = {
    "/projets": _afficher_projets,
    "/tables": _afficher_tables,
    "/scenarios": _afficher_scenarios,
    "/echecs": _afficher_echecs,
    "/logs": _afficher_logs,
    "/connexions": _afficher_connexions,
    "/export": _exporter_projet,
    "/dependances": _afficher_dependances,
    "/interfaces": _afficher_tables_interface,
    "/moteurs": _afficher_moteurs,
    "/migration": _afficher_migration,
}


async def _repondre(
    llm: AsyncOpenAI,
    modele: str,
    session: ClientSession,
    outils: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> str:
    """Boucle LLM <-> outils MCP jusqu'à obtenir une réponse finale."""
    for _ in range(NB_MAX_APPELS_OUTILS):
        reponse = await llm.chat.completions.create(
            model=modele,
            messages=messages,
            tools=outils,
            tool_choice="auto",
            temperature=0,
        )
        message = reponse.choices[0].message

        if not message.tool_calls:
            messages.append({"role": "assistant", "content": message.content})
            return message.content or ""

        messages.append(message.model_dump(exclude_none=True))

        for appel in message.tool_calls:
            nom = appel.function.name
            try:
                arguments = json.loads(appel.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}

            print(f"  🔧 {nom}({json.dumps(arguments, ensure_ascii=False)})")

            try:
                resultat = await session.call_tool(nom, arguments)
                contenu = _texte_resultat(resultat)
            except Exception as exc:
                contenu = f"Erreur lors de l'appel de l'outil {nom} : {exc}"

            messages.append(
                {"role": "tool", "tool_call_id": appel.id, "content": contenu}
            )

    return "Trop d'appels d'outils successifs, reformule ta question."


async def main() -> None:
    parser = argparse.ArgumentParser(description="Chat LLM + Dataiku MCP")
    parser.add_argument("--question", "-q", help="Pose une seule question")
    args = parser.parse_args()

    llm, modele = _creer_client_llm()

    env_serveur = dict(os.environ)
    env_serveur["DSS_READ_ONLY"] = (
        "true" if _vrai(os.environ.get("CHAT_READ_ONLY"), True) else "false"
    )

    serveur = StdioServerParameters(
        command=sys.executable,
        args=[str(RACINE / "scripts" / "mcp_server.py")],
        env=env_serveur,
        cwd=str(RACINE),
    )

    async with stdio_client(serveur) as (lecture, ecriture):
        async with ClientSession(lecture, ecriture) as session:
            await session.initialize()
            outils_mcp = (await session.list_tools()).tools
            outils = [_outil_vers_openai(o) for o in outils_mcp]

            print(f"✅ Connecté : {modele} — {len(outils)} outils Dataiku")
            print(AIDE)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": PROMPT_SYSTEME}
            ]

            questions = [args.question] if args.question else None

            while True:
                if questions is not None:
                    if not questions:
                        break
                    question = questions.pop(0)
                    print(f"\n🧑 {question}")
                else:
                    try:
                        question = input(
                            "\n🧑 Toi (/aide pour les commandes, exit pour quitter) : "
                        ).strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if question.lower() in {"exit", "quit", "q"}:
                        break
                    if not question:
                        continue

                commande = question.split()[0].lower() if question.startswith("/") else ""
                if commande in ("/aide", "/help"):
                    print(AIDE)
                    continue
                if commande == "/outils":
                    _afficher_outils(outils)
                    continue
                if commande in COMMANDES:
                    try:
                        await COMMANDES[commande](session, question)
                    except Exception as exc:  # une commande ne doit pas tuer le chat
                        print(f"Erreur pendant {commande} : {exc}")
                    continue
                if commande:
                    print(f"Commande inconnue : {commande}. Tape /aide.")
                    continue

                taille_historique = len(messages)
                messages.append({"role": "user", "content": question})

                try:
                    texte = await _repondre(
                        llm, modele, session, outils, messages
                    )
                except APIConnectionError as exc:
                    texte = f"Impossible de joindre le LLM : {exc.__cause__ or exc}"
                    if "CERTIFICATE_VERIFY_FAILED" in str(exc.__cause__):
                        texte += (
                            "\n→ Certificat TLS non reconnu : renseigne "
                            "VLLM_CA_BUNDLE=/chemin/vers/ca.pem dans .env, "
                            "ou VLLM_INSECURE_TLS=true."
                        )
                    del messages[taille_historique:]
                except APIStatusError as exc:
                    texte = f"Erreur API LLM ({exc.status_code}) : {exc.message}"
                    if "tool" in str(exc.message).lower():
                        texte += (
                            "\n→ Le serveur vLLM doit être lancé avec "
                            "--enable-auto-tool-choice --tool-call-parser hermes "
                            "pour que le modèle puisse appeler des outils."
                        )
                    del messages[taille_historique:]

                print(f"\n🤖 {texte}")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
