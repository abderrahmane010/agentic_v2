"""
Rapports Markdown / CSV de l'inventaire technique de migration.

Les CSV utilisent le séparateur ";" et l'encodage UTF-8 avec BOM pour
s'ouvrir correctement dans Excel (paramètres régionaux français).
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

_ICONES = {"haute": "🔴", "moyenne": "🟠", "basse": "🟡"}


def _ecrire_csv(chemin: Path, entetes: list[str], lignes: list[list[Any]]) -> None:
    with chemin.open("w", newline="", encoding="utf-8-sig") as fichier:
        writer = csv.writer(fichier, delimiter=";")
        writer.writerow(entetes)
        writer.writerows(lignes)


def _compteurs(titre: str, valeurs: dict[str, int]) -> list[str]:
    if not valeurs:
        return []
    lignes = [f"**{titre}** : " + ", ".join(
        f"{cle} ({nombre})"
        for cle, nombre in sorted(valeurs.items(), key=lambda kv: -kv[1])
    ), ""]
    return lignes


def rapport_projet(inv: dict[str, Any], dossier: Path) -> list[Path]:
    """Écrit le rapport d'un projet (Markdown + CSV des recettes)."""
    dossier.mkdir(parents=True, exist_ok=True)
    horodatage = f"{datetime.now():%Y%m%d_%H%M}"
    base = dossier / f"inventaire_{inv['projet']}_{horodatage}"

    stockage, recettes, scenarios = inv["stockage"], inv["recettes"], inv["scenarios"]
    md = [
        f"# Inventaire technique de migration — {inv['projet']}",
        "",
        f"Généré le {datetime.now():%d/%m/%Y %H:%M}.",
        "",
        f"## Complexité : **{inv['complexite']}** (score {inv['score']})",
        "",
    ]
    md += [f"- {raison}" for raison in inv["raisons"]] or ["- Aucun point bloquant détecté"]

    md += ["", f"## Stockage ({stockage['total']} datasets)", ""]
    md += _compteurs("Par technologie", stockage["par_categorie"])
    md += _compteurs("Par format", stockage["par_format"])
    md += _compteurs("Par connexion", stockage["par_connexion"])
    md += [f"Datasets partitionnés : {stockage['nb_partitionnes']}", ""]

    md += [f"## Recettes ({recettes['total']})", ""]
    md += _compteurs("Par moteur", recettes["par_moteur"])
    md += _compteurs("Par type", recettes["par_type"])
    md += _compteurs("Environnements de code", recettes["code_envs"])
    md += _compteurs("Configurations Spark", recettes["configs_spark"])
    if recettes["plugins"]:
        md += [f"**Plugins** : {', '.join(recettes['plugins'])}", ""]

    md += [
        f"## Scénarios ({scenarios['total']})",
        "",
        f"Actifs : {scenarios['actifs']} — avec code Python : {scenarios['avec_code']}",
        "",
        "## Adhérences Cloudera détectées dans le code",
        "",
    ]
    if inv["adherences_cloudera"]:
        md += [
            "| Gravité | Motif | Occurrences | Objets | Conseil |",
            "|---|---|---|---|---|",
        ]
        for adh in inv["adherences_cloudera"]:
            md.append(
                f"| {_ICONES[adh['gravite']]} {adh['gravite']} | {adh['libelle']} | "
                f"{adh['occurrences']} | {', '.join(adh['objets'])} | {adh['conseil']} |"
            )
    elif inv.get("code_analyse"):
        md.append("Aucune adhérence détectée.")
    else:
        md.append("Code non analysé (analyser_code=False).")

    if inv["erreurs"]:
        md += ["", "## Erreurs de lecture", ""]
        md += [f"- {e['projet']} : {e['erreur']}" for e in inv["erreurs"]]

    md += ["", f"> {inv['note']}", ""]

    chemin_md = base.with_suffix(".md")
    chemin_md.write_text("\n".join(md), encoding="utf-8")

    chemin_csv = Path(f"{base}_objets.csv")
    lignes = []
    for objet in recettes["detail"] + scenarios["detail"]:
        motifs = objet["adherences"]
        lignes.append([
            objet["objet"],
            objet.get("type"),
            objet.get("moteur", ""),
            len(motifs),
            ", ".join(f"{m['libelle']} ({m['occurrences']})" for m in motifs),
        ])
    _ecrire_csv(
        chemin_csv,
        ["Objet", "Type", "Moteur", "Nb motifs", "Adhérences détectées"],
        lignes,
    )

    chemin_ds = Path(f"{base}_datasets.csv")
    _ecrire_csv(
        chemin_ds,
        ["Dataset", "Type", "Technologie", "Connexion", "Format", "Partitionné"],
        [
            [d["nom"], d["type"], d["categorie"], d["connexion"], d["format"],
             "oui" if d["partitionne"] else "non"]
            for d in stockage["detail"]
        ],
    )
    return [chemin_md, chemin_csv, chemin_ds]


def rapport_instance(inv: dict[str, Any], dossier: Path) -> list[Path]:
    """Écrit la synthèse de toute l'instance (Markdown + CSV par projet)."""
    dossier.mkdir(parents=True, exist_ok=True)
    base = dossier / f"inventaire_instance_{datetime.now():%Y%m%d_%H%M}"
    stats = inv["statistiques"]

    md = [
        "# Inventaire technique de migration — instance",
        "",
        f"Généré le {datetime.now():%d/%m/%Y %H:%M}.",
        "",
        "## Synthèse",
        "",
        f"- Projets analysés : {stats['nb_projets']}",
        f"- Simples : {stats['simples']} — Moyens : {stats['moyens']} — "
        f"Complexes : {stats['complexes']}",
        "",
        "## Totaux",
        "",
    ]
    md += [f"- {cle} : {valeur}" for cle, valeur in inv["totaux"].items()]
    md += [
        "",
        "## Projets (du plus complexe au plus simple)",
        "",
        "| Projet | Complexité | Score | Datasets (HDFS/Hive) | Recettes "
        "(Hive/Impala, Spark) | Plugins | Adhérences code | Principales raisons |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in inv["projets"]:
        md.append(
            f"| {p['projet']} | {p['complexite']} | {p['score']} | "
            f"{p['nb_datasets']} ({p['datasets_hdfs_hive']}) | "
            f"{p['nb_recettes']} ({p['recettes_hive_impala']}, {p['recettes_spark']}) | "
            f"{p['plugins']} | {p['adherences_code']} | {'; '.join(p['raisons'])} |"
        )
    if inv["erreurs"]:
        md += ["", "## Erreurs de lecture", ""]
        md += [f"- {e['projet']} : {e['erreur']}" for e in inv["erreurs"]]
    md += ["", f"> {inv['note']}", ""]

    chemin_md = base.with_suffix(".md")
    chemin_md.write_text("\n".join(md), encoding="utf-8")

    chemin_csv = base.with_suffix(".csv")
    _ecrire_csv(
        chemin_csv,
        ["Projet", "Complexité", "Score", "Datasets", "Datasets HDFS/Hive",
         "Recettes", "Recettes Hive/Impala", "Recettes Spark", "Plugins",
         "Adhérences code", "Principales raisons"],
        [
            [p["projet"], p["complexite"], p["score"], p["nb_datasets"],
             p["datasets_hdfs_hive"], p["nb_recettes"], p["recettes_hive_impala"],
             p["recettes_spark"], p["plugins"], p["adherences_code"],
             "; ".join(p["raisons"])]
            for p in inv["projets"]
        ],
    )
    return [chemin_md, chemin_csv]
