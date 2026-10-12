"""Fixtures communes : un vrai DSSClient branché sur le faux serveur DSS."""

import dataikuapi
import pytest

from dataiku_mcp import client as client_module
from tests.fake_dss import FakeDSS


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Environnement neutre : écriture autorisée, tous les projets."""
    monkeypatch.setenv("DSS_READ_ONLY", "false")
    monkeypatch.setenv("DSS_ALLOWED_PROJECTS", "")


@pytest.fixture
def dss(monkeypatch):
    fake = FakeDSS()
    client = dataikuapi.DSSClient("http://dss.test", "api-key")
    monkeypatch.setattr(client, "_perform_http", fake)
    monkeypatch.setattr(client_module, "_CLIENT_INSTANCE", client)
    yield fake
    client_module.reset_client()
