"""
Liens entre projets que DSS ne déclare pas.

Deux sources, utilisées par dependances_projets :

1. Stockage physique : deux datasets de projets différents qui pointent vers
   le même emplacement (connexion + table, ou connexion + chemin). Si l'un
   des projets écrit cet emplacement (le dataset est la sortie d'une de ses
   recettes), les projets qui le lisent en dépendent.
2. Code des recettes : références à un dataset d'un autre projet
   (dataiku.Dataset("PROJET.nom")), tables SQL "schema.table" ou chemins
   HDFS écrits par un autre projet.

Ces liens restent des présomptions : deux connexions différentes peuvent
viser le même stockage, et du code peut construire des noms dynamiquement.
"""

import re
from collections import defaultdict
from typing import Any, Optional

# (projet, dataset)
Ref = tuple[str, str]

_VARIABLE_PROJET = re.compile(r"\$\{projectKey\}", re.IGNORECASE)

# dataiku.Dataset("PROJET.nom"), dataiku.Folder('PROJET.id')
_REF_DATAIKU = re.compile(
    r"""\b(?:Dataset|Folder)\(\s*[rRuUbB]?["']([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)["']"""
)
# FROM schema.table, JOIN `db`.`t`, INSERT INTO db.t, TABLE db.t, UPDATE db.t
_REF_SQL = re.compile(
    r"""\b(?:from|join|into|table|update)\s+[`"\[]?([A-Za-z_][\w$]*)[`"\]]?"""
    r"""\s*\.\s*[`"\[]?([A-Za-z_][\w$]*)""",
    re.IGNORECASE,
)
# spark.table("db.t"), spark.read.table('db.t'), saveAsTable("db.t")
_REF_SPARK = re.compile(
    r"""\b(?:table|saveAsTable|insertInto)\(\s*["']([A-Za-z_][\w$]*)\.([A-Za-z_][\w$]*)["']"""
)
# Chemins entre guillemets : "hdfs://nn/data/x", '/data/x/y'
_REF_CHEMIN = re.compile(r"""["'](?:[a-z0-9]+://[^/"'\s]*)?(/[^"'\s]+)["']""")


def _resoudre(valeur: Any, projet: str) -> Optional[str]:
    """Remplace ${projectKey} ; None si vide ou autre variable non résolue."""
    if not isinstance(valeur, str) or not valeur.strip():
        return None
    valeur = _VARIABLE_PROJET.sub(projet, valeur.strip())
    return None if "${" in valeur else valeur


def _normaliser_chemin(chemin: str) -> str:
    chemin = re.sub(r"/+", "/", "/" + chemin.strip()).rstrip("/")
    return chemin.lower()


def emplacement(projet: str, dataset: dict[str, Any]) -> Optional[str]:
    """Clé de l'emplacement physique d'un dataset, ou None si inconnu.

    - table : "table:connexion|catalogue.schema.table"
    - fichier : "chemin:connexion|/chemin"
    """
    params = dataset.get("params") or {}
    connexion = params.get("connection")
    if not connexion:
        return None

    table = _resoudre(params.get("table"), projet)
    if table:
        parties = [
            _resoudre(params.get("catalog"), projet),
            _resoudre(params.get("schema") or params.get("database"), projet),
            table,
        ]
        return f"table:{connexion}|{'.'.join(p for p in parties if p)}".lower()

    chemin = _resoudre(params.get("path"), projet)
    if chemin and chemin.strip("/"):
        return f"chemin:{connexion.lower()}|{_normaliser_chemin(chemin)}"

    return None


def liens_stockage(
    catalogue: dict[str, dict[str, Any]],
) -> tuple[list[tuple[str, str, str, str]], dict[str, list[dict[str, Any]]]]:
    """Liens issus d'emplacements physiques partagés entre projets.

    Args:
        catalogue: {projet: {"datasets": {nom: def}, "ecrits": set(noms)}}

    Returns:
        (liens, constats) avec liens = [(fournisseur, dataset_fournisseur,
        consommateur, dataset_consommateur)] et constats = {
        "ecritures_multiples": [...], "sources_externes_partagees": [...]}.
    """
    par_emplacement: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)
    for projet, infos in catalogue.items():
        for nom, definition in infos["datasets"].items():
            cle = emplacement(projet, definition)
            if cle:
                par_emplacement[cle].append((projet, nom, nom in infos["ecrits"]))

    liens = []
    constats: dict[str, list[dict[str, Any]]] = {
        "ecritures_multiples": [],
        "sources_externes_partagees": [],
    }

    for cle, entrees in sorted(par_emplacement.items()):
        projets = {p for p, _, _ in entrees}
        if len(projets) < 2:
            continue

        ecrivains = sorted({(p, n) for p, n, ecrit in entrees if ecrit})
        lecteurs = sorted({(p, n) for p, n, ecrit in entrees if not ecrit})
        description = {
            "emplacement": cle,
            "datasets": [f"{p}.{n}" for p, n, _ in sorted(entrees)],
        }

        if not ecrivains:
            constats["sources_externes_partagees"].append(description)
            continue

        if len({p for p, _ in ecrivains}) > 1:
            constats["ecritures_multiples"].append(
                {**description, "ecrivains": [f"{p}.{n}" for p, n in ecrivains]}
            )

        for projet_e, nom_e in ecrivains:
            for projet_l, nom_l in lecteurs:
                if projet_l != projet_e:
                    liens.append((projet_e, nom_e, projet_l, nom_l))

    return liens, constats


def _index_tables_ecrites(
    catalogue: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[Ref]], dict[str, list[Ref]]]:
    """Tables SQL ("schema.table") et chemins écrits par chaque projet."""
    tables: dict[str, list[Ref]] = defaultdict(list)
    chemins: dict[str, list[Ref]] = defaultdict(list)

    for projet, infos in catalogue.items():
        for nom in infos["ecrits"]:
            params = (infos["datasets"].get(nom) or {}).get("params") or {}
            table = _resoudre(params.get("table"), projet)
            schema = _resoudre(params.get("schema") or params.get("database"), projet)
            if table and schema:
                tables[f"{schema}.{table}".lower()].append((projet, nom))
            chemin = _resoudre(params.get("path"), projet)
            # Au moins 2 segments, pour limiter les faux positifs.
            if chemin and len(_normaliser_chemin(chemin).strip("/").split("/")) >= 2:
                chemins[_normaliser_chemin(chemin)].append((projet, nom))

    return tables, chemins


def liens_code(
    catalogue: dict[str, dict[str, Any]],
    projets_connus: set[str],
) -> list[tuple[str, str, str, str]]:
    """Liens trouvés dans le code des recettes.

    Args:
        catalogue: {projet: {..., "codes": {recette: code}}}
        projets_connus: projets analysés (pour reconnaître "PROJET.nom")

    Returns:
        [(fournisseur, objet_fournisseur, consommateur, recette)]
    """
    tables, chemins = _index_tables_ecrites(catalogue)
    liens: set[tuple[str, str, str, str]] = set()

    for consommateur, infos in catalogue.items():
        for recette, code in (infos.get("codes") or {}).items():
            if not code:
                continue

            for projet, objet in _REF_DATAIKU.findall(code):
                if projet != consommateur and projet in projets_connus:
                    liens.add((projet, objet, consommateur, recette))

            references = {
                f"{a}.{b}".lower()
                for a, b in _REF_SQL.findall(code) + _REF_SPARK.findall(code)
            }
            for reference in references:
                for projet, nom in tables.get(reference, []):
                    if projet != consommateur:
                        liens.add((projet, nom, consommateur, recette))

            for chemin_code in {_normaliser_chemin(c) for c in _REF_CHEMIN.findall(code)}:
                for chemin, refs in chemins.items():
                    # Chemin du dataset contenu dans celui du code, aligné
                    # sur les "/" (racine de connexion inconnue).
                    if chemin + "/" in chemin_code + "/":
                        for projet, nom in refs:
                            if projet != consommateur:
                                liens.add((projet, nom, consommateur, recette))

    return sorted(liens)
