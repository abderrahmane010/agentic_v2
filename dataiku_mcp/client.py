"""
Dataiku DSS client wrapper for MCP integration.
"""

import os
from typing import Optional
import dataikuapi
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

_CLIENT_INSTANCE: Optional[dataikuapi.DSSClient] = None


def get_client() -> dataikuapi.DSSClient:
    """
    Get a configured Dataiku DSS client instance.
    
    Returns:
        dataikuapi.DSSClient: Configured DSS client
        
    Raises:
        ValueError: If required environment variables are missing
        ConnectionError: If connection to DSS fails
    """
    global _CLIENT_INSTANCE
    
    if _CLIENT_INSTANCE is None:
        _CLIENT_INSTANCE = _create_client()
    
    return _CLIENT_INSTANCE


def _create_client() -> dataikuapi.DSSClient:
    """
    Create a new DSS client instance.
    
    Returns:
        dataikuapi.DSSClient: New DSS client instance
    """
    # Get configuration from environment
    dss_host = os.environ.get("DSS_HOST")
    dss_api_key = os.environ.get("DSS_API_KEY")
    insecure_tls = os.environ.get("DSS_INSECURE_TLS", "true").lower() == "true"
    
    if not dss_host:
        raise ValueError("DSS_HOST environment variable is required")
    
    if not dss_api_key:
        raise ValueError("DSS_API_KEY environment variable is required")
    
    try:
        client = dataikuapi.DSSClient(
            dss_host,
            dss_api_key,
            insecure_tls=insecure_tls
        )
        
        # Test connection
        client.get_instance_info()
        
        return client
        
    except Exception as exc:
        raise ConnectionError(f"Failed to connect to DSS at {dss_host}: {exc}"
                              )from exc


def reset_client():
    """
    Reset the client instance (useful for testing).
    """
    global _CLIENT_INSTANCE
    _CLIENT_INSTANCE = None

def get_project(project_key: str) -> dataikuapi.dss.project.DSSProject:
    """
    Get a DSS project by key.
    
    Args:
        project_key: The project key
        
    Returns:
        dataikuapi.DSSProject: Project instance
    """
    client = get_client()
    return client.get_project(project_key)


def list_projects() -> list[str]:
    """
    List all accessible project keys.
    
    Returns:
        list[str]: List of project keys
    """
    client = get_client()
    return client.list_project_keys()


def get_dss_version() -> str:
    """
    Get the DSS version.
    
    Returns:
        str: DSS version string
    """
    client = get_client()
    return client.get_instance_info()._data.get("dssVersion", "Unknown")