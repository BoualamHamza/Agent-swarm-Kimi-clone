"""Async clients for OpenRouter (LLM), Tavily (web search), and Firecrawl (scraping).

Singletons — instantiated lazily on first access so tests can monkeypatch
environment variables without import-time failures.

The OpenRouter client is wrapped with `langsmith.wrappers.wrap_openai` so each
chat-completion call appears as an `llm`-type run in LangSmith with token
usage, model name, message contents, and timing — instead of being invisible
inside the parent @traceable's input/output blob.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI
from tavily import AsyncTavilyClient

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@lru_cache(maxsize=1)
def get_openrouter() -> AsyncOpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    raw = AsyncOpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key,
        # Default is 2 retries; bump to 6 for free-tier resilience. The SDK does
        # exponential backoff with jitter, respects upstream `Retry-After`, and
        # only retries on transient errors (429/408/409/5xx + connection errors).
        max_retries=6,
        # Default is 600s. A 6-retry chain with backoff can take ~1-2 min on a
        # sustained 429; this keeps us well above that ceiling.
        timeout=180.0,
        default_headers={
            "HTTP-Referer": "https://github.com/local/agent-swarm",
            "X-Title": "Agent Swarm",
        },
    )
    # When LangSmith tracing is disabled, wrap_openai is a no-op — safe to always apply.
    return wrap_openai(raw)


@lru_cache(maxsize=1)
def get_tavily() -> AsyncTavilyClient:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    return AsyncTavilyClient(api_key=api_key)


@lru_cache(maxsize=1)
def get_firecrawl():
    from firecrawl import FirecrawlApp
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise RuntimeError("FIRECRAWL_API_KEY is not set")
    return FirecrawlApp(api_key=api_key)
