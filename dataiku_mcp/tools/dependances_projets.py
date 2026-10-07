"""
Dépendances inter-projets Dataiku DSS.

Objectif : donner aux architectes une vision des liens entre projets avant
une migration (ex. Cloudera -> Databricks) :
- quel projet lit les données de quel autre projet ;
- quels projets forment des cycles (à migrer ensemble) ;
- dans quel ordre migrer (vagues).

Sources analysées (lecture seule) :
1. entrées des recettes référençant un autre projet ("PROJET.objet") ;
2. scénarios (déclencheurs, étapes de build, lancement de scénarios)
   pointant vers un autre projet ;
3. objets exposés (partages déclarés) dans les paramètres des projets.

Convention : un lien "fournisseur -> consommateur" signifie que le
consommateur utilise un objet du fournisseur. Le fournisseur doit donc
être migré avant (ou en même temps que) le consommateur.
"""

import logging
from collections import defaultdict
from typing import Any, Optional

from dataiku_mcp.client import get_project, list_projects
from dataiku_mcp.securite import filtrer_projets
from dataiku_mcp.tools.classification_dataset import _as_dict

logger = logging.getLogger(__name__)

# Nombre maximum d'objets listés par lien en mode compact.
_MAX_OBJETS_COMPACT = 10


def dependances_inter_projets(
    project_key: Optional[str] = None,
    inclure_scenarios: bool = True,
    details: bool = False,
) -> dict[str, Any]:
    """Analyse les dépendances entre les projets accessibles.

    Args:
        project_key: si fourni, le résultat est centré sur ce projet
            (amont, aval, vague) ; l'analyse porte quand même sur tous les
            projets, pour trouver ceux qui le consomment.
        inclure_scenarios: analyser aussi les scénarios (plus lent :
            un appel API par scénario).
        details: lister tous les objets de chaque lien et les partages
            déclarés non utilisés.
    """
    projets = sorted(filtrer_projets(list_projects()))
    connus = set(projets)

    # (fournisseur, consommateur) -> {objet: set(origines)}
    liens: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    partages: dict[tuple[str, str], set[str]] = defaultdict(set)
    erreurs: list[dict[str, str]] = []

    for cle in projets:
        try:
            projet = get_project(cle)
        except Exception as exc:
            erreurs.append({"projet": cle, "erreur": str(exc)})
            continue

        _analyser_recettes(projet, cle, liens, erreurs)
        if inclure_scenarios:
            _analyser_scenarios(projet, cle, liens, erreurs)
        _analyser_partages(projet, cle, partages, erreurs)

    graphe = _construire_graphe(projets, liens)
    cycles = _composantes_fortement_connexes(projets, graphe)
    vagues = _calculer_vagues(projets, graphe, cycles)

    resultat = _mettre_en_forme(
        projets, connus, liens, partages, cycles, vagues, erreurs, details
    )

    if project_key:
        return _centrer_sur_projet(project_key, resultat, graphe, vagues)

    return resultat


# ---------------------------------------------------------------------------
# Collecte
# ---------------------------------------------------------------------------
def _projet_externe(ref: Any, projet_courant: str) -> Optional[tuple[str, str]]:
    """Retourne (projet, objet) si la référence pointe vers un autre projet."""
    if not isinstance(ref, str) or "." not in ref:
        return None

    autre_projet, objet = ref.split(".", 1)
    if not autre_projet or not objet or autre_projet == projet_courant:
        return None

    return autre_projet, objet


def _refs_entrees_recette(projet: Any, brut: dict[str, Any]) -> list[str]:
    """Références des entrées d'une recette.

    La liste des recettes contient en général les entrées ; sinon on lit
    les paramètres de la recette (un appel API de plus).
    """
    entrees = brut.get("inputs")

    if isinstance(entrees, dict):
        refs = []
        for role in entrees.values():
            for item in (role or {}).get("items", []) or []:
                ref = (item or {}).get("ref")
                if ref:
                    refs.append(ref)
        return refs

    settings = projet.get_recipe(brut["name"]).get_settings()
    return [str(ref) for ref in settings.get_flat_input_refs()]


def _analyser_recettes(
    projet: Any,
    cle: str,
    liens: dict,
    erreurs: list[dict[str, str]],
) -> None:
    try:
        recettes = projet.list_recipes()
    except Exception as exc:
        erreurs.append({"projet": cle, "erreur": f"recettes : {exc}"})
        return

    for item in recettes:
        brut = _as_dict(item)
        nom = brut.get("name")
        if not nom:
            continue

        try:
            refs = _refs_entrees_recette(projet, brut)
        except Exception as exc:
            erreurs.append(
                {"projet": cle, "erreur": f"recette {nom} : {exc}"}
            )
            continue

        for ref in refs:
            externe = _projet_externe(ref, cle)
            if externe:
                fournisseur, objet = externe
                liens[(fournisseur, cle)][objet].add(f"recette:{nom}")


def _references_projets(valeur: Any, projet_courant: str) -> list[tuple[str, str]]:
    """Parcourt un JSON et retourne les (projectKey, objet) étrangers."""
    trouves: list[tuple[str, str]] = []

    if isinstance(valeur, dict):
        autre = valeur.get("projectKey")
        if isinstance(autre, str) and autre and autre != projet_courant:
            objet = (
                valeur.get("itemId")
                or valeur.get("scenarioId")
                or valeur.get("id")
                or valeur.get("name")
                or "?"
            )
            trouves.append((autre, str(objet)))
        for enfant in valeur.values():
            trouves.extend(_references_projets(enfant, projet_courant))

    elif isinstance(valeur, list):
        for enfant in valeur:
            trouves.extend(_references_projets(enfant, projet_courant))

    return trouves


def _analyser_scenarios(
    projet: Any,
    cle: str,
    liens: dict,
    erreurs: list[dict[str, str]],
) -> None:
    try:
        scenarios = projet.list_scenarios()
    except Exception as exc:
        erreurs.append({"projet": cle, "erreur": f"scénarios : {exc}"})
        return

    for item in scenarios:
        brut = _as_dict(item)
        scenario_id = brut.get("id")
        if not scenario_id:
            continue

        try:
            raw = projet.get_scenario(scenario_id).get_settings().get_raw()
        except Exception as exc:
            erreurs.append(
                {"projet": cle, "erreur": f"scénario {scenario_id} : {exc}"}
            )
            continue

        for fournisseur, objet in _references_projets(raw, cle):
            liens[(fournisseur, cle)][objet].add(f"scenario:{scenario_id}")


def _analyser_partages(
    projet: Any,
    cle: str,
    partages: dict[tuple[str, str], set[str]],
    erreurs: list[dict[str, str]],
) -> None:
    """Objets que ce projet expose (partage) à d'autres projets."""
    try:
        settings = projet.get_settings().get_raw()
    except Exception as exc:
        erreurs.append({"projet": cle, "erreur": f"partages : {exc}"})
        return

    exposes = (settings.get("exposedObjects") or {}).get("objects") or []

    for objet in exposes:
        nom = objet.get("localName")
        for regle in objet.get("rules") or []:
            cible = regle.get("targetProject")
            if nom and cible and cible != cle:
                partages[(cle, cible)].add(nom)


# ---------------------------------------------------------------------------
# Graphe : cycles et vagues
# ---------------------------------------------------------------------------
def _construire_graphe(
    projets: list[str], liens: dict
) -> dict[str, set[str]]:
    """Graphe fournisseur -> consommateurs, limité aux projets analysés."""
    connus = set(projets)
    graphe: dict[str, set[str]] = {p: set() for p in projets}

    for fournisseur, consommateur in liens:
        if fournisseur in connus and consommateur in connus:
            graphe[fournisseur].add(consommateur)

    return graphe


def _composantes_fortement_connexes(
    projets: list[str], graphe: dict[str, set[str]]
) -> list[list[str]]:
    """Algorithme de Tarjan (itératif). Retourne les cycles (taille > 1)."""
    index: dict[str, int] = {}
    bas: dict[str, int] = {}
    sur_pile: set[str] = set()
    pile: list[str] = []
    cycles: list[list[str]] = []
    compteur = 0

    for depart in projets:
        if depart in index:
            continue

        travail = [(depart, iter(sorted(graphe[depart])))]
        index[depart] = bas[depart] = compteur
        compteur += 1
        pile.append(depart)
        sur_pile.add(depart)

        while travail:
            noeud, voisins = travail[-1]
            avance = False

            for voisin in voisins:
                if voisin not in index:
                    index[voisin] = bas[voisin] = compteur
                    compteur += 1
                    pile.append(voisin)
                    sur_pile.add(voisin)
                    travail.append((voisin, iter(sorted(graphe[voisin]))))
                    avance = True
                    break
                if voisin in sur_pile:
                    bas[noeud] = min(bas[noeud], index[voisin])

            if avance:
                continue

            travail.pop()
            if travail:
                parent = travail[-1][0]
                bas[parent] = min(bas[parent], bas[noeud])

            if bas[noeud] == index[noeud]:
                composante = []
                while True:
                    membre = pile.pop()
                    sur_pile.discard(membre)
                    composante.append(membre)
                    if membre == noeud:
                        break
                if len(composante) > 1:
                    cycles.append(sorted(composante))

    return sorted(cycles)


def _calculer_vagues(
    projets: list[str],
    graphe: dict[str, set[str]],
    cycles: list[list[str]],
) -> dict[str, int]:
    """Numéro de vague par projet (1 = aucune dépendance amont).

    Les projets d'un même cycle sont regroupés et reçoivent la même vague.
    """
    groupe_de: dict[str, str] = {p: p for p in projets}
    for cycle in cycles:
        for membre in cycle:
            groupe_de[membre] = cycle[0]

    # Graphe des groupes (cycles condensés).
    predecesseurs: dict[str, set[str]] = defaultdict(set)
    groupes = set(groupe_de.values())
    for fournisseur, consommateurs in graphe.items():
        for consommateur in consommateurs:
            g_f, g_c = groupe_de[fournisseur], groupe_de[consommateur]
            if g_f != g_c:
                predecesseurs[g_c].add(g_f)

    vague_groupe: dict[str, int] = {}

    def vague(groupe: str) -> int:
        # Le graphe condensé est acyclique : la récursion termine.
        if groupe not in vague_groupe:
            amont = predecesseurs.get(groupe, set())
            vague_groupe[groupe] = 1 + max((vague(g) for g in amont), default=0)
        return vague_groupe[groupe]

    for groupe in sorted(groupes):
        vague(groupe)

    return {p: vague_groupe[groupe_de[p]] for p in projets}


# ---------------------------------------------------------------------------
# Mise en forme
# ---------------------------------------------------------------------------
def _mettre_en_forme(
    projets: list[str],
    connus: set[str],
    liens: dict,
    partages: dict[tuple[str, str], set[str]],
    cycles: list[list[str]],
    vagues: dict[str, int],
    erreurs: list[dict[str, str]],
    details: bool,
) -> dict[str, Any]:
    liste_liens = []
    externes: dict[str, set[str]] = defaultdict(set)

    for (fournisseur, consommateur), objets in sorted(liens.items()):
        noms = sorted(objets)
        origines = sorted({o.split(":", 1)[0] for s in objets.values() for o in s})
        lien: dict[str, Any] = {
            "fournisseur": fournisseur,
            "consommateur": consommateur,
            "nb_objets": len(noms),
            "objets": noms if details else noms[:_MAX_OBJETS_COMPACT],
            "via": origines,
        }
        if details:
            lien["usages"] = {
                objet: sorted(usages) for objet, usages in sorted(objets.items())
            }
        liste_liens.append(lien)

        if fournisseur not in connus:
            externes[fournisseur].add(consommateur)

    utilises = {(f, c) for f, c in liens}
    partages_inutilises = [
        {"fournisseur": f, "cible": c, "objets": sorted(objets)}
        for (f, c), objets in sorted(partages.items())
        if (f, c) not in utilises
    ]

    amont: dict[str, set[str]] = defaultdict(set)
    aval: dict[str, set[str]] = defaultdict(set)
    for fournisseur, consommateur in liens:
        amont[consommateur].add(fournisseur)
        aval[fournisseur].add(consommateur)

    isoles = [p for p in projets if not amont.get(p) and not aval.get(p)]

    par_vague: dict[int, list[str]] = defaultdict(list)
    for projet, numero in vagues.items():
        if projet not in isoles:
            par_vague[numero].append(projet)

    resultat: dict[str, Any] = {
        "statistiques": {
            "nb_projets_analyses": len(projets),
            "nb_liens": len(liste_liens),
            "nb_projets_isoles": len(isoles),
            "nb_cycles": len(cycles),
            "nb_vagues": max(par_vague, default=0),
        },
        "liens": liste_liens,
        "cycles": cycles,
        "vagues": [
            {"vague": numero, "projets": sorted(membres)}
            for numero, membres in sorted(par_vague.items())
        ],
        "projets_isoles": isoles,
        "projets_externes_ou_inaccessibles": {
            p: sorted(c) for p, c in sorted(externes.items())
        },
        "erreurs": erreurs,
        "note": (
            "Vague 1 = projets sans dépendance amont. Un projet doit être "
            "migré après (ou avec) ses fournisseurs. Les projets d'un cycle "
            "doivent être migrés ensemble. Les projets isolés peuvent être "
            "migrés à tout moment. Les accès faits dynamiquement dans le "
            "code (SQL, chemins HDFS) ne sont pas détectés."
        ),
    }

    if details:
        resultat["partages_declares_non_utilises"] = partages_inutilises
    else:
        resultat["statistiques"]["nb_partages_non_utilises"] = len(
            partages_inutilises
        )

    return resultat


def _centrer_sur_projet(
    project_key: str,
    resultat: dict[str, Any],
    graphe: dict[str, set[str]],
    vagues: dict[str, int],
) -> dict[str, Any]:
    """Vue d'un projet : fournisseurs, consommateurs, prérequis complets."""
    liens = resultat["liens"]
    fournisseurs = [l for l in liens if l["consommateur"] == project_key]
    consommateurs = [l for l in liens if l["fournisseur"] == project_key]

    # Tous les projets à migrer avant celui-ci (amont transitif).
    predecesseurs: dict[str, set[str]] = defaultdict(set)
    for fournisseur, cibles in graphe.items():
        for cible in cibles:
            predecesseurs[cible].add(fournisseur)

    prerequis: set[str] = set()
    a_visiter = list(predecesseurs.get(project_key, set()))
    while a_visiter:
        courant = a_visiter.pop()
        if courant in prerequis or courant == project_key:
            continue
        prerequis.add(courant)
        a_visiter.extend(predecesseurs.get(courant, set()))

    cycle = next((c for c in resultat["cycles"] if project_key in c), None)
    # Les membres du même cycle se migrent ensemble : pas des prérequis.
    prerequis -= set(cycle or [])

    return {
        "projet": project_key,
        "vague": vagues.get(project_key),
        "depend_de": fournisseurs,
        "utilise_par": consommateurs,
        "prerequis_migration": sorted(prerequis),
        "cycle": cycle,
        "erreurs": resultat["erreurs"],
        "note": resultat["note"],
    }


def generer_mermaid(resultat: dict[str, Any]) -> str:
    """Graphe Mermaid (affiché nativement par GitLab) des dépendances."""
    lignes = ["graph LR"]
    for lien in resultat.get("liens", []):
        lignes.append(
            f'    {lien["fournisseur"]} -->|{lien["nb_objets"]}| '
            f'{lien["consommateur"]}'
        )
    return "\n".join(lignes)
