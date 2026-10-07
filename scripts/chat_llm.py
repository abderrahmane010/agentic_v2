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
    python scripts/chat_llm.py
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
- Pour les liens entre projets, l'ordre ou les vagues de migration :
  dependances_inter_projets.
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
        print(f"Erreur : {donnees.get('error') or donnees}")
        return

    print(f"\nProjet {donnees['projet']} — "
          f"{donnees['statistiques']['nb_datasets_total']} datasets")
    for cle, titre in _TITRES.items():
        elements = donnees.get(cle, [])
        print(f"\n{titre} ({len(elements)})")
        for element in elements:
            connexion = element.get("connexion") or "-"
            print(f"  - {element['nom']}  [{element.get('type')}, {connexion}]")
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
        "| Fournisseur | Consommateur | Nb objets | Via | Objets |",
        "|---|---|---|---|---|",
    ]
    for lien in donnees["liens"]:
        lignes.append(
            f"| {lien['fournisseur']} | {lien['consommateur']} | "
            f"{lien['nb_objets']} | {', '.join(lien['via'])} | "
            f"{', '.join(lien['objets'])} |"
        )

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

    if donnees.get("error") or donnees.get("success") is False:
        print(f"Erreur : {donnees.get('error') or donnees}")
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
        return

    stats = donnees["statistiques"]
    print(f"\n{stats['nb_projets_analyses']} projets, {stats['nb_liens']} liens, "
          f"{stats['nb_cycles']} cycles, {stats['nb_projets_isoles']} isolés")
    for vague in donnees["vagues"]:
        print(f"  Vague {vague['vague']} : {', '.join(vague['projets'])}")
    for cycle in donnees["cycles"]:
        print(f"  🔁 Cycle : {' ↔ '.join(cycle)}")

    dossier = RACINE / "rapports"
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"dependances_inter_projets_{datetime.now():%Y%m%d_%H%M}.md"
    fichier.write_text(_rapport_dependances_markdown(donnees), encoding="utf-8")
    print(f"\n📄 Rapport complet : {fichier}")


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
                            "\n🧑 Toi (/tables PROJET, /dependances [PROJET], "
                            "exit pour quitter) : "
                        ).strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if question.lower() in {"exit", "quit", "q"}:
                        break
                    if not question:
                        continue

                if question.startswith("/tables"):
                    await _afficher_tables(session, question)
                    continue

                if question.startswith("/dependances"):
                    await _afficher_dependances(session, question)
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
