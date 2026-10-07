"""
Contrôles de sécurité des outils MCP.

Configuration par variables d'environnement :
- DSS_READ_ONLY=true : bloque tous les outils qui modifient DSS ;
- DSS_ALLOWED_PROJECTS=PROJ_A,PROJ_B : limite l'accès à ces projets
  (vide ou absent = tous les projets accessibles avec la clé API).
"""

import functools
import inspect
import logging
import os
from collections.abc import Callable, Iterable
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_VRAI = {"1", "true", "yes", "oui", "on"}


def mode_lecture_seule() -> bool:
    """Indique si le serveur est en lecture seule (DSS_READ_ONLY)."""
    return os.environ.get("DSS_READ_ONLY", "false").strip().lower() in _VRAI


def projets_autorises() -> set[str]:
    """Retourne les projets autorisés (ensemble vide = tous)."""
    brut = os.environ.get("DSS_ALLOWED_PROJECTS", "")
    return {cle.strip() for cle in brut.split(",") if cle.strip()}


def verifier_projet(project_key: Any) -> str:
    """Valide une clé projet et vérifie qu'elle est autorisée.

    Returns:
        La clé projet nettoyée.

    Raises:
        ValueError: si la clé est vide ou n'est pas une chaîne.
        PermissionError: si le projet n'est pas dans DSS_ALLOWED_PROJECTS.
    """
    if not isinstance(project_key, str) or not project_key.strip():
        raise ValueError("project_key doit être une chaîne non vide")

    cle = project_key.strip()
    autorises = projets_autorises()

    if autorises and cle not in autorises:
        raise PermissionError(
            f"Accès au projet '{cle}' refusé (absent de DSS_ALLOWED_PROJECTS)"
        )

    return cle


def filtrer_projets(projets: Iterable[str]) -> list[str]:
    """Ne garde que les projets autorisés."""
    autorises = projets_autorises()
    return [p for p in projets if not autorises or p in autorises]


def outil_securise(
    ecriture: bool = False,
    champs_projet: tuple[str, ...] = ("project_key",),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Décorateur appliquant les contrôles de sécurité à un outil MCP.

    - bloque l'outil en lecture seule si ``ecriture=True`` ;
    - vérifie chaque argument listé dans ``champs_projet`` (s'il est fourni) ;
    - renvoie une erreur structurée au lieu de lever une exception.

    La signature de la fonction décorée est conservée (functools.wraps),
    ce qui permet à FastMCP de générer le schéma de l'outil.
    """

    def decorateur(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            nom = func.__name__

            if ecriture and mode_lecture_seule():
                logger.warning("Outil d'écriture bloqué (lecture seule) : %s", nom)
                return {
                    "success": False,
                    "error": (
                        f"L'outil '{nom}' modifie DSS et le serveur est en "
                        "lecture seule (DSS_READ_ONLY=true)."
                    ),
                }

            try:
                arguments = signature.bind(*args, **kwargs)
                arguments.apply_defaults()

                for champ in champs_projet:
                    valeur = arguments.arguments.get(champ)
                    if valeur is not None:
                        arguments.arguments[champ] = verifier_projet(valeur)

                logger.info("Appel outil : %s", nom)
                return func(*arguments.args, **arguments.kwargs)

            except (PermissionError, ValueError, TypeError) as exc:
                logger.warning("Outil %s refusé : %s", nom, exc)
                return {"success": False, "error": str(exc)}

        # Permet au serveur de masquer les outils d'écriture en lecture seule.
        wrapper.outil_ecriture = ecriture  # type: ignore[attr-defined]
        return wrapper

    return decorateur
