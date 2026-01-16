"""
Police Incident Search API - Challenge 8 Version
=================================================
Phase 3: RAG Summarization

This version includes:
- Everything from Challenge 6 (hybrid search COMPLETED)
- Stats endpoint
- RAG summarize endpoint with TODO placeholders (fill-in-blank exercise)

EXERCISE: Complete the rag_summarize() endpoint by filling in the TODO sections.
Follow the step-by-step instructions in the assignment to build each component.

The RAG pattern:
1. RETRIEVE - Get the document from Elasticsearch
2. AUGMENT - Build a prompt with the document context
3. GENERATE - Call the LLM to produce a summary
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
    SummarizeRequest,
    SearchResponse,
    SearchHit,
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
    es_config = {
        "hosts": [settings.elasticsearch_url],
        "request_timeout": 60,  # 60 seconds for LLM inference calls
    }
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
# Health & Feature Endpoints
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

    ============================================================================
    EXERCISE: Complete this endpoint by filling in the TODO sections below.
    Follow the instructions in the assignment document step by step.
    ============================================================================
    """
    settings = get_settings()

    # Check feature flags
    if not settings.llm_enabled:
        raise HTTPException(
            status_code=403,
            detail="LLM not enabled. Set LLM_ENABLED=true in .env"
        )
    if not settings.rag_enabled:
        raise HTTPException(
            status_code=403,
            detail="RAG not enabled. Complete the exercise below, then set RAG_ENABLED=true in .env"
        )

    # =========================================================================
    # Step 1: RETRIEVE - Get the document from Elasticsearch
    # =========================================================================
    # We need to fetch the incident document that the user wants summarized.
    # The document_id comes from the request.
    #
    # TODO: Retrieve the document using es_client.get()
    # Hint: Use request.document_id as the document ID
    #
    try:
        doc_resp = None  # YOUR CODE HERE - Replace with es_client.get() call
        # Example:
        # doc_resp = await es_client.get(
        #     index=settings.elasticsearch_index,
        #     id=request.document_id,
        #     source_excludes=["narrative_semantic"],
        # )

        if doc_resp is None:
            raise HTTPException(
                status_code=500,
                detail="Step 1 incomplete: Add the es_client.get() call to retrieve the document"
            )
        document = doc_resp["_source"]
    except NotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Document {request.document_id} not found"
        )

    # =========================================================================
    # Step 2: AUGMENT - Build the prompt with document context
    # =========================================================================
    # This is where RAG differs from basic LLM calls - we inject real data
    # into the prompt so the LLM can generate a grounded response.
    #
    # TODO: Build a prompt string that includes:
    # - Instructions for the LLM (what kind of summary to produce)
    # - The incident details (type, location, resolution)
    # - The narrative text from the document
    #
    prompt = ""  # YOUR CODE HERE - Build the prompt string
    # Example:
    # prompt = f"""Summarize this police incident in 2-3 bullet points. Focus on: what happened, where, and the outcome.
    #
    # Incident Type: {document.get('incident_type', 'Unknown')}
    # Location: {document.get('address_block', 'Unknown')}, {document.get('district', '')} District
    # Resolution: {document.get('resolution', 'Unknown')}
    #
    # Narrative:
    # {document.get('narrative', 'No narrative available.')}
    #
    # Provide a brief summary:"""

    if not prompt:
        raise HTTPException(
            status_code=500,
            detail="Step 2 incomplete: Build the prompt string with document context"
        )

    # =========================================================================
    # Step 3: GENERATE - Call the LLM via Elasticsearch Inference API
    # =========================================================================
    # Now we send our augmented prompt to the LLM. Elasticsearch's Inference
    # API handles the connection to the configured LLM (RedHat Granite).
    #
    # TODO: Call the LLM using es_client.inference.inference()
    # Hint: Use settings.llm_inference_id as the model_id
    #
    try:
        inference_resp = None  # YOUR CODE HERE - Replace with inference API call
        # Example:
        # inference_resp = await es_client.inference.inference(
        #     model_id=settings.llm_inference_id,
        #     task_type="completion",
        #     input=prompt,
        # )

        if inference_resp is None:
            raise HTTPException(
                status_code=500,
                detail="Step 3 incomplete: Add the es_client.inference.inference() call"
            )

        summary = inference_resp.get("completion", [{}])[0].get("result", "Unable to generate summary.")
    except Exception as e:
        logger.warning(f"LLM summarize failed: {e}")
        # Fallback to extractive summary if LLM fails
        summary = f"- {document.get('incident_type', 'Incident')} at {document.get('address_block', 'unknown location')}\n"
        summary += f"- Resolution: {document.get('resolution', 'Unknown')}\n"
        if document.get("arrest_made"):
            summary += "- Arrest was made"
        elif document.get("injuries_reported"):
            summary += "- Injuries were reported"

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
