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
from starlette.responses import StreamingResponse
from elasticsearch import AsyncElasticsearch, NotFoundError

import time

from config import get_settings
from metrics import create_metrics_index, log_llm_metrics, log_agent_metrics, log_search_metrics
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
from validation import validate_chat_input

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
    es_config = {
        "hosts": [settings.elasticsearch_url],
        "request_timeout": 60,  # 60 seconds for LLM inference calls
    }
    if settings.elasticsearch_api_key:
        es_config["api_key"] = settings.elasticsearch_api_key

    es_client = AsyncElasticsearch(**es_config)
    logger.info(f"Connected to Elasticsearch at {settings.elasticsearch_url}")

    # Create metrics index for observability
    await create_metrics_index(es_client)

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
        # Check ES connection with a simple info call (works in Serverless)
        es_info = await es_client.info()
        index_exists = bool(await es_client.indices.exists(index=settings.elasticsearch_index))
        doc_count = 0
        if index_exists:
            count_resp = await es_client.count(index=settings.elasticsearch_index)
            doc_count = count_resp["count"]

        return HealthResponse(
            status="healthy",
            elasticsearch={
                "status": "available",
                "cluster_name": es_info.get("cluster_name", "serverless"),
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
        "hybrid_enabled": settings.hybrid_enabled,
        "llm_enabled": settings.llm_enabled,
        "rag_enabled": settings.rag_enabled,
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
    start_time = time.time()
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
        result = _format_search_response(resp, "hybrid")

        # Log search metrics
        latency_ms = (time.time() - start_time) * 1000
        await log_search_metrics(
            es_client=es_client,
            search_type="hybrid",
            query=request.query,
            latency_ms=latency_ms,
            result_count=result.total,
            success=True
        )

        return result
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


@app.get("/documents/map", tags=["Documents"])
async def get_documents_for_map(
    incident_type: Optional[str] = Query(default=None),
    district: Optional[str] = Query(default=None),
    size: int = Query(default=500, ge=1, le=1000)
):
    """Get documents with location data for map display."""
    settings = get_settings()

    filter_clauses = [{"exists": {"field": "location"}}]

    if incident_type:
        filter_clauses.append({"term": {"incident_type": incident_type}})
    if district:
        filter_clauses.append({"term": {"district": district}})

    query = {
        "query": {
            "bool": {
                "filter": filter_clauses
            }
        },
        "size": size,
        "_source": [
            "incident_id", "incident_type", "incident_subtype",
            "incident_datetime", "district", "neighborhood",
            "address_block", "location", "severity", "resolution"
        ]
    }

    try:
        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return {
            "total": resp["hits"]["total"]["value"],
            "incidents": [hit["_source"] for hit in resp["hits"]["hits"]]
        }
    except Exception as e:
        logger.error(f"Map documents query failed: {e}")
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
    start_time = time.time()
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

    # Log metrics
    latency_ms = (time.time() - start_time) * 1000
    await log_llm_metrics(
        es_client=es_client,
        endpoint="/rag/summarize",
        prompt=prompt,
        response=summary,
        latency_ms=latency_ms,
        success=True
    )

    return SummaryResponse(summary=summary, document_id=request.document_id)


# =============================================================================
# Chat Endpoints (Pre-built - not part of user exercises)
# =============================================================================

@app.post("/chat", response_model=GeneralChatResponse, tags=["Chat"])
async def general_chat(request: GeneralChatRequest):
    """General RAG chat - search and generate response."""
    start_time = time.time()
    settings = get_settings()

    if not settings.chat_enabled:
        raise HTTPException(
            status_code=403,
            detail="Chat feature is not enabled. Set CHAT_ENABLED=true in environment."
        )

    # Validate input for security
    is_valid, error_msg = validate_chat_input(request.message)
    if not is_valid:
        return GeneralChatResponse(
            response=error_msg,
            sources=[],
            source_count=0
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

    # Log metrics
    latency_ms = (time.time() - start_time) * 1000
    await log_llm_metrics(
        es_client=es_client,
        endpoint="/chat",
        prompt=prompt,
        response=response_text,
        latency_ms=latency_ms,
        success=True
    )

    return GeneralChatResponse(response=response_text, sources=sources, source_count=len(sources))


@app.post("/chat/document", response_model=ChatResponse, tags=["Chat"])
async def chat_with_document(request: ChatRequest):
    """
    Chat about a specific document using Agent Builder.

    Retrieves the document content and includes it as context when
    calling the Agent Builder API. Conversations are persisted in Kibana.
    """
    import httpx

    settings = get_settings()

    # Get the document
    try:
        doc_resp = await es_client.get(
            index=settings.elasticsearch_index,
            id=request.document_id,
            source_excludes=["narrative_semantic"],
        )
        document = doc_resp["_source"]
    except NotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Document {request.document_id} not found"
        )

    # Build context from document
    context = f"""Police Incident Report:
- Incident ID: {document.get('incident_id', 'Unknown')}
- Type: {document.get('incident_type', 'Unknown')} - {document.get('incident_subtype', '')}
- Date/Time: {document.get('incident_datetime', 'Unknown')}
- Location: {document.get('address_block', 'Unknown')}, {document.get('neighborhood', '')} ({document.get('district', '')} District)
- Severity: {document.get('severity', 'Unknown')}
- Resolution: {document.get('resolution', 'Unknown')}
- Arrest Made: {document.get('arrest_made', 'Unknown')}
- Injuries Reported: {document.get('injuries_reported', 'Unknown')}
- Weapon Involved: {document.get('weapon_involved', 'None')}
- Estimated Loss: ${document.get('estimated_loss', 0):,.2f}

Narrative:
{document.get('narrative', 'No narrative available.')}
"""

    # Build message with document context
    user_message = f"""I'm asking about this specific incident report:

{context}

My question: {request.message}"""

    # Check if Agent Builder is available
    if not settings.kibana_url or not settings.agent_enabled:
        # Fallback to direct inference if Agent Builder not configured
        try:
            inference_resp = await es_client.inference.inference(
                model_id=settings.llm_inference_id,
                task_type="completion",
                input=user_message,
            )
            response_text = inference_resp.get("completion", [{}])[0].get("result", "Unable to generate response.")
            return ChatResponse(response=response_text, document_id=request.document_id, conversation_id=None)
        except Exception as e:
            logger.warning(f"Direct inference failed: {e}")
            raise HTTPException(status_code=503, detail="LLM service unavailable")

    # Call Agent Builder API
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            request_body = {
                "input": user_message,
                "agent_id": settings.agent_id,
            }
            if request.conversation_id:
                request_body["conversation_id"] = request.conversation_id

            response = await client.post(
                f"{settings.kibana_url}/api/agent_builder/converse",
                headers={
                    "kbn-xsrf": "true",
                    "Authorization": f"ApiKey {settings.elasticsearch_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body
            )

            if response.status_code != 200:
                logger.error(f"Agent API error: {response.status_code} - {response.text}")
                raise HTTPException(status_code=response.status_code, detail=f"Agent API error: {response.text}")

            result = response.json()

    except httpx.TimeoutException:
        logger.error("Agent API request timed out")
        raise HTTPException(status_code=504, detail="Agent request timed out")
    except httpx.RequestError as e:
        logger.error(f"Agent API connection error: {e}")
        raise HTTPException(status_code=503, detail=f"Could not connect to Agent Builder: {str(e)}")

    # Extract response
    response_obj = result.get("response", {})
    response_text = response_obj.get("message", "") if isinstance(response_obj, dict) else str(response_obj)

    return ChatResponse(
        response=response_text or "No response from agent.",
        document_id=request.document_id,
        conversation_id=result.get("conversation_id")
    )


@app.post("/agent/chat", response_model=AgentChatResponse, tags=["Agent"])
async def agent_chat(request: AgentChatRequest):
    """Chat with Agent Builder."""
    import httpx

    start_time = time.time()
    settings = get_settings()

    if not settings.agent_enabled:
        raise HTTPException(status_code=403, detail="Agent chat is not enabled.")

    if not settings.kibana_url:
        raise HTTPException(status_code=503, detail="Kibana URL not configured.")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Build request body
            request_body = {
                "input": request.message,
                "agent_id": settings.agent_id,
            }
            if request.conversation_id:
                request_body["conversation_id"] = request.conversation_id

            response = await client.post(
                f"{settings.kibana_url}/api/agent_builder/converse",
                headers={
                    "kbn-xsrf": "true",
                    "Authorization": f"ApiKey {settings.elasticsearch_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body
            )

            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"Agent API error: {response.text}")

            result = response.json()

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Agent request timed out.")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Could not connect to Agent Builder: {str(e)}")

    # Parse tool calls from steps
    tool_calls = []
    for step in result.get("steps", []):
        if step.get("type") == "tool_call":
            tool_calls.append(ToolCall(
                tool=step.get("tool_id", "unknown"),
                parameters=step.get("parameters", {}),
                result=step.get("result")
            ))

    # Extract response message
    response_obj = result.get("response", {})
    response_message = response_obj.get("message", "") if isinstance(response_obj, dict) else str(response_obj)

    # Log agent metrics
    latency_ms = (time.time() - start_time) * 1000
    await log_agent_metrics(
        es_client=es_client,
        message=request.message,
        response=response_message or "",
        latency_ms=latency_ms,
        tool_calls=len(tool_calls),
        success=True
    )

    return AgentChatResponse(
        response=response_message or "No response from agent.",
        tool_calls=tool_calls,
        sources=[],
        conversation_id=result.get("conversation_id")
    )


@app.post("/agent/chat/stream", tags=["Agent"])
async def agent_chat_stream(request: AgentChatRequest):
    """
    Stream chat with Agent Builder using Server-Sent Events.

    Returns real-time progress as the agent processes your request:
    - reasoning: Agent's thinking process
    - tool_call: When a tool is selected
    - tool_progress: Tool execution updates
    - tool_result: Tool completion results
    - message_chunk: Streaming response text
    - message_complete: Final response
    """
    import httpx

    settings = get_settings()

    if not settings.agent_enabled:
        raise HTTPException(status_code=403, detail="Agent chat is not enabled.")

    if not settings.kibana_url:
        raise HTTPException(status_code=503, detail="Kibana URL not configured.")

    async def event_generator():
        """Generate SSE events from Kibana Agent Builder stream."""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                request_body = {
                    "input": request.message,
                    "agent_id": settings.agent_id,
                }
                if request.conversation_id:
                    request_body["conversation_id"] = request.conversation_id

                async with client.stream(
                    "POST",
                    f"{settings.kibana_url}/api/agent_builder/converse/async",
                    headers={
                        "kbn-xsrf": "true",
                        "Authorization": f"ApiKey {settings.elasticsearch_api_key}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                    },
                    json=request_body
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        yield f"event: error\ndata: {error_text.decode()}\n\n"
                        return

                    # Stream events from Kibana to the client
                    async for line in response.aiter_lines():
                        if line:
                            # Pass through the SSE events from Kibana
                            yield f"{line}\n"
                        else:
                            # Empty line marks end of event
                            yield "\n"

        except httpx.TimeoutException:
            yield f"event: error\ndata: {{\"error\": \"Request timed out\"}}\n\n"
        except httpx.RequestError as e:
            yield f"event: error\ndata: {{\"error\": \"Connection error: {str(e)}\"}}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"event: error\ndata: {{\"error\": \"Stream error: {str(e)}\"}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@app.post("/chat/document/stream", tags=["Chat"])
async def chat_with_document_stream(request: ChatRequest):
    """
    Stream chat about a specific document using Agent Builder.

    Similar to /agent/chat/stream but includes document context.
    """
    import httpx

    settings = get_settings()

    # Get the document first
    try:
        doc_resp = await es_client.get(
            index=settings.elasticsearch_index,
            id=request.document_id,
            source_excludes=["narrative_semantic"],
        )
        document = doc_resp["_source"]
    except NotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Document {request.document_id} not found"
        )

    # Build context from document
    context = f"""Police Incident Report:
- Incident ID: {document.get('incident_id', 'Unknown')}
- Type: {document.get('incident_type', 'Unknown')} - {document.get('incident_subtype', '')}
- Date/Time: {document.get('incident_datetime', 'Unknown')}
- Location: {document.get('address_block', 'Unknown')}, {document.get('neighborhood', '')} ({document.get('district', '')} District)
- Severity: {document.get('severity', 'Unknown')}
- Resolution: {document.get('resolution', 'Unknown')}
- Arrest Made: {document.get('arrest_made', 'Unknown')}
- Injuries Reported: {document.get('injuries_reported', 'Unknown')}
- Weapon Involved: {document.get('weapon_involved', 'None')}
- Estimated Loss: ${document.get('estimated_loss', 0):,.2f}

Narrative:
{document.get('narrative', 'No narrative available.')}
"""

    user_message = f"""I'm asking about this specific incident report:

{context}

My question: {request.message}"""

    if not settings.kibana_url or not settings.agent_enabled:
        raise HTTPException(status_code=503, detail="Agent Builder not configured for streaming.")

    async def event_generator():
        """Generate SSE events from Kibana Agent Builder stream."""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                request_body = {
                    "input": user_message,
                    "agent_id": settings.agent_id,
                }
                if request.conversation_id:
                    request_body["conversation_id"] = request.conversation_id

                async with client.stream(
                    "POST",
                    f"{settings.kibana_url}/api/agent_builder/converse/async",
                    headers={
                        "kbn-xsrf": "true",
                        "Authorization": f"ApiKey {settings.elasticsearch_api_key}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                    },
                    json=request_body
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        yield f"event: error\ndata: {error_text.decode()}\n\n"
                        return

                    async for line in response.aiter_lines():
                        if line:
                            yield f"{line}\n"
                        else:
                            yield "\n"

        except httpx.TimeoutException:
            yield f"event: error\ndata: {{\"error\": \"Request timed out\"}}\n\n"
        except httpx.RequestError as e:
            yield f"event: error\ndata: {{\"error\": \"Connection error: {str(e)}\"}}\n\n"
        except Exception as e:
            logger.error(f"Document stream error: {e}")
            yield f"event: error\ndata: {{\"error\": \"Stream error: {str(e)}\"}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
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
