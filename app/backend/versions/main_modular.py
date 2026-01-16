"""
Police Incident Search API - FastAPI Backend (Modular Version)

This version imports search and RAG logic from separate modules:
- hybrid.py: Hybrid search query builders
- rag.py: RAG pipeline functions

Users edit those modules during challenges 6 and 8.
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from elasticsearch import AsyncElasticsearch, NotFoundError

from config import get_settings
from models import (
    SearchRequest,
    FilteredSearchRequest,
    HybridSearchRequest,
    ChatRequest,
    SummarizeRequest,
    GeneralChatRequest,
    AgentChatRequest,
    SearchResponse,
    SearchHit,
    ChatResponse,
    GeneralChatResponse,
    AgentChatResponse,
    ToolCall,
    SummaryResponse,
    HealthResponse,
    StatsResponse,
)

# Import from modules - users edit these files!
from hybrid import build_keyword_query, build_semantic_query, build_rrf_query
from rag import retrieve_document, build_prompt, generate_summary

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global ES client
es_client: Optional[AsyncElasticsearch] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global es_client
    settings = get_settings()

    # Initialize Elasticsearch client
    es_config = {"hosts": [settings.elasticsearch_url]}
    if settings.elasticsearch_api_key:
        es_config["api_key"] = settings.elasticsearch_api_key

    es_client = AsyncElasticsearch(**es_config)
    logger.info(f"Connected to Elasticsearch at {settings.elasticsearch_url}")

    yield

    # Cleanup
    if es_client:
        await es_client.close()
        logger.info("Elasticsearch connection closed")


# Initialize FastAPI app
app = FastAPI(
    title="Police Incident Search API",
    description="AI-powered search for police incident reports",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Health & Stats Endpoints
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Check API and Elasticsearch health."""
    settings = get_settings()

    try:
        cluster_health = await es_client.cluster.health()
        index_exists = await es_client.indices.exists(index=settings.elasticsearch_index)
        doc_count = 0
        if index_exists:
            count_resp = await es_client.count(index=settings.elasticsearch_index)
            doc_count = count_resp["count"]

        return HealthResponse(
            status="healthy",
            elasticsearch={
                "status": cluster_health["status"],
                "cluster_name": cluster_health["cluster_name"],
            },
            index={
                "name": settings.elasticsearch_index,
                "exists": index_exists,
                "document_count": doc_count,
            },
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/stats", response_model=StatsResponse, tags=["Health"])
async def get_stats():
    """Get index statistics and aggregations."""
    settings = get_settings()

    try:
        agg_query = {
            "size": 0,
            "aggs": {
                "incident_types": {"terms": {"field": "incident_type", "size": 20}},
                "districts": {"terms": {"field": "district", "size": 20}},
                "resolutions": {"terms": {"field": "resolution", "size": 10}},
                "avg_loss": {"avg": {"field": "estimated_loss"}},
            },
        }

        resp = await es_client.search(index=settings.elasticsearch_index, body=agg_query)
        aggs = resp["aggregations"]

        return StatsResponse(
            total_documents=resp["hits"]["total"]["value"],
            incident_types={b["key"]: b["doc_count"] for b in aggs["incident_types"]["buckets"]},
            districts={b["key"]: b["doc_count"] for b in aggs["districts"]["buckets"]},
            resolutions={b["key"]: b["doc_count"] for b in aggs["resolutions"]["buckets"]},
            avg_estimated_loss=aggs["avg_loss"]["value"] or 0,
        )
    except Exception as e:
        logger.error(f"Stats query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/features", tags=["Health"])
async def get_features():
    """Get feature flags for the frontend."""
    settings = get_settings()

    return {
        "llm_enabled": settings.llm_enabled,
        "chat_enabled": settings.chat_enabled,
        "agent_enabled": settings.agent_enabled,
        "agent_id": settings.agent_id if settings.agent_enabled else None,
        "llm_inference_id": settings.llm_inference_id if settings.llm_enabled else None,
    }


# =============================================================================
# Search Endpoints
# =============================================================================

@app.post("/search/keyword", response_model=SearchResponse, tags=["Search"])
async def keyword_search(request: SearchRequest):
    """Traditional BM25 keyword search."""
    settings = get_settings()

    query = {
        "query": {
            "multi_match": {
                "query": request.query,
                "fields": ["narrative^2", "incident_type", "neighborhood", "tags"],
                "type": "best_fields",
            }
        },
        "highlight": {
            "fields": {"narrative": {"fragment_size": 200, "number_of_fragments": 2}}
        },
        "size": request.size,
        "from": request.from_,
        "_source": {"excludes": ["narrative_semantic"]},
    }

    try:
        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return _format_search_response(resp, "keyword")
    except Exception as e:
        logger.error(f"Keyword search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search/semantic", response_model=SearchResponse, tags=["Search"])
async def semantic_search(request: SearchRequest):
    """Semantic search using ELSER."""
    settings = get_settings()

    query = {
        "query": {
            "semantic": {
                "field": "narrative_semantic",
                "query": request.query,
            }
        },
        "size": request.size,
        "from": request.from_,
        "_source": {"excludes": ["narrative_semantic"]},
    }

    try:
        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return _format_search_response(resp, "semantic")
    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search/hybrid", response_model=SearchResponse, tags=["Search"])
async def hybrid_search(request: HybridSearchRequest):
    """
    Hybrid search combining keyword and semantic.

    Uses RRF (Reciprocal Rank Fusion) to combine BM25 keyword search
    with ELSER semantic search for best overall relevance.

    NOTE: This endpoint uses functions from hybrid.py - edit that file!
    """
    settings = get_settings()

    # Build queries using functions from hybrid.py
    keyword_query = build_keyword_query(request.query)
    semantic_query = build_semantic_query(request.query)
    rrf_query = build_rrf_query(keyword_query, semantic_query, request.size, request.from_)

    # Check if user has implemented the functions
    if not rrf_query:
        raise HTTPException(
            status_code=501,
            detail="Hybrid search not implemented. Complete the TODO sections in hybrid.py"
        )

    try:
        resp = await es_client.search(index=settings.elasticsearch_index, body=rrf_query)
        return _format_search_response(resp, "hybrid")
    except Exception as e:
        logger.error(f"Hybrid search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search/filtered", response_model=SearchResponse, tags=["Search"])
async def filtered_search(request: FilteredSearchRequest):
    """Hybrid search with metadata filters."""
    settings = get_settings()

    # Build filter clauses
    filter_clauses = []
    if request.filters:
        if "district" in request.filters:
            filter_clauses.append({"term": {"district": request.filters["district"]}})
        if "incident_type" in request.filters:
            filter_clauses.append({"term": {"incident_type": request.filters["incident_type"]}})
        if "severity" in request.filters:
            filter_clauses.append({"term": {"severity": request.filters["severity"]}})
        if "arrest_made" in request.filters:
            filter_clauses.append({"term": {"arrest_made": request.filters["arrest_made"]}})
        if "date_from" in request.filters or "date_to" in request.filters:
            date_range = {}
            if "date_from" in request.filters:
                date_range["gte"] = request.filters["date_from"]
            if "date_to" in request.filters:
                date_range["lte"] = request.filters["date_to"]
            filter_clauses.append({"range": {"incident_datetime": date_range}})

    # Use functions from hybrid.py
    keyword_query = build_keyword_query(request.query)
    semantic_query = build_semantic_query(request.query)

    if filter_clauses:
        keyword_query = {"bool": {"must": [keyword_query], "filter": filter_clauses}}
        semantic_query = {"bool": {"must": [semantic_query], "filter": filter_clauses}}

    query = {
        "retriever": {
            "rrf": {
                "retrievers": [
                    {"standard": {"query": keyword_query}},
                    {"standard": {"query": semantic_query}},
                ],
                "rank_window_size": 50,
            }
        },
        "size": request.size,
        "from": request.from_,
        "_source": {"excludes": ["narrative_semantic"]},
    }

    try:
        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return _format_search_response(resp, "filtered")
    except Exception as e:
        logger.error(f"Filtered search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Document Endpoints
# =============================================================================

@app.get("/document/{doc_id}", tags=["Documents"])
async def get_document(doc_id: str):
    """Retrieve a single document by ID."""
    settings = get_settings()

    try:
        resp = await es_client.get(
            index=settings.elasticsearch_index,
            id=doc_id,
            source_excludes=["narrative_semantic"],
        )
        return {"id": resp["_id"], "source": resp["_source"]}
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    except Exception as e:
        logger.error(f"Get document failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents/similar/{doc_id}", response_model=SearchResponse, tags=["Documents"])
async def similar_documents(doc_id: str, size: int = Query(default=5, ge=1, le=20)):
    """Find documents similar to the given document."""
    settings = get_settings()

    query = {
        "query": {
            "more_like_this": {
                "fields": ["narrative", "incident_type", "tags"],
                "like": [{"_index": settings.elasticsearch_index, "_id": doc_id}],
                "min_term_freq": 1,
                "min_doc_freq": 1,
            }
        },
        "size": size,
        "_source": {"excludes": ["narrative_semantic"]},
    }

    try:
        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return _format_search_response(resp, "similar")
    except Exception as e:
        logger.error(f"Similar documents search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents/recent", response_model=SearchResponse, tags=["Documents"])
async def recent_documents(size: int = Query(default=10, ge=1, le=50)):
    """Get recent documents sorted by date."""
    settings = get_settings()

    query = {
        "query": {"match_all": {}},
        "sort": [{"incident_datetime": {"order": "desc"}}],
        "size": size,
        "_source": {"excludes": ["narrative_semantic"]},
    }

    try:
        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return _format_search_response(resp, "recent")
    except Exception as e:
        logger.error(f"Recent documents query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# RAG Endpoints
# =============================================================================

@app.post("/rag/summarize", response_model=SummaryResponse, tags=["RAG"])
async def rag_summarize(request: SummarizeRequest):
    """
    RAG Summarization endpoint.

    This endpoint demonstrates the RAG (Retrieve-Augment-Generate) pattern:
    1. RETRIEVE: Get the document from Elasticsearch
    2. AUGMENT: Build a prompt with the document context
    3. GENERATE: Call the LLM to produce a summary

    NOTE: This endpoint uses functions from rag.py - edit that file!
    """
    settings = get_settings()

    # Step 1: RETRIEVE - Use function from rag.py
    try:
        doc_resp = await retrieve_document(es_client, settings.elasticsearch_index, request.document_id)
        if doc_resp is None:
            raise HTTPException(
                status_code=501,
                detail="RAG retrieve not implemented. Complete STEP 1 in rag.py"
            )
        document = doc_resp["_source"]
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Document {request.document_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Step 2: AUGMENT - Use function from rag.py
    prompt = build_prompt(document)
    if not prompt:
        raise HTTPException(
            status_code=501,
            detail="RAG prompt not implemented. Complete STEP 2 in rag.py"
        )

    # Step 3: GENERATE - Use function from rag.py
    try:
        inference_resp = await generate_summary(es_client, settings.llm_inference_id, prompt)
        if inference_resp is None:
            raise HTTPException(
                status_code=501,
                detail="RAG generate not implemented. Complete STEP 3 in rag.py"
            )
        summary = inference_resp.get("completion", [{}])[0].get("result", "Unable to generate summary.")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Summarize failed: {e}")
        # Generate a simple extractive summary as fallback
        summary = f"• {document.get('incident_type', 'Incident')} at {document.get('address_block', 'unknown location')}\n"
        summary += f"• Resolution: {document.get('resolution', 'Unknown')}\n"
        if document.get("arrest_made"):
            summary += "• Arrest was made"
        elif document.get("injuries_reported"):
            summary += "• Injuries were reported"

    return SummaryResponse(summary=summary, document_id=request.document_id)


# =============================================================================
# Chat Endpoints (Pre-built - not part of user exercises)
# =============================================================================

@app.post("/chat", response_model=GeneralChatResponse, tags=["Chat"])
async def general_chat(request: GeneralChatRequest):
    """General RAG chat - search and generate response."""
    settings = get_settings()

    if not settings.chat_enabled:
        raise HTTPException(
            status_code=403,
            detail="Chat feature is not enabled. Set CHAT_ENABLED=true in environment."
        )

    # Search for relevant incidents
    search_query = {
        "retriever": {
            "rrf": {
                "retrievers": [
                    {"standard": {"query": {"match": {"narrative": request.message}}}},
                    {"standard": {"query": {"semantic": {"field": "narrative_semantic", "query": request.message}}}}
                ]
            }
        },
        "size": request.max_context,
        "_source": ["incident_id", "incident_type", "narrative", "district", "incident_datetime", "estimated_loss"]
    }

    try:
        search_resp = await es_client.search(index=settings.elasticsearch_index, body=search_query)
    except Exception as e:
        logger.error(f"Chat search failed: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

    # Extract documents
    retrieved_docs = []
    sources = []
    for hit in search_resp["hits"]["hits"]:
        doc = hit["_source"]
        retrieved_docs.append(doc)
        sources.append(doc.get("incident_id", "Unknown"))

    if not retrieved_docs:
        return GeneralChatResponse(
            response="I couldn't find any relevant incidents matching your query.",
            sources=[],
            source_count=0
        )

    # Build context
    context_text = ""
    for i, doc in enumerate(retrieved_docs, 1):
        context_text += f"\n{i}. **{doc.get('incident_id', 'Unknown')}** ({doc.get('incident_type', 'Unknown')}) - {doc.get('district', 'Unknown')} District\n"
        context_text += f"   Date: {doc.get('incident_datetime', 'Unknown')}\n"
        if doc.get('estimated_loss', 0) > 0:
            context_text += f"   Estimated Loss: ${doc.get('estimated_loss', 0):,.0f}\n"
        narrative = doc.get('narrative', '')[:400]
        context_text += f"   Summary: {narrative}\n"

    # Include chat history for context
    history_text = ""
    if request.chat_history:
        history_text = "\nPrevious conversation:\n"
        for msg in request.chat_history[-4:]:  # Last 4 messages
            role = "User" if msg.get("role") == "user" else "Assistant"
            history_text += f"{role}: {msg.get('content', '')}\n"

    prompt = f"""You are a police department investigation assistant.

Based on the following incident reports, answer the user's question.
{history_text}
INCIDENT REPORTS:
{context_text}

USER QUESTION: {request.message}

INSTRUCTIONS:
- Reference specific incident IDs
- Keep your response concise (2-4 sentences)
- Provide factual information only

RESPONSE:"""

    try:
        llm_resp = await es_client.inference.inference(
            model_id=settings.llm_inference_id,
            task_type="completion",
            input=prompt
        )
        response_text = llm_resp.get("completion", [{}])[0].get("result", "Unable to generate response")
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return GeneralChatResponse(
            response=f"I found {len(retrieved_docs)} relevant incidents but couldn't generate a summary.",
            sources=sources,
            source_count=len(sources)
        )

    return GeneralChatResponse(response=response_text, sources=sources, source_count=len(sources))


@app.post("/agent/chat", response_model=AgentChatResponse, tags=["Agent"])
async def agent_chat(request: AgentChatRequest):
    """Chat with Agent Builder."""
    import httpx

    settings = get_settings()

    if not settings.agent_enabled:
        raise HTTPException(status_code=403, detail="Agent chat is not enabled.")

    if not settings.kibana_url:
        raise HTTPException(status_code=503, detail="Kibana URL not configured.")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.kibana_url}/api/ai/agents/{settings.agent_id}/chat",
                headers={
                    "kbn-xsrf": "true",
                    "Authorization": f"ApiKey {settings.elasticsearch_api_key}",
                    "Content-Type": "application/json",
                },
                json={"message": request.message, "conversationId": request.conversation_id}
            )

            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"Agent API error: {response.text}")

            result = response.json()

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Agent request timed out.")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Could not connect to Agent Builder: {str(e)}")

    tool_calls = [
        ToolCall(tool=tc.get("tool", "unknown"), parameters=tc.get("parameters", {}), result=tc.get("result"))
        for tc in result.get("toolCalls", [])
    ]

    return AgentChatResponse(
        response=result.get("response", "No response from agent."),
        tool_calls=tool_calls,
        sources=result.get("sources", []),
        conversation_id=result.get("conversationId")
    )


# =============================================================================
# Helper Functions
# =============================================================================

def _format_search_response(es_response: dict, search_type: str) -> SearchResponse:
    """Format Elasticsearch response into SearchResponse."""
    hits = [
        SearchHit(
            id=hit["_id"],
            score=hit.get("_score"),
            source=hit["_source"],
            highlight=hit.get("highlight"),
        )
        for hit in es_response["hits"]["hits"]
    ]

    total = es_response["hits"]["total"]
    total_value = total["value"] if isinstance(total, dict) else total

    return SearchResponse(total=total_value, hits=hits, took_ms=es_response.get("took"), search_type=search_type)


# =============================================================================
# Run Server
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.debug)
