#!/bin/bash
set -e

echo "🚀 Installing Dataiku MCP Server..."

# Create virtual environment
echo "Creating virtual environment..."
python -m venv .venv
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -e .

# Create environment file
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.sample .env
    echo "Please edit .env with your DSS instance details"
fi

echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env with your DSS host and API key"
echo "2. Register with Claude Code:"
echo "   claude mcp add dataiku-factory -e DSS_HOST=https://your-dss-instance.com:10000 -e DSS_API_KEY=your-api-key-here -e DSS_INSECURE_TLS=true -- python scripts/mcp_server.py"
