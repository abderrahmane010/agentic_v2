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
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import APIStatusError, AsyncOpenAI

RACINE = Path(__file__).resolve().parent.parent
load_dotenv(RACINE / ".env")

# Limite la taille des résultats d'outils renvoyés au LLM (contexte limité).
TAILLE_MAX_RESULTAT = 12_000
NB_MAX_APPELS_OUTILS = 10

PROMPT_SYSTEME = """Tu es un assistant expert de Dataiku DSS.
Tu disposes d'outils pour interroger l'instance DSS (projets, Flow,
datasets, recettes, scénarios, jobs...).
- Utilise les outils pour obtenir des informations réelles, n'invente rien.
- Si la clé projet (project_key) manque, demande-la à l'utilisateur.
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

    verify = not _vrai(os.environ.get("VLLM_INSECURE_TLS"), False)
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

    if len(texte) > TAILLE_MAX_RESULTAT:
        texte = texte[:TAILLE_MAX_RESULTAT] + "\n... (résultat tronqué)"
    return texte


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
                        question = input("\n🧑 Toi (exit pour quitter) : ").strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if question.lower() in {"exit", "quit", "q"}:
                        break
                    if not question:
                        continue

                taille_historique = len(messages)
                messages.append({"role": "user", "content": question})

                try:
                    texte = await _repondre(
                        llm, modele, session, outils, messages
                    )
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
