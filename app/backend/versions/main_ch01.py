"""
Police Incident Search API - Challenge 1 Skeleton Version

This is the "empty" version shown in Challenge 1.
- Keyword search works but returns sample data (index doesn't exist yet)
- Semantic/Hybrid search disabled
- AI features disabled

The 3 sample incidents give users something to see in the UI before real data is loaded.
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime

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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global ES client
es_client: Optional[AsyncElasticsearch] = None

# =============================================================================
# SAMPLE FALLBACK DATA
# These 3 incidents are shown when the index doesn't exist yet
# =============================================================================
SAMPLE_INCIDENTS = [
    {
        "incident_id": "SAMPLE-001",
        "incident_type": "Burglary",
        "incident_subtype": "Residential",
        "severity": "Medium",
        "narrative": "This is a SAMPLE incident for demonstration purposes. In Challenge 3, you'll load 1000 real police incident reports. This burglary report shows the kind of detailed narratives you'll be searching through - descriptions of what happened, where, and when. The semantic search will understand the meaning behind these narratives.",
        "address_block": "1200 Demo Street",
        "district": "Sample District",
        "neighborhood": "Example Heights",
        "resolution": "Pending",
        "incident_datetime": "2024-01-15T14:30:00",
        "report_datetime": "2024-01-15T15:00:00",
        "arrest_made": False,
        "responding_units": 2,
        "injuries_reported": False,
        "weapon_involved": "None",
        "property_damage": True,
        "estimated_loss": 2500.00,
        "victim_count": 1,
        "tags": ["sample", "demo", "residential"],
        "location": {"lat": 37.7749, "lon": -122.4194}
    },
    {
        "incident_id": "SAMPLE-002",
        "incident_type": "Robbery",
        "incident_subtype": "Armed",
        "severity": "High",
        "narrative": "SAMPLE DATA - This armed robbery demonstrates how the app will display high-severity incidents. Once you load real data in Challenge 3, you'll see actual incident narratives that you can search using keywords, semantic meaning, or hybrid search combining both approaches.",
        "address_block": "500 Test Avenue",
        "district": "Demo District",
        "neighborhood": "Tutorial Town",
        "resolution": "Under Investigation",
        "incident_datetime": "2024-01-14T22:15:00",
        "report_datetime": "2024-01-14T22:45:00",
        "arrest_made": False,
        "responding_units": 4,
        "injuries_reported": False,
        "weapon_involved": "Handgun",
        "property_damage": False,
        "estimated_loss": 850.00,
        "victim_count": 1,
        "tags": ["sample", "demo", "armed", "commercial"],
        "location": {"lat": 37.7849, "lon": -122.4094}
    },
    {
        "incident_id": "SAMPLE-003",
        "incident_type": "Vehicle Theft",
        "incident_subtype": "Auto",
        "severity": "Medium",
        "narrative": "SAMPLE INCIDENT - Vehicle theft report showing how location data appears on the map. After Challenge 3, you'll have 1000 incidents with real San Francisco locations displayed on the interactive map. The AI features (Generate Summary, Chat) will be unlocked in later challenges.",
        "address_block": "800 Preview Boulevard",
        "district": "Example District",
        "neighborhood": "Placeholder Park",
        "resolution": "Report Filed",
        "incident_datetime": "2024-01-16T08:00:00",
        "report_datetime": "2024-01-16T09:30:00",
        "arrest_made": False,
        "responding_units": 1,
        "injuries_reported": False,
        "weapon_involved": "None",
        "property_damage": False,
        "estimated_loss": 35000.00,
        "victim_count": 1,
        "tags": ["sample", "demo", "vehicle", "parking-lot"],
        "location": {"lat": 37.7649, "lon": -122.4294}
    }
]


def _get_sample_response(search_type: str = "keyword") -> SearchResponse:
    """Return sample data response when index doesn't exist."""
    hits = []
    for i, incident in enumerate(SAMPLE_INCIDENTS):
        hits.append(SearchHit(
            id=incident["incident_id"],
            score=1.0 - (i * 0.1),  # Descending scores
            source=incident,
            highlight={"narrative": [f"<em>SAMPLE</em> {incident['narrative'][:100]}..."]} if search_type == "keyword" else None
        ))

    return SearchResponse(
        total=len(SAMPLE_INCIDENTS),
        hits=hits,
        search_type=search_type,
        message="Showing SAMPLE data - load real incidents in Challenge 3!"
    )


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
    description="AI-powered search for police incident reports (Skeleton Version)",
    version="0.1.0",
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

        # Check index exists and get doc count
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
    """Get index statistics - returns sample stats if index doesn't exist."""
    settings = get_settings()

    try:
        # Check if index exists first
        index_exists = await es_client.indices.exists(index=settings.elasticsearch_index)

        if not index_exists:
            # Return sample stats
            return StatsResponse(
                total_documents=3,
                incident_types={"Burglary": 1, "Robbery": 1, "Vehicle Theft": 1},
                districts={"Sample District": 1, "Demo District": 1, "Example District": 1},
                resolutions={"Pending": 1, "Under Investigation": 1, "Report Filed": 1},
                avg_estimated_loss=12783.33,
            )

        # Real aggregation query
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
        # Return sample stats on error
        return StatsResponse(
            total_documents=3,
            incident_types={"Burglary": 1, "Robbery": 1, "Vehicle Theft": 1},
            districts={"Sample District": 1, "Demo District": 1, "Example District": 1},
            resolutions={"Pending": 1, "Under Investigation": 1, "Report Filed": 1},
            avg_estimated_loss=12783.33,
        )


@app.get("/features", tags=["Health"])
async def get_features():
    """Get feature flags - all AI features disabled in skeleton version."""
    return {
        "llm_enabled": False,
        "chat_enabled": False,
        "agent_enabled": False,
        "agent_id": None,
        "llm_inference_id": None,
        "skeleton_mode": True,  # Flag to indicate this is the skeleton version
    }


# =============================================================================
# Search Endpoints
# =============================================================================

@app.post("/search/keyword", response_model=SearchResponse, tags=["Search"])
async def keyword_search(request: SearchRequest):
    """
    Keyword search - returns sample data if index doesn't exist.
    """
    settings = get_settings()

    try:
        # Check if index exists
        index_exists = await es_client.indices.exists(index=settings.elasticsearch_index)

        if not index_exists:
            logger.info("Index doesn't exist, returning sample data")
            return _get_sample_response("keyword")

        # Real search query
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

        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return _format_search_response(resp, "keyword")
    except Exception as e:
        logger.error(f"Keyword search failed: {e}")
        # Return sample data on error
        return _get_sample_response("keyword")


@app.post("/search/semantic", response_model=SearchResponse, tags=["Search"])
async def semantic_search(request: SearchRequest):
    """
    Semantic search - LOCKED in skeleton version.
    Returns message explaining this feature needs ELSER + data.
    """
    raise HTTPException(
        status_code=503,
        detail="Semantic search is not available yet. Complete Challenge 2 (Deploy ELSER) and Challenge 3 (Load Data) to enable this feature."
    )


@app.post("/search/hybrid", response_model=SearchResponse, tags=["Search"])
async def hybrid_search(request: HybridSearchRequest):
    """
    Hybrid search - LOCKED in skeleton version.
    You'll implement this in Challenge 6!
    """
    raise HTTPException(
        status_code=503,
        detail="Hybrid search is not available yet. You'll implement this endpoint in Challenge 6!"
    )


@app.post("/search/filtered", response_model=SearchResponse, tags=["Search"])
async def filtered_search(request: FilteredSearchRequest):
    """
    Filtered hybrid search - LOCKED in skeleton version.
    """
    raise HTTPException(
        status_code=503,
        detail="Filtered search is not available yet. Complete the hybrid search challenges first."
    )


# =============================================================================
# Document Endpoints
# =============================================================================

@app.get("/documents/recent", response_model=SearchResponse, tags=["Documents"])
async def get_recent_documents(size: int = Query(default=10, le=100)):
    """Get recent documents - returns sample data if index doesn't exist."""
    settings = get_settings()

    try:
        index_exists = await es_client.indices.exists(index=settings.elasticsearch_index)

        if not index_exists:
            return _get_sample_response("recent")

        query = {
            "query": {"match_all": {}},
            "sort": [{"incident_datetime": {"order": "desc"}}],
            "size": size,
            "_source": {"excludes": ["narrative_semantic"]},
        }

        resp = await es_client.search(index=settings.elasticsearch_index, body=query)
        return _format_search_response(resp, "recent")
    except Exception as e:
        logger.error(f"Recent documents query failed: {e}")
        return _get_sample_response("recent")


@app.get("/documents/{document_id}", tags=["Documents"])
async def get_document(document_id: str):
    """Get a specific document by ID - returns sample if not found."""
    settings = get_settings()

    # Check if it's a sample document ID
    for incident in SAMPLE_INCIDENTS:
        if incident["incident_id"] == document_id:
            return incident

    try:
        resp = await es_client.get(
            index=settings.elasticsearch_index,
            id=document_id,
            source_excludes=["narrative_semantic"],
        )
        return resp["_source"]
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
    except Exception as e:
        logger.error(f"Get document failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents/{document_id}/related", response_model=SearchResponse, tags=["Documents"])
async def get_related_documents(document_id: str, size: int = Query(default=5, le=20)):
    """Get related documents - returns sample data in skeleton version."""
    return _get_sample_response("related")


# =============================================================================
# AI Features - All LOCKED in skeleton version
# =============================================================================

@app.post("/rag/summarize", response_model=SummaryResponse, tags=["RAG"])
async def summarize_document(request: SummarizeRequest):
    """RAG Summarization - LOCKED. You'll build this in Challenge 8!"""
    raise HTTPException(
        status_code=503,
        detail="AI Summarization is not available yet. You'll build this RAG endpoint in Challenge 8!"
    )


@app.post("/chat", response_model=GeneralChatResponse, tags=["Chat"])
async def general_chat(request: GeneralChatRequest):
    """General chat - LOCKED until Challenge 10."""
    raise HTTPException(
        status_code=503,
        detail="Chat is not available yet. Complete the LLM and RAG challenges first."
    )


@app.post("/chat/document", response_model=ChatResponse, tags=["Chat"])
async def document_chat(request: ChatRequest):
    """Document chat - LOCKED until Challenge 10."""
    raise HTTPException(
        status_code=503,
        detail="Document chat is not available yet. Complete the LLM and RAG challenges first."
    )


@app.post("/agent/chat", response_model=AgentChatResponse, tags=["Agent"])
async def agent_chat(request: AgentChatRequest):
    """Agent chat - LOCKED until Challenge 10."""
    raise HTTPException(
        status_code=503,
        detail="AI Agent is not available yet. You'll configure Agent Builder in Challenge 9!"
    )


# =============================================================================
# Helper Functions
# =============================================================================

def _format_search_response(es_response: dict, search_type: str) -> SearchResponse:
    """Format Elasticsearch response into SearchResponse model."""
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
        search_type=search_type,
    )
