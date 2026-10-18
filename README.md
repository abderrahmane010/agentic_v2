# Dataiku MCP - serveur MCP pour Dataiku DSS

Serveur [Model Context Protocol](https://modelcontextprotocol.io) qui donne à
Claude Code (ou à tout client MCP) un accès outillé à une instance Dataiku DSS :
exploration des projets et du Flow, datasets, recettes, scénarios, jobs,
connexions. Il sert notamment à cartographier les projets DSS avant une
migration vers Databricks.

Tous les appels passent par `dataiku-api-client` **14.0.0** (version fixée et
vérifiée par les tests).

## Démarrage rapide

Prérequis : Python 3.11+, une instance DSS et une clé API.

```bash
git clone <url-du-repo> && cd agentic_v2
uv sync --extra dev            # ou : ./install.sh (pip + venv)
cp .env.sample .env            # puis renseigner DSS_HOST et DSS_API_KEY
```

Vérifier la connexion et les outils sur un vrai projet (lecture seule, ne
modifie rien) :

```bash
uv run python scripts/smoke_test.py MON_PROJET
```

Enregistrer le serveur dans Claude Code :

```bash
claude mcp add dataiku-dss \
    -e DSS_HOST=https://votre-dss:10000 \
    -e DSS_API_KEY=votre-cle \
    -e DSS_READ_ONLY=true \
    -- uv run --directory /chemin/vers/agentic_v2 python scripts/mcp_server.py
```

## Chat avec votre propre LLM (vLLM / API compatible OpenAI)

Renseigner `VLLM_BASE_URL`, `VLLM_MODEL` et `OPENAI_API_KEY` dans `.env`, puis :

```bash
python scripts/chat_llm.py                       # chat interactif
python scripts/chat_llm.py -q "Liste les datasets finaux du projet MON_PROJET"
```

Commandes directes (sans LLM, sortie complète) :

- `/tables PROJET` : datasets classés en source / intermédiaire / final
- `/dependances` : dépendances entre tous les projets, cycles et vagues de
  migration proposées ; écrit un rapport Markdown avec graphe Mermaid dans
  `rapports/`
- `/dependances PROJET` : fournisseurs, consommateurs et prérequis de migration
  d'un projet
- `/interfaces [PROJET]` : tables d'un projet utilisées par d'autres projets
  (y compris une table « finale » dans son projet), emplacements écrits par
  plusieurs projets et sources externes partagées
- `/moteurs PROJET [RECETTE] [CIBLE]` : moteur d'exécution de chaque recette (menu
  « Engine » au-dessus de RUN) : moteur configuré, moteur réellement
  sélectionné par DSS, moteurs disponibles et indisponibles avec la raison
  donnée par DSS, et possibilité de passer au moteur CIBLE (ex. `SPARK`).
  Lecture seule : rien n'est modifié dans DSS
- `/projets`, `/scenarios PROJET`, `/echecs PROJET`, `/logs PROJET SCENARIO`,
  `/connexions [PROJET]`, `/export PROJET` : voir `/aide` dans le chat

Les dépendances entre projets sont détectées via les entrées des recettes,
les scénarios, le **stockage physique partagé** (deux datasets sur la même
table ou le même chemin, dont l'un est écrit par un projet) et le **code des
recettes** (`dataiku.Dataset("PROJET.nom")`, tables SQL `schema.table` et
chemins HDFS écrits par un autre projet). Ces liens comptent dans le calcul
des vagues. Les noms construits dynamiquement dans le code et les
consommateurs hors DSS (BI, exports) ne sont pas détectés.
- `/migration PROJET` : inventaire technique avant migration Databricks
  (stockage HDFS/Hive, moteurs des recettes, code spécifique Cloudera, plugins,
  score de complexité) ; écrit un rapport Markdown et des CSV dans `rapports/`
- `/migration` : le même résumé pour tous les projets, trié par complexité

Le chat démarre le serveur MCP, donne ses outils au LLM et exécute les appels
d'outils demandés. Par défaut seuls les outils en lecture sont exposés
(`CHAT_READ_ONLY=true`). Le serveur vLLM doit être lancé avec
`--enable-auto-tool-choice --tool-call-parser hermes` (Qwen) pour l'appel
d'outils.

## Configuration (`.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `DSS_HOST` | - | URL de l'instance DSS (obligatoire) |
| `DSS_API_KEY` | - | Clé API (obligatoire). Ses droits DSS bornent tout ce que le serveur peut faire |
| `DSS_INSECURE_TLS` | `false` | `true` désactive la vérification du certificat (certificat auto-signé uniquement) |
| `DSS_READ_ONLY` | `false` (`true` dans `.env.sample`) | Bloque tous les outils qui modifient DSS |
| `DSS_ALLOWED_PROJECTS` | vide = tous | Liste blanche de clés projet, séparées par des virgules |
| `DSS_PROJECT_KEY` | - | Projet par défaut des scripts |
| `VLLM_BASE_URL`, `VLLM_MODEL`, `OPENAI_API_KEY` | - | LLM utilisé par `scripts/chat_llm.py` |
| `VLLM_INSECURE_TLS`, `VLLM_CA_BUNDLE` | `false`, vide | TLS du serveur LLM (certificat d'entreprise) |
| `CHAT_READ_ONLY` | `true` | Le chat n'expose que les outils en lecture |
| `CHAT_MAX_RESULT_CHARS` | `40000` | Taille max d'un résultat d'outil envoyé au LLM |

## Sécurité

- **Lecture seule** : avec `DSS_READ_ONLY=true`, les outils d'écriture renvoient
  `{"status": "error", "error_type": "read_only"}` sans appeler DSS.
- **Liste blanche de projets** : tout outil sur un projet hors de
  `DSS_ALLOWED_PROJECTS` renvoie `error_type: "forbidden"`.
- **Secrets** : les variables de projet dont le nom contient `password`,
  `secret`, `token`, `key` ou `credential` sont masquées. Seule une liste blanche
  de paramètres de connexion (hôte, base, schéma...) est renvoyée.
- **Opérations de masse** : `duplicate_project_structure` et
  `batch_update_objects` sont en `dry_run=true` par défaut.
  `clone_scenario` crée le clone **inactif** pour ne pas doubler les runs de
  production.
- `get_dataset_sample` renvoie des données réelles au client : à désactiver, ou à
  limiter avec `DSS_ALLOWED_PROJECTS`, si les données sont sensibles.

## Contrat de réponse

Tous les outils renvoient un dict :

```json
{"status": "ok", "...": "..."}
{"status": "error", "error_type": "invalid_argument|forbidden|read_only|job_failed|dss_error", "message": "..."}
```

Les outils qui lancent un job (`run_recipe`, `build_dataset`, `run_scenario`)
renvoient `status: "error"` et `error_type: "job_failed"` si le job ne se termine
pas en succès, avec son état. Avec `wait=false`, ils renvoient l'identifiant du
job tout de suite, et `get_job_details` permet ensuite de le suivre. Un champ
`warnings` signale les données partielles.

## Outils (48)

**Projets** : `list_dss_projects`

**Datasets** : `list_datasets`, `get_dataset_info`, `inspect_dataset_schema`,
`check_dataset_metrics`, `get_dataset_sample`, `create_dataset`*,
`update_dataset`*, `delete_dataset`*, `build_dataset`*, `clear_dataset`*

**Recettes** : `list_recipes`, `get_recipe_info`, `inventaire_moteurs`, `get_recipe_code`,
`validate_recipe_syntax`, `dry_run_recipe`, `get_generated_sql`,
`create_recipe`*, `update_recipe`*, `delete_recipe`*, `run_recipe`*

**Scénarios** : `list_scenarios`, `get_scenario_info`,
`get_scenario_run_history`, `get_scenario_steps`, `get_scenario_logs`,
`create_scenario`*, `update_scenario`*, `delete_scenario`*,
`add_scenario_trigger`*, `remove_scenario_trigger`*, `run_scenario`*,
`clone_scenario`*

**Flow et cartographie** : `get_project_flow`, `classer_datasets_flow`
(sources / intermédiaires / finales / isolées), `search_project_objects`,
`export_project_config` (JSON ou YAML : datasets, recettes avec code,
scénarios)

**Environnement** : `get_connections`, `get_code_environments`,
`get_project_variables`

**Monitoring** : `get_recent_runs`, `get_job_details`, `cancel_running_jobs`*

**Productivité** : `duplicate_project_structure`* (duplication native DSS),
`batch_update_objects`*

\* outil d'écriture, bloqué par `DSS_READ_ONLY=true`.

Les types de recettes sont ceux de DSS : `python`, `pyspark`, `r`,
`sql_script`, `sql_query`, `spark_sql_query`, `shell`, `join`, `grouping`,
`window`, `sync`, `prepare`...
`add_scenario_trigger` gère les types `periodic`, `hourly`, `daily` et
`monthly`. Le type `raw` sert pour un trigger copié depuis `get_scenario_info`
(trigger sur dataset ou SQL).

## Scripts

| Script | Rôle |
|---|---|
| `scripts/mcp_server.py` | Point d'entrée du serveur (`--transport stdio\|sse`) |
| `scripts/smoke_test.py` | Appelle chaque outil de lecture sur un vrai projet et affiche OK / ERREUR |
| `scripts/classer_datasets.py` | Classification topologique des datasets d'un projet |
| `scripts/chat_llm.py` | Chat en terminal avec un LLM compatible OpenAI (vLLM) utilisant les outils MCP |
| `scripts/list_databricks_scenario_projects.py` | Projets avec un dataset Databricks déclencheur d'un scénario actif |

## Développement

```bash
uv sync --extra dev
uv run pytest            # tests unitaires (aucune instance DSS requise)
uv run ruff check .
```

Les tests utilisent un **vrai** `dataikuapi.DSSClient` dont seule la couche HTTP
est remplacée par un faux serveur DSS (`tests/fake_dss.py`). Un appel à une
méthode qui n'existe pas dans `dataikuapi` fait donc échouer les tests.
`tests/test_api_contract.py` vérifie en plus, par analyse du code, que chaque
méthode appelée existe dans la version fixée de `dataikuapi`. Les tests et le
lint tournent en CI (`.github/workflows/ci.yml`).

## Architecture

```
dataiku_mcp/
├── client.py          # client DSS (singleton, configuration .env)
├── securite.py        # lecture seule, liste blanche de projets (décorateur outil_securise)
├── server.py          # déclaration des outils et ressources MCP (FastMCP)
└── tools/
    ├── _common.py     # contrat de réponse, résumés de jobs / runs / triggers
    ├── datasets.py, recipes.py, scenarios.py, advanced_scenarios.py
    ├── project_exploration.py, classification_dataset.py
    ├── code_development.py, environment_config.py
    ├── monitoring_debug.py, productivity.py
scripts/               # CLI
tests/                 # tests unitaires + faux serveur DSS
```

## Limites connues

- `get_generated_sql` reconstruit du SQL indicatif pour quelques recettes
  visuelles (join, grouping, distinct, sort, sampling, prepare). Ce n'est pas le
  SQL exécuté par DSS.
- La classification du Flow est topologique. Les lectures et écritures faites
  dynamiquement dans du code ne sont pas détectées.
- `get_connections` liste les connexions via l'API d'administration : il faut
  une clé API avec les droits suffisants.
