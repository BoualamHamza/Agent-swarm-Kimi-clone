"""Shared test fixtures."""
from __future__ import annotations

import pytest

from app.client import get_openrouter, get_tavily
from app.memory import get_store


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Provide dummy API keys so the singletons construct without erroring.

    Disable LangSmith tracing during tests to avoid network calls.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    # Reset the lru_cache singletons between tests
    get_openrouter.cache_clear()
    get_tavily.cache_clear()
    get_store.cache_clear()
    yield
