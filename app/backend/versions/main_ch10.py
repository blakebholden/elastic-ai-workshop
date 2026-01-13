"""
Police Incident Search API - Challenge 10 Version (Full)
=========================================================
Phase 4: Complete Chat & RAG Features

This is the COMPLETE version with all features:
- Health, Stats, Features endpoints
- Keyword, Semantic, Hybrid, Filtered search
- Document retrieval and map data
- RAG summarization
- General chat (across all incidents)
- Document-specific chat

Feature flags control access:
- HYBRID_ENABLED: Hybrid/filtered search
- LLM_ENABLED: Master LLM switch
- RAG_ENABLED: /rag/summarize endpoint
- CHAT_ENABLED: /chat and /chat/document endpoints
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
    SearchResponse,
    SearchHit,
    ChatResponse,
    GeneralChatResponse,
    SummaryResponse,
    HealthResponse,
    StatsResponse,
)

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
        index_exists = bool(await es_client.indices.exists(index=settings.elasticsearch_index))
        doc_count = 0
        if index_exists:
            count_resp = await es_client.count(index=settings.elasticsearch_index)
            doc_count = count_resp["count"]

        return HealthResponse(
            status="healthy",
            elasticsearch={
                "status": "connected",
                "cluster_name": "serverless",
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
        "llm_inference_id": settings.llm_inference_id if settings.llm_enabled else None,
    }


# =============================================================================
# Search Endpoints
# =============================================================================

@app.post("/search/keyword", response_model=SearchResponse, tags=["Search"])
async def keyword_search(request: SearchRequest):
    """
    Traditional BM25 keyword search.

    Searches the narrative field using Elasticsearch's match query.
    Best for exact term matching and known terminology.
    """
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
        "_source": {
            "excludes": ["narrative_semantic"]
        },
    }

    try:
        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return _format_search_response(resp, "keyword")
    except Exception as e:
        logger.error(f"Keyword search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search/semantic", response_model=SearchResponse, tags=["Search"])
async def semantic_search(request: SearchRequest):
    """
    Semantic search using ELSER.

    Uses the narrative_semantic field to find conceptually similar incidents.
    Understands intent and finds related concepts even without exact matches.
    """
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
        "_source": {
            "excludes": ["narrative_semantic"]
        },
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
    Hybrid search combining keyword and semantic using RRF.

    Uses RRF (Reciprocal Rank Fusion) to combine BM25 keyword search
    with ELSER semantic search for best overall relevance.
    """
    settings = get_settings()

    if not settings.hybrid_enabled:
        raise HTTPException(
            status_code=403,
            detail="Hybrid search not enabled. Set HYBRID_ENABLED=true in .env"
        )

    query = {
        "retriever": {
            "rrf": {
                "retrievers": [
                    {
                        "standard": {
                            "query": {
                                "multi_match": {
                                    "query": request.query,
                                    "fields": ["narrative^2", "incident_type", "tags"],
                                }
                            }
                        }
                    },
                    {
                        "standard": {
                            "query": {
                                "semantic": {
                                    "field": "narrative_semantic",
                                    "query": request.query,
                                }
                            }
                        }
                    },
                ],
                "rank_window_size": 50,
                "rank_constant": 20,
            }
        },
        "size": request.size,
        "from": request.from_,
        "_source": {
            "excludes": ["narrative_semantic"]
        },
    }

    try:
        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return _format_search_response(resp, "hybrid")
    except Exception as e:
        logger.error(f"Hybrid search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search/filtered", response_model=SearchResponse, tags=["Search"])
async def filtered_search(request: FilteredSearchRequest):
    """
    Hybrid search with metadata filters.

    Combines semantic understanding with precise filtering by
    district, incident type, date range, severity, etc.
    """
    settings = get_settings()

    if not settings.hybrid_enabled:
        raise HTTPException(
            status_code=403,
            detail="Filtered search requires hybrid search. Set HYBRID_ENABLED=true"
        )

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

    keyword_query = {"multi_match": {"query": request.query, "fields": ["narrative^2", "incident_type", "tags"]}}
    semantic_query = {"semantic": {"field": "narrative_semantic", "query": request.query}}

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
        "_source": {
            "excludes": ["narrative_semantic"]
        },
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


@app.get("/documents/recent", response_model=SearchResponse, tags=["Documents"])
async def get_recent_documents(size: int = Query(default=20, ge=1, le=100)):
    """
    Get recent incidents sorted by date (most recent first).

    Used to populate the search page before a query is entered.
    """
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

        incidents = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            if source.get("location"):
                incidents.append({
                    "id": hit["_id"],
                    **source
                })

        return {"incidents": incidents, "total": len(incidents)}
    except Exception as e:
        logger.error(f"Map documents query failed: {e}")
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
        "_source": {
            "excludes": ["narrative_semantic"]
        },
    }

    try:
        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return _format_search_response(resp, "similar")
    except Exception as e:
        logger.error(f"Similar documents search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# RAG Endpoints
# =============================================================================

@app.post("/rag/summarize", response_model=SummaryResponse, tags=["RAG"])
async def rag_summarize(request: SummarizeRequest):
    """
    Generate a brief summary of an incident using RAG.

    RAG = Retrieve-Augment-Generate:
    1. RETRIEVE: Get the document from Elasticsearch
    2. AUGMENT: Build a prompt with the document context
    3. GENERATE: Call the LLM to generate a summary
    """
    settings = get_settings()

    if not settings.llm_enabled:
        raise HTTPException(
            status_code=403,
            detail="LLM not enabled. Set LLM_ENABLED=true in .env"
        )
    if not settings.rag_enabled:
        raise HTTPException(
            status_code=403,
            detail="RAG not enabled. Set RAG_ENABLED=true in .env"
        )

    try:
        doc_resp = await es_client.get(
            index=settings.elasticsearch_index,
            id=request.document_id,
            source_excludes=["narrative_semantic"],
        )
        document = doc_resp["_source"]
    except NotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Document {request.document_id} not found"
        )

    prompt = f"""Summarize this police incident in 2-3 bullet points. Focus on: what happened, where, and the outcome.

Incident Type: {document.get('incident_type', 'Unknown')}
Location: {document.get('address_block', 'Unknown')}, {document.get('district', '')} District
Resolution: {document.get('resolution', 'Unknown')}

Narrative:
{document.get('narrative', 'No narrative available.')}

Provide a brief summary:"""

    try:
        inference_resp = await es_client.inference.inference(
            model_id=settings.llm_inference_id,
            input=prompt,
        )
        summary = inference_resp.get("completion", [{}])[0].get("result", "Unable to generate summary.")
    except Exception as e:
        logger.warning(f"LLM summarize failed: {e}")
        narrative = document.get("narrative", "")
        summary = f"- {document.get('incident_type', 'Incident')} at {document.get('address_block', 'unknown location')}\n"
        summary += f"- Resolution: {document.get('resolution', 'Unknown')}\n"
        if document.get("arrest_made"):
            summary += "- Arrest was made"
        elif document.get("injuries_reported"):
            summary += "- Injuries were reported"

    return SummaryResponse(summary=summary, document_id=request.document_id)


# =============================================================================
# Chat Endpoints
# =============================================================================

@app.post("/chat", response_model=GeneralChatResponse, tags=["Chat"])
async def general_chat(request: GeneralChatRequest):
    """
    General RAG chat - search across all incidents and generate a response.

    This endpoint powers the floating chat widget and allows users to ask
    questions about incidents without specifying a particular document.

    Requires CHAT_ENABLED=true and LLM_ENABLED=true.
    """
    settings = get_settings()

    if not settings.chat_enabled:
        raise HTTPException(
            status_code=403,
            detail="Chat not enabled. Set CHAT_ENABLED=true in .env"
        )
    if not settings.llm_enabled:
        raise HTTPException(
            status_code=403,
            detail="LLM not enabled. Set LLM_ENABLED=true in .env"
        )

    # Step 1: Search for relevant incidents using hybrid search
    search_query = {
        "retriever": {
            "rrf": {
                "retrievers": [
                    {
                        "standard": {
                            "query": {
                                "match": {"narrative": request.message}
                            }
                        }
                    },
                    {
                        "standard": {
                            "query": {
                                "semantic": {
                                    "field": "narrative_semantic",
                                    "query": request.message
                                }
                            }
                        }
                    }
                ]
            }
        },
        "size": request.max_context,
        "_source": ["incident_id", "incident_type", "narrative", "district", "incident_datetime", "estimated_loss"]
    }

    try:
        search_resp = await es_client.search(
            index=settings.elasticsearch_index,
            body=search_query
        )
    except Exception as e:
        logger.error(f"Chat search failed: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

    # Extract retrieved documents
    retrieved_docs = []
    sources = []
    for hit in search_resp["hits"]["hits"]:
        doc = hit["_source"]
        retrieved_docs.append(doc)
        sources.append(doc.get("incident_id", "Unknown"))

    if not retrieved_docs:
        return GeneralChatResponse(
            response="I couldn't find any relevant incidents matching your query. Try rephrasing your question.",
            sources=[],
            source_count=0
        )

    # Step 2: Build the augmented prompt
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
        for msg in request.chat_history[-4:]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            history_text += f"{role}: {msg.get('content', '')}\n"

    prompt = f"""You are a police department investigation assistant helping analysts review incident data.

Based on the following incident reports, answer the user's question.
{history_text}
INCIDENT REPORTS:
{context_text}

USER QUESTION: {request.message}

INSTRUCTIONS:
- Reference specific incident IDs when making points
- Keep your response concise (2-4 sentences)
- If the incidents don't directly address the question, say so
- Provide factual information from the records only

RESPONSE:"""

    # Step 3: Call the LLM
    try:
        llm_resp = await es_client.inference.inference(
            model_id=settings.llm_inference_id,
            input=prompt
        )
        response_text = llm_resp.get("completion", [{}])[0].get("result", "Unable to generate response")
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return GeneralChatResponse(
            response=f"I found {len(retrieved_docs)} relevant incidents but couldn't generate a summary. Error: {str(e)}",
            sources=sources,
            source_count=len(sources)
        )

    return GeneralChatResponse(
        response=response_text,
        sources=sources,
        source_count=len(sources)
    )


@app.post("/chat/document", response_model=ChatResponse, tags=["Chat"])
async def chat_with_document(request: ChatRequest):
    """
    Chat about a specific document using RAG.

    Retrieves the document content and uses it as context for the LLM
    to answer questions about the incident.

    Requires CHAT_ENABLED=true and LLM_ENABLED=true.
    """
    settings = get_settings()

    if not settings.chat_enabled:
        raise HTTPException(
            status_code=403,
            detail="Chat not enabled. Set CHAT_ENABLED=true in .env"
        )
    if not settings.llm_enabled:
        raise HTTPException(
            status_code=403,
            detail="LLM not enabled. Set LLM_ENABLED=true in .env"
        )

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

    # Build chat prompt
    user_message = f"""Based on this incident report:

{context}

User question: {request.message}"""

    # Call LLM via Elasticsearch Inference API
    try:
        inference_resp = await es_client.inference.inference(
            model_id=settings.llm_inference_id,
            input=user_message,
        )
        response_text = inference_resp.get("completion", [{}])[0].get("result", "Unable to generate response.")
    except Exception as e:
        logger.warning(f"Inference API call failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="LLM service unavailable. Please try again later.",
        )

    return ChatResponse(response=response_text, document_id=request.document_id)


@app.post("/chat/summarize", response_model=SummaryResponse, tags=["Chat"])
async def summarize_document(request: SummarizeRequest):
    """
    Generate a brief summary of an incident.

    This is an alias for /rag/summarize for backwards compatibility.
    """
    return await rag_summarize(request)


# =============================================================================
# Helper Functions
# =============================================================================

def _format_search_response(es_response: dict, search_type: str) -> SearchResponse:
    """Format Elasticsearch response into SearchResponse."""
    hits = []
    for hit in es_response["hits"]["hits"]:
        hits.append(
            SearchHit(
                id=hit["_id"],
                score=hit.get("_score"),
                source=hit["_source"],
                highlight=hit.get("highlight"),
            )
        )

    total = es_response["hits"]["total"]
    total_value = total["value"] if isinstance(total, dict) else total

    return SearchResponse(
        total=total_value,
        hits=hits,
        took_ms=es_response.get("took"),
        search_type=search_type,
    )


async def _call_llm_direct(messages: list, settings) -> str:
    """Call LLM directly via OpenAI-compatible API (fallback)."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.llm_api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.llm_model,
                "messages": messages,
                "max_tokens": 500,
                "temperature": 0.7,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# =============================================================================
# Run Server
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
