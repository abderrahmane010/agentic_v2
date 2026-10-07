from typing import Any

from dataiku_mcp.client import get_project


_CATEGORIES = (
    "tables_sources",
    "tables_intermediaires",
    "tables_finales",
    "tables_isolees",
)


def classer_datasets_flow(
    project_key: str,
    details: bool = False,
) -> dict[str, Any]:
    """Classe publiquement les datasets selon leur position dans le Flow.

    Par défaut le résultat est compact (nom, type, connexion par dataset),
    adapté à un LLM. ``details=True`` renvoie aussi les recettes
    productrices/consommatrices, les explications et les avertissements.
    """
    if not isinstance(project_key, str):
        raise TypeError(
            "project_key doit être une chaîne de caractères, "
            f"type reçu : {type(project_key).__name__}"
        )

    project_key = project_key.strip()

    if not project_key:
        raise ValueError(
            "project_key ne doit pas être vide"
        )

    resultat = _classer_datasets_flow_interne(project_key)

    if details:
        return resultat

    return _compacter(resultat)


def _compacter(resultat: dict[str, Any]) -> dict[str, Any]:
    """Ne garde que l'essentiel de la classification."""
    compact: dict[str, Any] = {
        "projet": resultat["projet"],
        "statistiques": resultat["statistiques"],
    }

    for categorie in _CATEGORIES:
        compact[categorie] = [
            {
                "nom": dataset["nom"],
                "type": dataset.get("type"),
                "connexion": dataset.get("connexion"),
            }
            for dataset in resultat[categorie]
        ]

    if resultat.get("autres_objets_flow"):
        compact["autres_objets_flow"] = [
            {"nom": o["nom"], "type": o["type"]}
            for o in resultat["autres_objets_flow"]
        ]

    if resultat.get("erreurs_flow"):
        compact["erreurs_flow"] = resultat["erreurs_flow"]

    compact["note"] = (
        "Classification topologique basée sur les dépendances visibles "
        "dans le Flow (pas forcément le sens métier)."
    )
    return compact


def _classer_datasets_flow_interne(
    project_key: str,
) -> dict[str, Any]:
    """Classe les datasets selon leur position dans le Flow Dataiku.

    Règles :
    - source : aucune recette productrice, au moins une recette consommatrice ;
    - intermediaire : au moins une recette productrice et consommatrice ;
    - final : au moins une recette productrice, aucune recette consommatrice ;
    - isole : ni recette productrice ni recette consommatrice.

    Cette classification est topologique. Elle décrit la position du dataset
    dans le Flow Dataiku, pas nécessairement sa nature métier."""
    flow = _cartographier_flow_interne(project_key)

    datasets: dict[str, dict] = {}

    for noeud in flow.get("noeuds", []):
        if noeud.get("categorie") != "dataset":
            continue

        dataset_name = noeud.get("nom")

        if not dataset_name:
            continue

        datasets[dataset_name] = {
            "nom": dataset_name,
            "type": noeud.get("type"),
            "connexion": noeud.get("connexion"),
            "recettes_productrices": [],
            "recettes_consommant": [],
        }

    for arete in flow.get("aretes", []):
        source = str(arete.get("source") or "")
        cible = str(arete.get("cible") or "")

        # recette -> dataset :
        # la recette produit le dataset.
        if (
            source.startswith("recette:")
            and cible.startswith("dataset:")
        ):
            recette_name = source.split(":", 1)[1]
            dataset_name = cible.split(":", 1)[1]

            datasets.setdefault(
                dataset_name,
                {
                    "nom": dataset_name,
                    "type": None,
                    "connexion": None,
                    "recettes_productrices": [],
                    "recettes_consommant": [],
                },
            )

            datasets[dataset_name][
                "recettes_productrices"
            ].append(recette_name)

        # dataset -> recette :
        # la recette consomme le dataset.
        elif (
            source.startswith("dataset:")
            and cible.startswith("recette:")
        ):
            dataset_name = source.split(":", 1)[1]
            recette_name = cible.split(":", 1)[1]

            datasets.setdefault(
                dataset_name,
                {
                    "nom": dataset_name,
                    "type": None,
                    "connexion": None,
                    "recettes_productrices": [],
                    "recettes_consommant": [],
                },
            )

            datasets[dataset_name][
                "recettes_consommant"
            ].append(recette_name)

    autres_objets = sorted(
        (
            {
                "nom": n.get("nom"),
                "identifiant": n.get("identifiant"),
                "type": n.get("type"),
            }
            for n in flow.get("noeuds", [])
            if n.get("categorie") == "objet"
        ),
        key=lambda o: (str(o["type"]), str(o["nom"]).lower()),
    )

    tables_sources: list[dict] = []
    tables_intermediaires: list[dict] = []
    tables_finales: list[dict] = []
    tables_isolees: list[dict] = []

    for dataset in datasets.values():
        producteurs = sorted(set(
            dataset["recettes_productrices"]
        ))

        consommateurs = sorted(set(
            dataset["recettes_consommant"]
        ))

        dataset["recettes_productrices"] = producteurs
        dataset["recettes_consommant"] = consommateurs

        if not producteurs and consommateurs:
            categorie = "source"
            explication = (
                "Le dataset est consommé par une ou plusieurs "
                "recettes, mais aucune recette du Flow ne le produit."
            )
            cible = tables_sources

        elif producteurs and consommateurs:
            categorie = "intermediaire"
            explication = (
                "Le dataset est produit par une recette puis "
                "consommé par au moins une autre recette."
            )
            cible = tables_intermediaires

        elif producteurs and not consommateurs:
            categorie = "final"
            explication = (
                "Le dataset est produit par une ou plusieurs "
                "recettes, mais aucune recette du Flow ne le consomme."
            )
            cible = tables_finales

        else:
            categorie = "isole"
            explication = (
                "Aucune relation avec une recette n'a été détectée "
                "dans le Flow."
            )
            cible = tables_isolees

        dataset["categorie_flow"] = categorie
        dataset["explication"] = explication

        cible.append(dataset)

    def trier(elements: list[dict]) -> list[dict]:
        return sorted(
            elements,
            key=lambda element: str(
                element.get("nom") or ""
            ).lower(),
        )

    tables_sources = trier(tables_sources)
    tables_intermediaires = trier(
        tables_intermediaires
    )
    tables_finales = trier(tables_finales)
    tables_isolees = trier(tables_isolees)

    return {
        "projet": project_key,
        "statistiques": {
            "nb_datasets_total": len(datasets),
            "nb_tables_sources": len(tables_sources),
            "nb_tables_intermediaires": len(
                tables_intermediaires
            ),
            "nb_tables_finales": len(tables_finales),
            "nb_tables_isolees": len(tables_isolees),
        },
        "tables_sources": tables_sources,
        "tables_intermediaires": tables_intermediaires,
        "tables_finales": tables_finales,
        "tables_isolees": tables_isolees,
        "autres_objets_flow": autres_objets,
        "erreurs_flow": flow.get("erreurs", []),
        "avertissements": [
            (
                "La classification est basée sur les dépendances "
                "visibles dans le Flow Dataiku."
            ),
            (
                "Une table source est un dataset sans recette "
                "productrice visible dans le projet."
            ),
            (
                "Une table finale est un dataset sans recette "
                "consommatrice visible dans le projet."
            ),
            (
                "Les lectures et écritures effectuées dynamiquement "
                "dans du code Python, SQL, R ou Shell peuvent ne pas "
                "être détectées."
            ),
            (
                "Un dataset final dans le Flow n'est pas forcément "
                "une table finale au sens métier."
            ),
        ],
    }

#-------------------------------------------------------------------------------------
def _as_dict(item: Any) -> dict[str, Any]:
    """Convertit un résultat Dataiku en dictionnaire."""
    if isinstance(item, dict):
        return item

    get_raw = getattr(item, "get_raw", None)

    if callable(get_raw):
        raw = get_raw()

        if isinstance(raw, dict):
            return raw

    raw_data = getattr(item, "_data", None)

    if isinstance(raw_data, dict):
        return raw_data

    return {
        "name": getattr(item, "name", str(item)),
        "type": getattr(item, "type", None),
    }


def _noeud_objet(
    ref: str,
    noeuds: dict[str, dict[str, Any]],
    autres_objets: dict[str, tuple[str, str]],
    project_key: str,
) -> str:
    """Retourne l'identifiant de noeud d'une entrée/sortie de recette.

    - dataset du projet : noeud déjà créé depuis list_datasets ;
    - dataset partagé depuis un autre projet ("PROJET.dataset") ;
    - autre objet du Flow (dossier géré, modèle, evaluation store...),
      référencé par son identifiant : ce n'est pas un dataset.
    """
    noeud_id = f"dataset:{ref}"
    if noeud_id in noeuds:
        return noeud_id

    if "." in ref and ref.split(".", 1)[0] != project_key:
        noeuds[noeud_id] = {
            "id": noeud_id,
            "nom": ref,
            "categorie": "dataset",
            "type": f"Partagé depuis {ref.split('.', 1)[0]}",
            "connexion": None,
        }
        return noeud_id

    nom, type_objet = autres_objets.get(ref, (ref, "Objet non identifié"))
    noeud_id = f"objet:{ref}"
    noeuds.setdefault(
        noeud_id,
        {
            "id": noeud_id,
            "nom": nom,
            "identifiant": ref,
            "categorie": "objet",
            "type": type_objet,
            "connexion": None,
        },
    )
    return noeud_id


def _lister_autres_objets(project: Any) -> dict[str, tuple[str, str]]:
    """Objets du Flow qui ne sont pas des datasets : identifiant -> (nom, type)."""
    objets: dict[str, tuple[str, str]] = {}
    sources = (
        ("list_managed_folders", "Dossier géré"),
        ("list_saved_models", "Modèle enregistré"),
        ("list_model_evaluation_stores", "Model evaluation store"),
        ("list_streaming_endpoints", "Streaming endpoint"),
        ("list_knowledge_banks", "Knowledge bank"),
    )

    for methode, libelle in sources:
        lister = getattr(project, methode, None)
        if lister is None:
            continue
        try:
            elements = lister()
        except Exception:
            # Type d'objet absent de cette instance/licence : sans impact,
            # ses références seront signalées "Objet non identifié".
            continue

        for element in elements or []:
            if isinstance(element, dict):
                identifiant, nom = element.get("id"), element.get("name")
            else:
                identifiant = getattr(element, "id", None)
                nom = getattr(element, "name", None)
            if identifiant:
                objets[str(identifiant)] = (nom or str(identifiant), libelle)

    return objets

#----------------------------------------------------------------------------------
def _cartographier_flow_interne(
    project_key: str,
) -> dict[str, Any]:
    """Construit le graphe dataset-recette du Flow.

    Cette fonction interne ne réalise ni contrôle d'allowlist
    ni audit. Ces contrôles sont effectués par les outils MCP publics.
    """
    project = get_project(project_key)

    noeuds: dict[str, dict[str, Any]] = {}
    aretes: list[dict[str, str]] = []
    erreurs: list[dict[str, str]] = []

    # Création des noeuds datasets.
    for item in project.list_datasets():
        brut = _as_dict(item)
        nom = brut.get("name")

        if not nom:
            continue

        params = brut.get("params") or {}
        dataset_id = f"dataset:{nom}"

        noeuds[dataset_id] = {
            "id": dataset_id,
            "nom": nom,
            "categorie": "dataset",
            "type": brut.get("type"),
            "connexion": params.get("connection"),
        }

    # Autres objets du Flow (dossiers, modèles...) : référencés par leur
    # identifiant dans les recettes, ce ne sont pas des datasets.
    autres_objets = _lister_autres_objets(project)

    # Création des noeuds recettes et des dépendances.
    for item in project.list_recipes():
        brut = _as_dict(item)
        nom = brut.get("name")

        if not nom:
            continue

        recette_id = f"recette:{nom}"

        noeuds[recette_id] = {
            "id": recette_id,
            "nom": nom,
            "categorie": "recette",
            "type": brut.get("type"),
        }

        try:
            recipe = project.get_recipe(nom)
            settings = recipe.get_settings()

            entrees = list(
                settings.get_flat_input_refs()
            )
            sorties = list(
                settings.get_flat_output_refs()
            )

            # dataset -> recette :
            # la recette lit le dataset.
            for dataset_ref in entrees:
                dataset_name = str(dataset_ref).strip()

                if not dataset_name:
                    continue

                dataset_id = _noeud_objet(
                    dataset_name, noeuds, autres_objets, project_key
                )

                aretes.append(
                    {
                        "source": dataset_id,
                        "cible": recette_id,
                        "relation": "lit",
                    }
                )

            # recette -> dataset :
            # la recette produit le dataset.
            for dataset_ref in sorties:
                dataset_name = str(dataset_ref).strip()

                if not dataset_name:
                    continue

                dataset_id = _noeud_objet(
                    dataset_name, noeuds, autres_objets, project_key
                )

                aretes.append(
                    {
                        "source": recette_id,
                        "cible": dataset_id,
                        "relation": "ecrit",
                    }
                )

        except Exception as exc:
            erreurs.append(
                {
                    "recette": nom,
                    "erreur": str(exc),
                }
            )

    return {
        "projet": project_key,
        "noeuds": list(noeuds.values()),
        "aretes": aretes,
        "statistiques": {
            "nb_datasets": sum(
                1
                for noeud in noeuds.values()
                if noeud.get("categorie") == "dataset"
            ),
            "nb_recettes": sum(
                1
                for noeud in noeuds.values()
                if noeud.get("categorie") == "recette"
            ),
            "nb_dependances": len(aretes),
        },
        "erreurs": erreurs,
    }