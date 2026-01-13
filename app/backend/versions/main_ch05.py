"""
Police Incident Search API - Challenge 5 Version
=================================================
Phase 1: Basic Search Capabilities

This version includes:
- Health check and feature flags
- Keyword search (BM25)
- Semantic search (ELSER)
- Document retrieval
- Map data endpoints

Hybrid search endpoint is present but DISABLED.
Enable it in Challenge 6 by building the RRF query.
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
    SearchResponse,
    SearchHit,
    HealthResponse,
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
# Health & Feature Endpoints
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Check API and Elasticsearch health."""
    settings = get_settings()

    try:
        # For Serverless, check connectivity by getting index info
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


@app.get("/features", tags=["Health"])
async def get_features():
    """
    Get feature flags for the frontend.

    Returns which features are enabled based on environment configuration.
    """
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
async def hybrid_search(request: SearchRequest):
    """
    Hybrid search combining keyword and semantic using RRF.

    NOTE: This endpoint is DISABLED in Challenge 5.
    You will build this functionality in Challenge 6!
    """
    settings = get_settings()

    # Feature flag check
    if not settings.hybrid_enabled:
        raise HTTPException(
            status_code=403,
            detail="Hybrid search not enabled. Complete Challenge 6 to enable this feature. Set HYBRID_ENABLED=true in .env after completing the exercise."
        )

    # This code won't run until HYBRID_ENABLED=true
    raise HTTPException(
        status_code=501,
        detail="Hybrid search implementation pending. Complete Challenge 6."
    )


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
    """
    Get documents with location data for map display.

    Returns incidents with lat/lon coordinates for plotting on a map.
    """
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
