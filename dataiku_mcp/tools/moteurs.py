"""
Inventaire des moteurs d'exécution des recettes (lecture seule).

Pour chaque recette : moteur configuré (menu "Engine" au-dessus de RUN),
moteur que DSS sélectionne réellement, moteurs disponibles et
indisponibles avec la raison donnée par DSS, et possibilité de passer à un
moteur cible (ex. HIVE -> SPARK).

Source : GET /projects/{projet}/recipes/{recette}/status
(DSSRecipe.get_status), le même calcul que l'interface DSS quand on ouvre
la recette. Rien n'est modifié ni sauvegardé dans DSS.
"""

import logging
from collections import Counter
from typing import Any, Optional

from dataiku_mcp.client import get_project
from dataiku_mcp.tools._common import CODE_RECIPE_TYPES, error, ok
from dataiku_mcp.tools.classification_dataset import _as_dict

logger = logging.getLogger(__name__)

# Moteur imposé par le type des recettes de code (pas de menu "Engine").
_MOTEUR_RECETTE_CODE = {
    "python": "PYTHON (local ou conteneur)",
    "cpython": "PYTHON (local ou conteneur)",
    "r": "R (local ou conteneur)",
    "pyspark": "SPARK",
    "sparkr": "SPARK",
    "spark_scala": "SPARK",
    "spark_sql_query": "SPARK",
    "sql_query": "SQL (base de la connexion)",
    "sql_script": "SQL (base de la connexion)",
    "hive": "HIVE",
    "impala": "IMPALA",
    "shell": "SHELL",
}

_SANS_RAISON = "indisponible (raison non fournie par DSS)"


def _transfert_rapide(type_moteur: str) -> bool:
    """Moteurs de transfert direct entre stockages (S3_TO_REDSHIFT, TDCH...).

    DSS les liste pour toutes les recettes Sync/Export ; ils ne servent que
    si l'entrée et la sortie sont sur les stockages concernés.
    """
    return "_TO_" in type_moteur or type_moteur == "TDCH"


def _type_moteur(moteur: dict[str, Any]) -> str:
    return str(moteur.get("type") or moteur.get("engineType") or "?").upper()


def _raison(moteur: dict[str, Any]) -> Optional[str]:
    """Message de DSS expliquant l'état d'un moteur.

    Selon le cas, DSS le place dans statusMessage ou dans un autre champ
    (raison de non-sélection) : on prend le premier texte trouvé dans un
    champ dont le nom évoque un message ou une raison.
    """
    for cle in ("statusMessage", "message", "reason", "details"):
        valeur = moteur.get(cle)
        if isinstance(valeur, str) and valeur.strip():
            return valeur.strip()
    for cle, valeur in moteur.items():
        if (
            isinstance(valeur, str)
            and valeur.strip()
            and any(mot in cle.lower() for mot in ("message", "reason", "cause", "why"))
        ):
            return valeur.strip()
    return None


def _selectionnable(moteur: dict[str, Any]) -> bool:
    if "isSelectable" in moteur:
        return bool(moteur["isSelectable"])
    return str(moteur.get("statusWarnLevel", "OK")).upper() != "ERROR"


def _analyser_moteurs(
    recette: Any,
    type_recette: str,
    params: dict[str, Any],
    cible: Optional[str],
    details: bool = False,
) -> dict[str, Any]:
    configure = params.get("engineType")
    resultat: dict[str, Any] = {
        "moteur_configure": configure.upper() if configure else "AUTO (choix de DSS)",
    }

    if type_recette in _MOTEUR_RECETTE_CODE:
        resultat["moteur_configure"] = "imposé par le type de recette"
        moteur = _MOTEUR_RECETTE_CODE[type_recette]
        resultat.update(
            moteur_selectionne=moteur,
            moteurs_disponibles=[],
            moteurs_indisponibles=[],
            note="Recette de code : moteur imposé par le type de recette",
        )
        if cible:
            possible = cible in moteur
            resultat["bascule"] = {
                "cible": cible,
                "possible": possible,
                "raison": (
                    "déjà sur ce moteur"
                    if possible
                    else "recette de code : changer de moteur = réécrire la "
                    f"recette (type {type_recette})"
                ),
            }
        return resultat

    statut = recette.get_status()
    if details:
        resultat["statut_brut"] = {
            k: statut.data.get(k) for k in ("selectedEngine", "engines") if k in statut.data
        }
    try:
        moteurs = statut.get_engines_details()
    except ValueError:
        moteurs = []
    try:
        detail_selectionne = statut.get_selected_engine_details()
        selectionne = _type_moteur(detail_selectionne)
    except ValueError:
        detail_selectionne, selectionne = {}, None

    disponibles, indisponibles, transferts = [], [], []
    for moteur in moteurs:
        if _transfert_rapide(_type_moteur(moteur)) and not _selectionnable(moteur):
            transferts.append(_type_moteur(moteur))
            continue
        entree = {
            "moteur": _type_moteur(moteur),
            "libelle": moteur.get("label"),
            "niveau": moteur.get("statusWarnLevel"),
        }
        if moteur.get("variantLabel") or moteur.get("variant"):
            entree["variante"] = moteur.get("variantLabel") or moteur.get("variant")
        if moteur.get("recommended"):
            entree["recommande"] = True
        message = _raison(moteur)
        # Le moteur sélectionné mais non sélectionnable est imposé (aucun
        # autre choix : plugins, recettes à moteur unique). Tout autre moteur
        # non sélectionnable est indisponible, même avec statusWarnLevel OK
        # (ex. "Not available with redispatch partitioning").
        impose = not moteur.get("isSelectable", True) and entree["moteur"] == selectionne
        if impose:
            entree["impose"] = True
        if _selectionnable(moteur) or impose:
            if message:
                entree["avertissement"] = message
            disponibles.append(entree)
        else:
            entree["raison"] = message or _SANS_RAISON
            indisponibles.append(entree)

    variante = detail_selectionne.get("variantLabel") or detail_selectionne.get("variant")
    if selectionne and variante:
        resultat["variante_selectionnee"] = variante
    resultat.update(
        moteur_selectionne=selectionne or "aucun moteur viable",
        moteurs_disponibles=disponibles,
        moteurs_indisponibles=indisponibles,
        transferts_rapides_non_applicables=transferts,
    )
    if type_recette.startswith("CustomCode_"):
        resultat["plugin"] = type_recette.split("_", 1)[1]
        resultat["note"] = (
            "Recette de plugin : le moteur est imposé par le plugin ; en changer "
            "suppose de remplacer le plugin"
        )
    elif not moteurs:
        resultat["note"] = "DSS ne propose pas de choix de moteur pour cette recette"
    elif disponibles and all(m.get("impose") for m in disponibles):
        resultat["note"] = "Moteur unique imposé : DSS ne propose pas d'alternative"

    if cible:
        resultat["bascule"] = _bascule(cible, selectionne, disponibles, indisponibles)
    return resultat


def _bascule(
    cible: str,
    selectionne: Optional[str],
    disponibles: list[dict[str, Any]],
    indisponibles: list[dict[str, Any]],
) -> dict[str, Any]:
    if selectionne == cible:
        return {"cible": cible, "possible": True, "raison": "déjà sur ce moteur"}
    dispo = next((m for m in disponibles if m["moteur"] == cible), None)
    if dispo:
        raison = "moteur proposé par DSS pour cette recette"
        if dispo.get("avertissement"):
            raison += f" (avertissement : {dispo['avertissement']})"
        return {"cible": cible, "possible": True, "raison": raison}
    bloque = next((m for m in indisponibles if m["moteur"] == cible), None)
    if bloque:
        return {"cible": cible, "possible": False, "raison": bloque["raison"]}
    return {
        "cible": cible,
        "possible": False,
        "raison": "moteur non proposé par DSS pour ce type de recette ou "
        "ces connexions d'entrée/sortie",
    }


def inventaire_moteurs(
    project_key: str,
    recipe_name: Optional[str] = None,
    moteur_cible: Optional[str] = None,
    details: bool = False,
) -> dict[str, Any]:
    """Moteurs actuels, disponibles et indisponibles des recettes d'un projet.

    Args:
        project_key: Le projet
        recipe_name: Une seule recette (sinon toutes)
        moteur_cible: Moteur à évaluer, ex. "SPARK" : pour chaque recette,
            indique si la bascule est possible et sinon pourquoi
        details: Ajouter le statut brut renvoyé par DSS (diagnostic)

    Returns:
        Détail par recette et synthèse ; rien n'est modifié dans DSS.
    """
    cible = moteur_cible.strip().upper() if moteur_cible else None

    try:
        projet = get_project(project_key)
        items = [_as_dict(r) for r in projet.list_recipes()]
    except Exception as e:
        return error(f"Impossible de lister les recettes de '{project_key}' : {e}")

    if recipe_name:
        items = [r for r in items if r.get("name") == recipe_name]
        if not items:
            return error(
                f"Recette '{recipe_name}' introuvable dans '{project_key}'",
                "not_found",
            )

    recettes, erreurs = [], []
    for numero, brut in enumerate(items, start=1):
        nom = brut.get("name")
        logger.info("Moteurs : recette %d/%d - %s", numero, len(items), nom)
        try:
            recette = projet.get_recipe(nom)
            settings = recette.get_settings()
            entree = {"recette": nom, "type": settings.type}
            entree.update(
                _analyser_moteurs(
                    recette, settings.type, settings.raw_params or {}, cible, details
                )
            )
            entree["recette_de_code"] = settings.type in CODE_RECIPE_TYPES
            recettes.append(entree)
        except Exception as e:
            erreurs.append({"recette": nom, "erreur": str(e)})

    synthese: dict[str, Any] = {
        "nb_recettes": len(recettes),
        "par_moteur_selectionne": dict(
            Counter(r["moteur_selectionne"] for r in recettes)
        ),
        "recettes_plugin": sorted(
            f"{r['recette']} ({r['plugin']})" for r in recettes if r.get("plugin")
        ),
        "moteurs_disponibles_au_moins_une_fois": sorted(
            {m["moteur"] for r in recettes for m in r["moteurs_disponibles"]}
        ),
    }
    if cible:
        bascules = [r for r in recettes if "bascule" in r]
        synthese["bascule_vers"] = {
            "cible": cible,
            "deja_sur_cible": sum(
                r["bascule"]["raison"] == "déjà sur ce moteur" for r in bascules
            ),
            "possibles": sorted(
                r["recette"]
                for r in bascules
                if r["bascule"]["possible"]
                and r["bascule"]["raison"] != "déjà sur ce moteur"
            ),
            "impossibles": [
                {"recette": r["recette"], "raison": r["bascule"]["raison"]}
                for r in bascules
                if not r["bascule"]["possible"]
            ],
        }

    resultat = ok(
        project_key=project_key,
        synthese=synthese,
        recettes=recettes,
        note=(
            "Lecture seule : statut calculé par DSS (comme à l'ouverture de "
            "la recette), aucune modification. 'Possible' signifie que DSS "
            "propose ce moteur : vérifier ensuite le résultat sur un run de test."
        ),
    )
    if erreurs:
        resultat["erreurs"] = erreurs
    return resultat
