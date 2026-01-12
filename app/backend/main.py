"""
Police Incident Search API - FastAPI Backend

A search API demonstrating keyword, semantic, vector, and hybrid search
capabilities with Elasticsearch and LLM-powered chat.
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
    SearchResponse,
    SearchHit,
    ChatResponse,
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
        # Check ES cluster health
        cluster_health = await es_client.cluster.health()

        # Check index exists and get doc count
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
        # Aggregation query
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

        # Parse aggregations
        aggs = resp["aggregations"]

        return StatsResponse(
            total_documents=resp["hits"]["total"]["value"],
            incident_types={
                b["key"]: b["doc_count"] for b in aggs["incident_types"]["buckets"]
            },
            districts={b["key"]: b["doc_count"] for b in aggs["districts"]["buckets"]},
            resolutions={
                b["key"]: b["doc_count"] for b in aggs["resolutions"]["buckets"]
            },
            avg_estimated_loss=aggs["avg_loss"]["value"] or 0,
        )
    except Exception as e:
        logger.error(f"Stats query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    Hybrid search combining keyword and semantic.

    Uses RRF (Reciprocal Rank Fusion) to combine BM25 keyword search
    with ELSER semantic search for best overall relevance.
    """
    settings = get_settings()

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

    # Build filter clauses
    filter_clauses = []
    if request.filters:
        if "district" in request.filters:
            filter_clauses.append({"term": {"district": request.filters["district"]}})
        if "incident_type" in request.filters:
            filter_clauses.append(
                {"term": {"incident_type": request.filters["incident_type"]}}
            )
        if "severity" in request.filters:
            filter_clauses.append({"term": {"severity": request.filters["severity"]}})
        if "arrest_made" in request.filters:
            filter_clauses.append(
                {"term": {"arrest_made": request.filters["arrest_made"]}}
            )
        if "date_from" in request.filters or "date_to" in request.filters:
            date_range = {}
            if "date_from" in request.filters:
                date_range["gte"] = request.filters["date_from"]
            if "date_to" in request.filters:
                date_range["lte"] = request.filters["date_to"]
            filter_clauses.append({"range": {"incident_datetime": date_range}})

    # Build query with filters applied to both retrievers
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
# Chat / RAG Endpoints
# =============================================================================

@app.post("/chat/document", response_model=ChatResponse, tags=["Chat"])
async def chat_with_document(request: ChatRequest):
    """
    Chat about a specific document using RAG.

    Retrieves the document content and uses it as context for the LLM
    to answer questions about the incident.
    """
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

    # Build chat prompt
    system_prompt = """You are a police department assistant helping officers and analysts understand incident reports.
Answer questions based only on the provided incident report. Be factual and concise.
If the information isn't in the report, say so clearly. Never speculate about ongoing investigations."""

    messages = [{"role": "system", "content": system_prompt}]

    # Add chat history
    for msg in request.chat_history[-6:]:  # Keep last 6 messages for context
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    # Add current message with context
    user_message = f"""Based on this incident report:

{context}

User question: {request.message}"""
    messages.append({"role": "user", "content": user_message})

    # Call LLM via Elasticsearch Inference API
    try:
        inference_resp = await es_client.inference.inference(
            inference_id=settings.llm_inference_id,
            body={"input": user_message},
        )
        response_text = inference_resp.get("completion", [{}])[0].get("result", "Unable to generate response.")
    except Exception as e:
        logger.warning(f"Inference API call failed: {e}, trying direct LLM")
        # Fallback to direct LLM call if configured
        if settings.llm_api_key and settings.llm_api_base:
            response_text = await _call_llm_direct(messages, settings)
        else:
            raise HTTPException(
                status_code=503,
                detail="LLM service unavailable. Please configure the inference endpoint.",
            )

    return ChatResponse(response=response_text, document_id=request.document_id)


@app.post("/chat/summarize", response_model=SummaryResponse, tags=["Chat"])
async def summarize_document(request: SummarizeRequest):
    """Generate a brief summary of an incident."""
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

    prompt = f"""Summarize this police incident in 2-3 bullet points. Focus on: what happened, where, and the outcome.

Incident Type: {document.get('incident_type', 'Unknown')}
Location: {document.get('address_block', 'Unknown')}, {document.get('district', '')} District
Resolution: {document.get('resolution', 'Unknown')}

Narrative:
{document.get('narrative', 'No narrative available.')}

Provide a brief summary:"""

    try:
        inference_resp = await es_client.inference.inference(
            inference_id=settings.llm_inference_id,
            body={"input": prompt},
        )
        summary = inference_resp.get("completion", [{}])[0].get("result", "Unable to generate summary.")
    except Exception as e:
        logger.warning(f"Summarize failed: {e}")
        # Generate a simple extractive summary as fallback
        narrative = document.get("narrative", "")
        summary = f"• {document.get('incident_type', 'Incident')} at {document.get('address_block', 'unknown location')}\n"
        summary += f"• Resolution: {document.get('resolution', 'Unknown')}\n"
        if document.get("arrest_made"):
            summary += "• Arrest was made"
        elif document.get("injuries_reported"):
            summary += "• Injuries were reported"

    return SummaryResponse(summary=summary, document_id=request.document_id)


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
    """Call LLM directly via OpenAI-compatible API."""
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
