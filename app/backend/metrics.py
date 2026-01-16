"""
Metrics and Observability Module

Logs API usage metrics to:
1. Local Elasticsearch index (app-metrics) - for user's personal dashboard
2. Remote Elasticsearch cluster (optional) - for instructor's class-wide dashboard

Metrics include:
- Endpoint called
- Latency
- Success/failure
- Token counts (estimated)
- Session/user identifier
"""
import logging
import socket
from datetime import datetime
from typing import Optional
from elasticsearch import AsyncElasticsearch

from config import get_settings

logger = logging.getLogger(__name__)

# Remote ES client (lazy initialized)
_remote_es_client: Optional[AsyncElasticsearch] = None


def _get_remote_client() -> Optional[AsyncElasticsearch]:
    """Get or create the remote ES client for class-wide metrics."""
    global _remote_es_client
    settings = get_settings()

    if not settings.remote_metrics_enabled:
        return None

    if not settings.remote_metrics_url or not settings.remote_metrics_api_key:
        return None

    if _remote_es_client is None:
        _remote_es_client = AsyncElasticsearch(
            hosts=[settings.remote_metrics_url],
            api_key=settings.remote_metrics_api_key,
        )

    return _remote_es_client


def _get_session_id() -> str:
    """Get a unique session identifier for this workshop instance."""
    settings = get_settings()

    if settings.session_id:
        return settings.session_id

    # Fall back to hostname
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars per token average)."""
    if not text:
        return 0
    return len(text) // 4


async def log_metrics(
    es_client: AsyncElasticsearch,
    endpoint: str,
    latency_ms: float,
    success: bool,
    prompt: str = "",
    response: str = "",
    error: str = None,
    extra_fields: dict = None,
):
    """
    Log API metrics to local and remote Elasticsearch.

    Args:
        es_client: Local ES client
        endpoint: API endpoint name (e.g., "/chat", "/rag/summarize")
        latency_ms: Request latency in milliseconds
        success: Whether the request succeeded
        prompt: The input prompt (for token estimation)
        response: The LLM response (for token estimation)
        error: Error message if failed
        extra_fields: Additional fields to log
    """
    settings = get_settings()

    if not settings.metrics_enabled:
        return

    # Estimate tokens
    prompt_tokens = _estimate_tokens(prompt)
    completion_tokens = _estimate_tokens(response)
    total_tokens = prompt_tokens + completion_tokens

    # Build the metric document
    doc = {
        "@timestamp": datetime.utcnow().isoformat() + "Z",
        "endpoint": endpoint,
        "latency_ms": round(latency_ms, 2),
        "success": success,
        "error": error,
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": total_tokens,
        },
        "session_id": _get_session_id(),
    }

    # Add any extra fields
    if extra_fields:
        doc.update(extra_fields)

    # Log to local index
    try:
        await es_client.index(
            index=settings.metrics_index,
            document=doc,
        )
        logger.debug(f"Logged metrics for {endpoint}")
    except Exception as e:
        logger.warning(f"Failed to log local metrics: {e}")

    # Log to remote index (instructor's cluster)
    remote_client = _get_remote_client()
    if remote_client:
        try:
            # Add workshop identifier for class-wide view
            doc["workshop"] = "smarter-ai-workshop"

            await remote_client.index(
                index=settings.remote_metrics_index,
                document=doc,
            )
            logger.debug(f"Logged remote metrics for {endpoint}")
        except Exception as e:
            logger.warning(f"Failed to log remote metrics: {e}")


async def log_search_metrics(
    es_client: AsyncElasticsearch,
    search_type: str,
    query: str,
    latency_ms: float,
    result_count: int,
    success: bool = True,
    error: str = None,
):
    """Log search-specific metrics."""
    await log_metrics(
        es_client=es_client,
        endpoint=f"/search/{search_type}",
        latency_ms=latency_ms,
        success=success,
        prompt=query,
        error=error,
        extra_fields={
            "search_type": search_type,
            "result_count": result_count,
            "query_length": len(query) if query else 0,
        },
    )


async def log_llm_metrics(
    es_client: AsyncElasticsearch,
    endpoint: str,
    prompt: str,
    response: str,
    latency_ms: float,
    success: bool = True,
    error: str = None,
):
    """Log LLM-specific metrics."""
    await log_metrics(
        es_client=es_client,
        endpoint=endpoint,
        latency_ms=latency_ms,
        success=success,
        prompt=prompt,
        response=response,
        error=error,
        extra_fields={
            "llm_call": True,
        },
    )


async def log_agent_metrics(
    es_client: AsyncElasticsearch,
    message: str,
    response: str,
    latency_ms: float,
    tool_calls: int = 0,
    success: bool = True,
    error: str = None,
):
    """Log agent-specific metrics."""
    await log_metrics(
        es_client=es_client,
        endpoint="/agent/chat",
        latency_ms=latency_ms,
        success=success,
        prompt=message,
        response=response,
        error=error,
        extra_fields={
            "agent_call": True,
            "tool_calls": tool_calls,
        },
    )


async def create_metrics_index(es_client: AsyncElasticsearch):
    """Create the metrics index with appropriate mappings."""
    settings = get_settings()

    mapping = {
        "mappings": {
            "properties": {
                "@timestamp": {"type": "date"},
                "endpoint": {"type": "keyword"},
                "latency_ms": {"type": "float"},
                "success": {"type": "boolean"},
                "error": {"type": "text"},
                "tokens": {
                    "properties": {
                        "prompt": {"type": "integer"},
                        "completion": {"type": "integer"},
                        "total": {"type": "integer"},
                    }
                },
                "session_id": {"type": "keyword"},
                "workshop": {"type": "keyword"},
                "search_type": {"type": "keyword"},
                "result_count": {"type": "integer"},
                "query_length": {"type": "integer"},
                "llm_call": {"type": "boolean"},
                "agent_call": {"type": "boolean"},
                "tool_calls": {"type": "integer"},
            }
        }
    }

    try:
        exists = await es_client.indices.exists(index=settings.metrics_index)
        if not exists:
            await es_client.indices.create(index=settings.metrics_index, body=mapping)
            logger.info(f"Created metrics index: {settings.metrics_index}")
    except Exception as e:
        logger.warning(f"Could not create metrics index: {e}")
