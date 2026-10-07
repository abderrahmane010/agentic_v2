"""
Inventaire technique avant migration Cloudera -> Databricks.

Pour un projet (ou toute l'instance), en lecture seule :
- stockage : datasets par technologie, format, partitionnement ;
- recettes : moteur d'exécution (Hive, Impala, Spark...), code envs,
  configurations Spark, plugins ;
- adhérences Cloudera repérées dans le code des recettes et des scénarios
  (chemins HDFS, Kerberos, Knox, SQL spécifique Hive...) ;
- score de complexité indicatif (Simple / Moyen / Complexe) et ses raisons.

Le scan du code repère des motifs textuels : c'est une liste de points à
vérifier, pas un verdict. Le score sert à comparer et prioriser les
projets, pas à chiffrer une charge.
"""

import logging
import re
from collections import Counter, defaultdict
from typing import Any, Optional

from dataiku_mcp.client import get_project, list_projects
from dataiku_mcp.securite import filtrer_projets
from dataiku_mcp.tools.classification_dataset import _as_dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Référentiels
# ---------------------------------------------------------------------------
# Moteur des recettes de code, déduit du type de recette.
_MOTEUR_PAR_TYPE = {
    "hive": "HIVE",
    "impala": "IMPALA",
    "pyspark": "SPARK",
    "spark_scala": "SPARK",
    "sparkr": "SPARK",
    "spark_sql_query": "SPARK",
    "python": "PYTHON",
    "r": "R",
    "sql_query": "SQL",
    "sql_script": "SQL",
    "shell": "SHELL",
    "julia": "JULIA",
}

_TYPES_CODE = set(_MOTEUR_PAR_TYPE)

_SQL = (
    "postgresql", "oracle", "teradata", "sqlserver", "mysql", "snowflake",
    "vertica", "greenplum", "redshift", "bigquery", "synapse", "jdbc",
    "db2", "sybase", "netezza", "exasol", "saphana",
)

# (identifiant, libellé, gravité, regex, conseil)
_MOTIFS_CODE = [
    ("hdfs_uri", "Chemin hdfs:// en dur", "haute",
     r"hdfs://", "Remplacer par un chemin cloud / table Unity Catalog"),
    ("chemin_hdfs", "Chemin HDFS absolu", "moyenne",
     r"(?<![\w/])/(?:user|apps/hive|warehouse|tmp/hive)/[\w./-]+",
     "Remplacer par un volume ou une table Unity Catalog"),
    ("commande_hadoop", "Commande hadoop/hdfs", "haute",
     r"\b(?:hadoop\s+fs|hdfs\s+dfs)\b", "Utiliser dbutils.fs ou les volumes"),
    ("kerberos", "Kerberos (kinit/keytab)", "haute",
     r"\bkinit\b|keytab|kerberos", "Authentification à revoir (pas de Kerberos)"),
    ("knox", "Passerelle Knox", "haute",
     r"\bknox\b", "API Cloudera : trouver l'équivalent Databricks"),
    ("impala", "Impala", "haute",
     r"\bimpala\b|impyla", "Réécrire en Spark SQL / Databricks SQL"),
    ("jdbc_hive", "Connexion JDBC/ODBC Hive", "haute",
     r"jdbc:hive2|\bpyhive\b|jaydebeapi", "Utiliser une connexion Databricks"),
    ("hive_context", "API HiveContext / enableHiveSupport", "moyenne",
     r"HiveContext|enableHiveSupport", "Utiliser SparkSession (Unity Catalog)"),
    ("ddl_hive", "DDL Hive (STORED AS, ROW FORMAT...)", "moyenne",
     r"STORED\s+AS\s+\w+|ROW\s+FORMAT|TBLPROPERTIES", "Convertir en tables Delta"),
    ("insert_overwrite", "INSERT OVERWRITE", "moyenne",
     r"INSERT\s+OVERWRITE", "Vérifier la sémantique (Delta : replaceWhere)"),
    ("msck", "MSCK REPAIR / gestion de partitions Hive", "moyenne",
     r"MSCK\s+REPAIR|ADD\s+PARTITION|DROP\s+PARTITION",
     "Inutile avec Delta : à supprimer ou adapter"),
    ("yarn", "Configuration YARN / executors", "moyenne",
     r"spark\.yarn\.|spark\.executor\.|--num-executors|\byarn\b",
     "Dimensionnement à refaire sur clusters Databricks"),
    ("rdd", "API RDD / SparkContext", "moyenne",
     r"\.rdd\b|sc\.parallelize|SparkContext\(",
     "Non supporté sur clusters partagés Unity Catalog"),
    ("appel_systeme", "Appel système (subprocess, os.system)", "moyenne",
     r"\bsubprocess\b|os\.system\(", "Vérifier les commandes appelées"),
    ("tri_hive", "DISTRIBUTE BY / CLUSTER BY / SORT BY", "basse",
     r"\b(?:DISTRIBUTE|CLUSTER|SORT)\s+BY\b", "Supporté en Spark SQL : à vérifier"),
    ("tls_off", "Vérification TLS désactivée (verify=False)", "basse",
     r"verify\s*=\s*False", "Sécurité : fournir le certificat"),
    ("secret_en_dur", "Identifiant ou secret en dur", "haute",
     r"(?:password|passwd|pwd|secret|token|api_key)\s*=\s*['\"][^'\"]{3,}['\"]",
     "Sécurité : utiliser des secrets (DSS / Databricks)"),
]

_MOTIFS_COMPILES = [
    (ident, libelle, gravite, re.compile(regex, re.IGNORECASE), conseil)
    for ident, libelle, gravite, regex, conseil in _MOTIFS_CODE
]

# Points du score de complexité.
_POINTS_GRAVITE = {"haute": 3, "moyenne": 1, "basse": 0}
_POINTS_MOTEUR = {"HIVE": 3, "IMPALA": 3, "SHELL": 2, "SPARK": 1}
_SEUIL_MOYEN = 10
_SEUIL_COMPLEXE = 30

_MAX_COMPACT = 15


# ---------------------------------------------------------------------------
# Outils publics
# ---------------------------------------------------------------------------
def inventaire_technique_migration(
    project_key: Optional[str] = None,
    analyser_code: bool = True,
    details: bool = False,
) -> dict[str, Any]:
    """Inventaire technique d'un projet, ou synthèse de toute l'instance."""
    if project_key:
        resultat = inventaire_projet(project_key.strip(), analyser_code)
        return resultat if details else _compacter_projet(resultat)

    return inventaire_instance(analyser_code)


def inventaire_projet(project_key: str, analyser_code: bool = True) -> dict[str, Any]:
    """Inventaire technique complet d'un projet."""
    projet = get_project(project_key)
    erreurs: list[dict[str, str]] = []

    stockage = _inventaire_stockage(projet, erreurs)
    recettes = _inventaire_recettes(projet, analyser_code, erreurs)
    scenarios = _inventaire_scenarios(projet, analyser_code, erreurs)
    autres = _inventaire_autres_objets(projet)

    adherences = _regrouper_adherences(
        recettes["detail"] + scenarios["detail"]
    )
    score = _calculer_score(stockage, recettes, scenarios, adherences, autres)

    return {
        "projet": project_key,
        "complexite": score["niveau"],
        "score": score["points"],
        "raisons": score["raisons"],
        "stockage": stockage,
        "recettes": recettes,
        "scenarios": scenarios,
        "autres_objets": autres,
        "adherences_cloudera": adherences,
        "code_analyse": analyser_code,
        "erreurs": erreurs,
        "note": (
            "Le scan du code repère des motifs textuels : liste de points à "
            "vérifier, pas un verdict. Le score est indicatif et sert à "
            "comparer les projets entre eux."
        ),
    }


def inventaire_instance(analyser_code: bool = True) -> dict[str, Any]:
    """Synthèse par projet pour toute l'instance (projets autorisés)."""
    projets = sorted(filtrer_projets(list_projects()))
    lignes: list[dict[str, Any]] = []
    erreurs: list[dict[str, str]] = []
    totaux: Counter = Counter()

    for numero, cle in enumerate(projets, start=1):
        logger.info("Inventaire : projet %d/%d - %s", numero, len(projets), cle)
        try:
            inv = inventaire_projet(cle, analyser_code)
        except Exception as exc:
            erreurs.append({"projet": cle, "erreur": str(exc)})
            continue

        moteurs = inv["recettes"]["par_moteur"]
        categories = inv["stockage"]["par_categorie"]
        nb_adherences = sum(a["occurrences"] for a in inv["adherences_cloudera"])

        lignes.append(
            {
                "projet": cle,
                "complexite": inv["complexite"],
                "score": inv["score"],
                "nb_datasets": inv["stockage"]["total"],
                "datasets_hdfs_hive": categories.get("HDFS", 0)
                + categories.get("Hive", 0),
                "nb_recettes": inv["recettes"]["total"],
                "recettes_hive_impala": moteurs.get("HIVE", 0)
                + moteurs.get("IMPALA", 0),
                "recettes_spark": moteurs.get("SPARK", 0),
                "plugins": len(inv["recettes"]["plugins"]),
                "adherences_code": nb_adherences,
                "raisons": inv["raisons"][:3],
            }
        )
        totaux.update(categories)
        totaux.update({f"moteur_{m}": n for m, n in moteurs.items()})
        erreurs.extend(inv["erreurs"])

    lignes.sort(key=lambda l: l["score"], reverse=True)
    niveaux = Counter(l["complexite"] for l in lignes)

    return {
        "statistiques": {
            "nb_projets": len(lignes),
            "simples": niveaux.get("Simple", 0),
            "moyens": niveaux.get("Moyen", 0),
            "complexes": niveaux.get("Complexe", 0),
        },
        "totaux": dict(sorted(totaux.items())),
        "projets": lignes,
        "erreurs": erreurs,
        "note": (
            "Projets triés du plus complexe au plus simple. Score indicatif "
            "(Simple < 10 <= Moyen < 30 <= Complexe)."
        ),
    }


# ---------------------------------------------------------------------------
# Stockage
# ---------------------------------------------------------------------------
def categorie_stockage(type_dataset: Optional[str]) -> str:
    """Famille technique d'un type de dataset DSS."""
    t = (type_dataset or "").lower()
    if "databricks" in t:
        return "Databricks"
    if "hive" in t:
        return "Hive"
    if "impala" in t:
        return "Impala"
    if "hdfs" in t:
        return "HDFS"
    if any(s in t for s in _SQL):
        return "SQL"
    if t in ("s3", "gcs", "azure") or t.startswith(("s3", "gcs", "azure")):
        return "Cloud"
    if t in ("filesystem", "uploadedfiles", "ftp", "sftp", "scp", "http"):
        return "Fichiers"
    if t == "inline":
        return "Inline"
    if t.startswith("custom"):
        return "Plugin"
    return "Autre"


def _inventaire_stockage(projet: Any, erreurs: list) -> dict[str, Any]:
    try:
        items = projet.list_datasets()
    except Exception as exc:
        erreurs.append({"projet": projet.project_key, "erreur": f"datasets : {exc}"})
        items = []

    detail = []
    for item in items:
        brut = _as_dict(item)
        params = brut.get("params") or {}
        dimensions = (brut.get("partitioning") or {}).get("dimensions") or []
        detail.append(
            {
                "nom": brut.get("name"),
                "type": brut.get("type"),
                "categorie": categorie_stockage(brut.get("type")),
                "connexion": params.get("connection"),
                "format": brut.get("formatType"),
                "partitionne": bool(dimensions),
                "gere": bool(brut.get("managed")),
            }
        )

    return {
        "total": len(detail),
        "par_categorie": dict(Counter(d["categorie"] for d in detail)),
        "par_type": dict(Counter(str(d["type"]) for d in detail)),
        "par_format": dict(Counter(d["format"] for d in detail if d["format"])),
        "par_connexion": dict(
            Counter(d["connexion"] for d in detail if d["connexion"])
        ),
        "nb_partitionnes": sum(d["partitionne"] for d in detail),
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Recettes
# ---------------------------------------------------------------------------
def _moteur(type_recette: str, params: dict[str, Any]) -> str:
    if type_recette in _MOTEUR_PAR_TYPE:
        return _MOTEUR_PAR_TYPE[type_recette]
    if type_recette.startswith("CustomCode_"):
        return "PLUGIN"
    moteur = (params or {}).get("engineType")
    return str(moteur).upper() if moteur else "DSS"


def scanner_code(code: str) -> list[dict[str, Any]]:
    """Repère les adhérences Cloudera dans un texte de code."""
    trouves = []
    for ident, libelle, gravite, regex, conseil in _MOTIFS_COMPILES:
        correspondances = list(regex.finditer(code or ""))
        if not correspondances:
            continue

        debut = correspondances[0].start()
        ligne = code[code.rfind("\n", 0, debut) + 1:].split("\n", 1)[0].strip()
        if ident == "secret_en_dur":
            ligne = "(masqué)"

        trouves.append(
            {
                "motif": ident,
                "libelle": libelle,
                "gravite": gravite,
                "occurrences": len(correspondances),
                "exemple": ligne[:120],
                "conseil": conseil,
            }
        )
    return trouves


def _inventaire_recettes(
    projet: Any, analyser_code: bool, erreurs: list
) -> dict[str, Any]:
    try:
        items = projet.list_recipes()
    except Exception as exc:
        erreurs.append({"projet": projet.project_key, "erreur": f"recettes : {exc}"})
        items = []

    detail = []
    code_envs: Counter = Counter()
    configs_spark: Counter = Counter()

    for item in items:
        brut = _as_dict(item)
        nom = brut.get("name")
        type_recette = str(brut.get("type") or "")
        if not nom:
            continue

        params: dict[str, Any] = brut.get("params") or {}
        adherences: list[dict[str, Any]] = []

        if analyser_code:
            try:
                settings = projet.get_recipe(nom).get_settings()
                params = settings.get_recipe_params() or {}
                type_recette = settings.type or type_recette
                if type_recette in _TYPES_CODE or type_recette.startswith("Custom"):
                    adherences = scanner_code(settings.str_payload or "")
            except Exception as exc:
                erreurs.append(
                    {"projet": projet.project_key, "erreur": f"recette {nom} : {exc}"}
                )

        env = (params.get("envSelection") or {})
        if env.get("envName"):
            code_envs[env["envName"]] += 1

        spark = params.get("sparkConfig") or {}
        if spark.get("inheritConf"):
            configs_spark[spark["inheritConf"]] += 1

        detail.append(
            {
                "objet": f"recette:{nom}",
                "type": type_recette,
                "moteur": _moteur(type_recette, params),
                "adherences": adherences,
            }
        )

    return {
        "total": len(detail),
        "par_moteur": dict(Counter(d["moteur"] for d in detail)),
        "par_type": dict(Counter(d["type"] for d in detail)),
        "code_envs": dict(code_envs),
        "configs_spark": dict(configs_spark),
        "plugins": sorted(
            {d["type"] for d in detail if d["type"].startswith("CustomCode_")}
        ),
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Scénarios
# ---------------------------------------------------------------------------
def _textes_code(valeur: Any) -> list[str]:
    """Extrait les scripts (clés script/code/sql) d'un JSON de scénario."""
    textes: list[str] = []
    if isinstance(valeur, dict):
        for cle, enfant in valeur.items():
            if cle in ("script", "code", "sql", "customScript") and isinstance(enfant, str):
                textes.append(enfant)
            else:
                textes.extend(_textes_code(enfant))
    elif isinstance(valeur, list):
        for enfant in valeur:
            textes.extend(_textes_code(enfant))
    return textes


def _inventaire_scenarios(
    projet: Any, analyser_code: bool, erreurs: list
) -> dict[str, Any]:
    try:
        items = projet.list_scenarios()
    except Exception as exc:
        erreurs.append({"projet": projet.project_key, "erreur": f"scénarios : {exc}"})
        items = []

    detail = []
    for item in items:
        brut = _as_dict(item)
        scenario_id = brut.get("id")
        if not scenario_id:
            continue

        adherences: list[dict[str, Any]] = []
        avec_code = brut.get("type") == "custom_python"

        if analyser_code:
            try:
                raw = projet.get_scenario(scenario_id).get_settings().get_raw()
                textes = _textes_code(raw)
                avec_code = avec_code or bool(textes)
                adherences = scanner_code("\n".join(textes))
            except Exception as exc:
                erreurs.append(
                    {"projet": projet.project_key,
                     "erreur": f"scénario {scenario_id} : {exc}"}
                )

        detail.append(
            {
                "objet": f"scenario:{scenario_id}",
                "type": brut.get("type"),
                "actif": bool(brut.get("active")),
                "avec_code": avec_code,
                "adherences": adherences,
            }
        )

    return {
        "total": len(detail),
        "actifs": sum(d["actif"] for d in detail),
        "avec_code": sum(d["avec_code"] for d in detail),
        "detail": detail,
    }


def _inventaire_autres_objets(projet: Any) -> dict[str, int]:
    resultat = {}
    for methode, libelle in (
        ("list_saved_models", "modeles_ml"),
        ("list_managed_folders", "dossiers_geres"),
    ):
        try:
            resultat[libelle] = len(getattr(projet, methode)() or [])
        except Exception:
            resultat[libelle] = 0
    return resultat


# ---------------------------------------------------------------------------
# Synthèse
# ---------------------------------------------------------------------------
def _regrouper_adherences(objets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Regroupe les adhérences par motif, avec la liste des objets touchés."""
    groupes: dict[str, dict[str, Any]] = {}
    for objet in objets:
        for adh in objet["adherences"]:
            groupe = groupes.setdefault(
                adh["motif"],
                {
                    "motif": adh["motif"],
                    "libelle": adh["libelle"],
                    "gravite": adh["gravite"],
                    "conseil": adh["conseil"],
                    "occurrences": 0,
                    "objets": [],
                    "exemple": adh["exemple"],
                },
            )
            groupe["occurrences"] += adh["occurrences"]
            groupe["objets"].append(objet["objet"])

    ordre = {"haute": 0, "moyenne": 1, "basse": 2}
    return sorted(
        groupes.values(), key=lambda g: (ordre[g["gravite"]], -g["occurrences"])
    )


def _calculer_score(
    stockage: dict, recettes: dict, scenarios: dict, adherences: list, autres: dict
) -> dict[str, Any]:
    points = 0
    raisons = []

    for moteur, valeur in _POINTS_MOTEUR.items():
        nombre = recettes["par_moteur"].get(moteur, 0)
        if nombre:
            points += nombre * valeur
            raisons.append(f"{nombre} recette(s) {moteur}")

    for adh in adherences:
        nb_objets = len(adh["objets"])
        gain = nb_objets * _POINTS_GRAVITE[adh["gravite"]]
        if gain:
            points += gain
            raisons.append(f"{adh['libelle']} dans {nb_objets} objet(s)")

    if recettes["plugins"]:
        points += 2 * len(recettes["plugins"])
        raisons.append(f"{len(recettes['plugins'])} plugin(s) de recette")

    hdfs = stockage["par_categorie"].get("HDFS", 0) + stockage["par_categorie"].get("Hive", 0)
    if hdfs:
        points += hdfs // 10
        raisons.append(f"{hdfs} dataset(s) HDFS/Hive à migrer")

    if stockage["nb_partitionnes"]:
        points += stockage["nb_partitionnes"] // 5
        raisons.append(f"{stockage['nb_partitionnes']} dataset(s) partitionné(s)")

    if scenarios["avec_code"]:
        points += scenarios["avec_code"]
        raisons.append(f"{scenarios['avec_code']} scénario(s) avec code")

    if autres.get("modeles_ml"):
        points += autres["modeles_ml"]
        raisons.append(f"{autres['modeles_ml']} modèle(s) ML")

    if points >= _SEUIL_COMPLEXE:
        niveau = "Complexe"
    elif points >= _SEUIL_MOYEN:
        niveau = "Moyen"
    else:
        niveau = "Simple"

    return {"points": points, "niveau": niveau, "raisons": raisons}


def _compacter_projet(resultat: dict[str, Any]) -> dict[str, Any]:
    """Version courte pour le LLM : sans le détail par objet."""
    compact = {k: v for k, v in resultat.items() if k not in ("stockage", "recettes", "scenarios")}
    compact["stockage"] = {
        k: v for k, v in resultat["stockage"].items() if k != "detail"
    }
    compact["recettes"] = {
        k: v for k, v in resultat["recettes"].items() if k != "detail"
    }
    compact["scenarios"] = {
        k: v for k, v in resultat["scenarios"].items() if k != "detail"
    }
    compact["adherences_cloudera"] = [
        {**a, "objets": a["objets"][:_MAX_COMPACT], "nb_objets": len(a["objets"])}
        for a in resultat["adherences_cloudera"]
    ]
    return compact
