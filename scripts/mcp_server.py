#!/usr/bin/env python3
"""
MCP Server entrypoint for Dataiku DSS integration.
"""

import sys
import asyncio
import argparse
import logging
from pathlib import Path

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataiku_mcp.server import create_server

# Configure logging (stderr: stdout is reserved for the MCP stdio protocol)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

def main():
    """Main entrypoint for the MCP server."""
    parser = argparse.ArgumentParser(description="Dataiku MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport mechanism (default: stdio)"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Host for SSE transport (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE transport (default: 8000)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create server
    try:
        server = create_server()
        logger.info("Starting Dataiku MCP Server...")
        
        # Run server based on transport
        if args.transport == "stdio":
            logger.info("Using stdio transport")
            server.run()
        elif args.transport == "sse":
            logger.info(f"Using SSE transport on {args.host}:{args.port}")
            server.settings.host = args.host
            server.settings.port = args.port
            server.run(transport="sse")
            
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()