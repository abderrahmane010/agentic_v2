# Dataiku Factory - MCP Tool Suite

A comprehensive Model Context Protocol (MCP) tool suite for Dataiku DSS integration. This project provides Claude Code with direct access to Dataiku DSS for managing recipes, datasets, and scenarios.

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Dataiku DSS instance with API access
- Valid DSS API key

### Installation

```bash
# Clone and setup
git clone <repository-url>
cd dataiku_factory

# Run installation script
./install.sh

# Or install manually:
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
```

### Configuration

1. Copy environment template:
```bash
cp .env.sample .env
```

2. Configure your DSS connection in `.env`:
```bash
DSS_HOST=https://your-dss-instance.com:10000
DSS_API_KEY=your-api-key-here
DSS_INSECURE_TLS=true  # Only if using self-signed certificates
```

3. Test your connection:
```bash
python scripts/mcp_server.py --help
```

### Claude Code Integration

Register the MCP server with Claude Code:

```bash
claude mcp add dataiku-factory \
    -e DSS_HOST=https://your-dss-instance.com:10000 \
    -e DSS_API_KEY=your-api-key-here \
    -e DSS_INSECURE_TLS=true \
    -- python scripts/mcp_server.py
```

### Chat with your own LLM (vLLM / OpenAI-compatible)

Set `VLLM_BASE_URL`, `VLLM_MODEL` and `OPENAI_API_KEY` in `.env`, then:

```bash
python scripts/chat_llm.py                       # interactive chat
python scripts/chat_llm.py -q "List the final datasets of project MY_PROJECT"
```

The chat starts the MCP server, gives its tools to the LLM and runs the
tool calls it asks for. By default only read-only tools are exposed
(`CHAT_READ_ONLY=true`). The vLLM server must be started with
`--enable-auto-tool-choice --tool-call-parser hermes` (Qwen) for tool calling.

## 📚 MCP Tool Catalog

### Core Recipe Management Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_recipe` | Create new recipe | `project_key`, `recipe_type`, `recipe_name`, `inputs`, `outputs`, `code` |
| `update_recipe` | Update existing recipe | `project_key`, `recipe_name`, `**kwargs` |
| `delete_recipe` | Delete recipe | `project_key`, `recipe_name` |
| `run_recipe` | Execute recipe | `project_key`, `recipe_name`, `build_mode` |

### Core Dataset Management Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_dataset` | Create new dataset | `project_key`, `dataset_name`, `dataset_type`, `params` |
| `update_dataset` | Update dataset settings | `project_key`, `dataset_name`, `**kwargs` |
| `delete_dataset` | Delete dataset | `project_key`, `dataset_name`, `drop_data` |
| `build_dataset` | Build dataset | `project_key`, `dataset_name`, `mode`, `partition` |
| `inspect_dataset_schema` | Get dataset schema | `project_key`, `dataset_name` |
| `check_dataset_metrics` | Get dataset metrics | `project_key`, `dataset_name` |

### Core Scenario Management Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_scenario` | Create new scenario | `project_key`, `scenario_name`, `scenario_type`, `definition` |
| `update_scenario` | Update scenario settings | `project_key`, `scenario_id`, `**kwargs` |
| `delete_scenario` | Delete scenario | `project_key`, `scenario_id` |
| `add_scenario_trigger` | Add trigger to scenario | `project_key`, `scenario_id`, `trigger_type`, `**params` |
| `remove_scenario_trigger` | Remove scenario trigger | `project_key`, `scenario_id`, `trigger_idx` |
| `run_scenario` | Execute scenario | `project_key`, `scenario_id` |

### 🔧 Advanced Scenario Management Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_scenario_logs` | Get detailed run logs and error messages | `project_key`, `scenario_id`, `run_id` |
| `get_scenario_steps` | Get step configuration including Python code | `project_key`, `scenario_id` |
| `clone_scenario` | Clone scenario with modifications | `project_key`, `source_scenario_id`, `new_scenario_name`, `modifications` |

### 💻 Code and Recipe Development Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_recipe_code` | Extract actual Python/SQL code from recipes | `project_key`, `recipe_name` |
| `validate_recipe_syntax` | Validate Python/SQL syntax before running | `project_key`, `recipe_name`, `code` |
| `test_recipe_dry_run` | Test recipe logic without execution | `project_key`, `recipe_name`, `sample_rows` |

### 🗺️ Project Exploration Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_project_flow` | Get complete data flow/pipeline structure | `project_key` |
| `search_project_objects` | Search datasets, recipes, scenarios by pattern | `project_key`, `search_term`, `object_types` |
| `get_dataset_sample` | Get sample data from datasets | `project_key`, `dataset_name`, `rows`, `columns` |

### ⚙️ Environment and Configuration Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_code_environments` | List available Python/R environments | `project_key` |
| `get_project_variables` | Get project-level variables and secrets | `project_key` |
| `get_connections` | List available data connections | `project_key` |

### 🔍 Debugging and Monitoring Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_recent_runs` | Get recent run history across scenarios/recipes | `project_key`, `limit`, `status_filter` |
| `get_job_details` | Get detailed job execution information | `project_key`, `job_id` |
| `cancel_running_jobs` | Cancel running jobs/scenarios | `project_key`, `job_ids` |

### 🚀 Productivity Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `duplicate_project_structure` | Copy project structure to new project | `source_project_key`, `target_project_key`, `include_data` |
| `export_project_config` | Export project configuration as JSON/YAML | `project_key`, `format` |
| `batch_update_objects` | Update multiple objects with similar changes | `project_key`, `object_type`, `pattern`, `updates` |

**Total: 34 Tools** (16 core + 18 advanced)

## 🔧 Usage Examples

### Core Operations

#### Creating a Python Recipe

```python
# Via Claude Code chat:
"""
Create a python recipe called "data_cleaner" that takes "raw_data" as input 
and outputs "clean_data" in project "ANALYTICS_PROJECT"
"""

# This translates to:
create_recipe(
    project_key="ANALYTICS_PROJECT",
    recipe_type="python",
    recipe_name="data_cleaner",
    inputs=["raw_data"],
    outputs=[{"name": "clean_data", "new": True, "connection": "filesystem_managed"}],
    code="""
import pandas as pd
df = dataiku.Dataset("raw_data").get_dataframe()
# Add your cleaning logic here
df_clean = df.dropna()
dataiku.Dataset("clean_data").write_with_schema(df_clean)
"""
)
```

#### Building a Dataset

```python
# Via Claude Code chat:
"""
Build the dataset "user_analytics" in project "BI" with recursive build mode
"""

# This translates to:
build_dataset(
    project_key="BI",
    dataset_name="user_analytics",
    mode="RECURSIVE_BUILD"
)
```

#### Adding a Daily Scenario Trigger

```python
# Via Claude Code chat:
"""
Add a daily trigger to scenario "daily_etl" that runs at 6:00 AM UTC
"""

# This translates to:
add_scenario_trigger(
    project_key="DATA_PIPELINE",
    scenario_id="daily_etl",
    trigger_type="daily",
    hour=6,
    minute=0,
    timezone="UTC"
)
```

### Advanced Operations

#### Getting Scenario Logs for Failed Runs

```python
# Via Claude Code chat:
"""
Show me the logs for the latest failed run of scenario "data_processing"
"""

# This translates to:
get_scenario_logs(
    project_key="ANALYTICS_PROJECT",
    scenario_id="data_processing"
)
```

#### Extracting and Validating Recipe Code

```python
# Via Claude Code chat:
"""
Extract the code from recipe "customer_segmentation" and validate its syntax
"""

# This translates to:
get_recipe_code(
    project_key="ML_PROJECT",
    recipe_name="customer_segmentation"
)

validate_recipe_syntax(
    project_key="ML_PROJECT",
    recipe_name="customer_segmentation"
)
```

#### Exploring Project Structure

```python
# Via Claude Code chat:
"""
Show me the complete data flow for project "SALES_ANALYTICS" and find all datasets containing "customer"
"""

# This translates to:
get_project_flow(
    project_key="SALES_ANALYTICS"
)

search_project_objects(
    project_key="SALES_ANALYTICS",
    search_term="customer",
    object_types=["datasets", "recipes", "scenarios"]
)
```

#### Getting Sample Data

```python
# Via Claude Code chat:
"""
Get a sample of 500 rows from dataset "transactions" showing only customer_id and amount columns
"""

# This translates to:
get_dataset_sample(
    project_key="FINANCE_PROJECT",
    dataset_name="transactions",
    rows=500,
    columns=["customer_id", "amount"]
)
```

#### Monitoring and Debugging

```python
# Via Claude Code chat:
"""
Show me the recent failed runs in project "DATA_PIPELINE" and get details for any failed jobs
"""

# This translates to:
get_recent_runs(
    project_key="DATA_PIPELINE",
    limit=20,
    status_filter="FAILED"
)

get_job_details(
    project_key="DATA_PIPELINE",
    job_id="job_12345"
)
```

#### Productivity Operations

```python
# Via Claude Code chat:
"""
Export the configuration of project "TEMPLATE_PROJECT" as YAML and duplicate its structure to "NEW_PROJECT"
"""

# This translates to:
export_project_config(
    project_key="TEMPLATE_PROJECT",
    format="yaml"
)

duplicate_project_structure(
    source_project_key="TEMPLATE_PROJECT",
    target_project_key="NEW_PROJECT",
    include_data=False
)
```

## 🏗️ Architecture

```
dataiku_factory/
├── dataiku_mcp/
│   ├── __init__.py
│   ├── client.py          # DSS client wrapper
│   ├── server.py          # MCP server implementation
│   └── tools/
│       ├── recipes.py              # Recipe management tools
│       ├── datasets.py             # Dataset management tools
│       ├── scenarios.py            # Scenario management tools
│       ├── advanced_scenarios.py   # Advanced scenario tools
│       ├── code_development.py     # Code development tools
│       ├── project_exploration.py  # Project exploration tools
│       ├── environment_config.py   # Environment configuration
│       ├── monitoring_debug.py     # Monitoring & debugging
│       └── productivity.py         # Productivity tools
├── scripts/
│   └── mcp_server.py      # MCP server entrypoint
├── install.sh             # Installation script
├── README.md
├── pyproject.toml
└── .env.sample
```

## 🔒 Security

- **API Key Protection**: Store API keys in environment variables, never in code
- **SSL Configuration**: Support for self-signed certificates with `DSS_INSECURE_TLS=true`
- **Permission Validation**: All operations respect DSS user permissions
- **Error Handling**: Sensitive information is not exposed in error messages

## 📈 Monitoring

The MCP server provides logging for monitoring:

```bash
# Run with verbose logging
python scripts/mcp_server.py --verbose

# Check logs for debugging
tail -f dataiku_mcp.log
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

### Development Setup

```bash
# Install development dependencies
pip install -e .[dev]

# Run code formatting
black dataiku_mcp/ scripts/
ruff check dataiku_mcp/ scripts/
```

## 📝 API Reference

### Supported Recipe Types

- **Code recipes**: `python`, `r`, `sql`, `pyspark`, `scala`, `shell`
- **Visual recipes**: `grouping`, `join`, `sync`, `split`, `distinct`, `sort`, `topn`

### Supported Dataset Types

- **Managed datasets**: `managed` (default filesystem storage)
- **Filesystem datasets**: `filesystem` (custom paths)
- **SQL datasets**: `sql` (database tables)
- **Cloud datasets**: `s3`, `gcs`, `azure`
- **Upload datasets**: `uploaded` (CSV uploads)

### Supported Scenario Types

- **Step-based scenarios**: `step_based` (visual workflow)
- **Custom Python scenarios**: `custom_python` (Python code)

### Trigger Types

- **Periodic**: `periodic` (every X minutes)
- **Hourly**: `hourly` (specific minutes past hour)
- **Daily**: `daily` (specific time daily)
- **Monthly**: `monthly` (specific day/time monthly)
- **Dataset**: `dataset` (on dataset changes)

## 🐛 Troubleshooting

### Common Issues

1. **Connection refused**: Check DSS_HOST and ensure DSS is running
2. **SSL certificate errors**: Set `DSS_INSECURE_TLS=true` for self-signed certificates
3. **API key invalid**: Verify API key in DSS admin panel
4. **Permission denied**: Ensure API key has required project permissions

### Debug Mode

Enable debug logging:

```bash
python scripts/mcp_server.py --verbose
```

### Connection Testing

Test the MCP server connection:

```bash
python scripts/mcp_server.py --verbose
```

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built for [Dataiku DSS](https://www.dataiku.com/)
- Uses [Model Context Protocol](https://modelcontextprotocol.io/)
- Integrated with [Claude Code](https://claude.ai/code)

---

**Ready to enhance your Dataiku workflows with AI assistance!** 🚀