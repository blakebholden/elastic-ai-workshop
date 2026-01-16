"""Pydantic models for API requests and responses."""
from typing import Optional, List, Any
from pydantic import BaseModel, Field
from datetime import datetime


# =============================================================================
# Request Models
# =============================================================================

class SearchRequest(BaseModel):
    """Base search request."""
    query: str = Field(..., description="Search query text")
    size: int = Field(default=10, ge=1, le=100, description="Number of results")
    from_: int = Field(default=0, ge=0, alias="from", description="Offset for pagination")


class FilteredSearchRequest(SearchRequest):
    """Search with filters."""
    filters: Optional[dict] = Field(default=None, description="Filter criteria")


class HybridSearchRequest(SearchRequest):
    """Hybrid search with weight control."""
    keyword_weight: float = Field(default=0.3, ge=0, le=1, description="Weight for keyword search")
    semantic_weight: float = Field(default=0.7, ge=0, le=1, description="Weight for semantic search")


class ChatRequest(BaseModel):
    """Chat with document context."""
    document_id: str = Field(..., description="Document ID for context")
    message: str = Field(..., description="User message")
    chat_history: List[dict] = Field(default=[], description="Previous messages")
    conversation_id: Optional[str] = Field(default=None, description="Conversation ID for multi-turn")


class SummarizeRequest(BaseModel):
    """Request document summary."""
    document_id: str = Field(..., description="Document ID to summarize")


class GeneralChatRequest(BaseModel):
    """General chat request (not document-specific)."""
    message: str = Field(..., description="User message")
    chat_history: List[dict] = Field(default=[], description="Previous messages")
    max_context: int = Field(default=5, ge=1, le=10, description="Max documents for context")


class AgentChatRequest(BaseModel):
    """Agent Builder chat request."""
    message: str = Field(..., description="User message to the agent")
    conversation_id: Optional[str] = Field(default=None, description="Conversation ID for multi-turn")


# =============================================================================
# Response Models
# =============================================================================

class IncidentSource(BaseModel):
    """Police incident document source."""
    incident_id: str
    incident_datetime: Optional[datetime] = None
    incident_type: Optional[str] = None
    incident_subtype: Optional[str] = None
    severity: Optional[str] = None
    narrative: Optional[str] = None
    address_block: Optional[str] = None
    district: Optional[str] = None
    neighborhood: Optional[str] = None
    resolution: Optional[str] = None
    arrest_made: Optional[bool] = None
    injuries_reported: Optional[bool] = None
    weapon_involved: Optional[str] = None
    estimated_loss: Optional[float] = None
    victim_count: Optional[int] = None
    tags: Optional[List[str]] = None

    class Config:
        extra = "allow"


class SearchHit(BaseModel):
    """Single search result."""
    id: str
    score: Optional[float] = None
    source: dict
    highlight: Optional[dict] = None


class SearchResponse(BaseModel):
    """Search results response."""
    total: int
    hits: List[SearchHit]
    took_ms: Optional[int] = None
    search_type: str


class ChatResponse(BaseModel):
    """Chat response."""
    response: str
    document_id: str
    conversation_id: Optional[str] = Field(default=None, description="Conversation ID for multi-turn")


class GeneralChatResponse(BaseModel):
    """General chat response."""
    response: str
    sources: List[str] = Field(default=[], description="Source incident IDs")
    source_count: int = Field(default=0, description="Number of sources used")


class ToolCall(BaseModel):
    """Agent tool execution details."""
    tool: str = Field(..., description="Tool name that was executed")
    parameters: dict = Field(default={}, description="Parameters passed to the tool")
    result: Optional[Any] = Field(default=None, description="Tool execution result")


class AgentChatResponse(BaseModel):
    """Agent Builder chat response."""
    response: str = Field(..., description="Agent's generated response")
    tool_calls: List[ToolCall] = Field(default=[], description="Tools executed by the agent")
    sources: List[str] = Field(default=[], description="Referenced incident IDs")
    conversation_id: Optional[str] = Field(default=None, description="Conversation ID for multi-turn")


class SummaryResponse(BaseModel):
    """Document summary response."""
    summary: str
    document_id: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    elasticsearch: dict
    index: dict


class StatsResponse(BaseModel):
    """Index statistics response."""
    total_documents: int
    incident_types: dict
    districts: dict
    resolutions: dict
    avg_estimated_loss: float
