"""
API models and schemas for requests/responses
Extended with: confidence judgment, eval, temporal, GoT, community endpoints
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime


# Authentication
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    scopes: List[str] = ["read", "write"]
    tenant_id: Optional[str] = None  # Gap #7

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Document Upload
class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    size_bytes: int
    task_id: Optional[str] = None
    message: str


class ScrapeRequest(BaseModel):
    url: str

class CrawlRequest(BaseModel):
    url: str
    max_depth: Optional[int] = 1
    max_pages: Optional[int] = 10


# Ingestion
class IngestionStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None


# Document List
class DocumentInfo(BaseModel):
    id: str
    filename: str
    file_type: str
    size_bytes: int
    upload_date: str


class DocumentListResponse(BaseModel):
    documents: List[DocumentInfo]
    total: int


# ── Query ─────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., description="User query")
    top_k: Optional[int] = Field(5, description="Number of results to retrieve")
    streaming: Optional[bool] = Field(False, description="Enable streaming responses")
    document_id: Optional[str] = Field(None, description="Filter query to a specific document")
    conversation_id: Optional[str] = Field(None, description="Persist memory in a conversation thread")
    # Gap #6 — GoT mode
    use_got: Optional[bool] = Field(False, description="Enable Graph-of-Thought parallel exploration")
    # Gap #5 — Temporal filter
    at_time: Optional[datetime] = Field(None, description="Query knowledge graph state at this time")


class ConfidenceJudgmentResponse(BaseModel):
    """Gap #4 — LLM-as-a-Judge response shape"""
    score: float
    reasoning: str
    grounded_claims: int
    ungrounded_claims: int
    hallucination_risk: Literal["low", "medium", "high"]


class QueryResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    reasoning_chain: List[str]
    confidence: float
    # Gap #4 — real confidence breakdown
    confidence_judgment: Optional[ConfidenceJudgmentResponse] = None
    retrieval_method: str
    processing_time_seconds: float
    conversation_id: Optional[str] = None
    # Gap #3 — DRIFT metadata
    drift_expanded: Optional[bool] = False
    total_sub_queries: Optional[int] = 1


# Conversations Memory
class Message(BaseModel):
    id: str
    role: str
    content: str
    reasoning: Optional[List[str]] = None
    sources: Optional[List[Dict[str, Any]]] = None
    confidence: Optional[float] = None
    hallucination_risk: Optional[str] = None
    created_at: str

class Conversation(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: Optional[List[Message]] = []

class ConversationListResponse(BaseModel):
    conversations: List[Conversation]


# Ontology
class OntologyResponse(BaseModel):
    version: str
    entity_types: List[str]
    relationship_types: List[str]
    properties: Dict[str, List[str]]
    created_at: datetime
    approved: bool


class OntologyUpdateRequest(BaseModel):
    entity_types: Optional[List[str]] = None
    relationship_types: Optional[List[str]] = None
    properties: Optional[Dict[str, List[str]]] = None
    approved: Optional[bool] = None


# Graph Visualization
class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    description: Optional[str] = None
    properties: Dict[str, Any] = {}
    community_id: Optional[int] = None   # Gap #2
    valid_from: Optional[str] = None     # Gap #5
    valid_until: Optional[str] = None    # Gap #5


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    properties: Dict[str, Any] = {}
    valid_from: Optional[str] = None     # Gap #5
    confidence: Optional[float] = None


class EntityUpdateRequest(BaseModel):
    name: str


class GraphVisualizationResponse(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]


# System Status
class SystemHealthResponse(BaseModel):
    status: str
    version: str
    neo4j_connected: bool
    redis_connected: bool
    workers_active: int
    timestamp: datetime


class SystemStatsResponse(BaseModel):
    documents_count: int
    entities_count: int
    relationships_count: int
    chunks_count: int
    ontology_version: str


# Ontology refinement
class OntologyRefineRequest(BaseModel):
    feedback: Optional[str] = Field(None, description="Human feedback to guide LLM refinement")
    document_id: Optional[str] = Field(None, description="Specific document ID to source chunks from")


class OntologyRefineResponse(BaseModel):
    version: str
    entity_types: List[str]
    relationship_types: List[str]
    properties: Dict[str, List[str]]
    created_at: datetime
    approved: bool
    changes: Optional[str] = None


# Entity deduplication
class DeduplicateResponse(BaseModel):
    merged_count: int
    groups: List[List[str]]


# ── Gap #8: Eval / Quality Dashboard ─────────────────────────────────────────

class EvalRequest(BaseModel):
    """Request to run quality evaluation on a Q&A pair"""
    question: str = Field(..., description="The question that was asked")
    answer: str = Field(..., description="The answer that was generated")
    contexts: List[str] = Field(..., description="Retrieved chunk texts used to answer")
    ground_truth: Optional[str] = Field(None, description="Known correct answer (optional)")
    document_id: Optional[str] = None


class EvalResponse(BaseModel):
    """Evaluation metrics for a Q&A pair"""
    question: str
    faithfulness: float = Field(..., description="0-1: Is answer grounded in contexts?")
    answer_relevancy: float = Field(..., description="0-1: Does answer address the question?")
    context_precision: float = Field(..., description="0-1: Are retrieved chunks relevant?")
    context_recall: float = Field(default=0.0, description="0-1: Did we retrieve enough info?")
    overall_score: float = Field(..., description="0-1: Weighted overall quality score")
    hallucination_detected: bool
    eval_id: Optional[str] = None  # Neo4j node ID for trending


class EvalTrendPoint(BaseModel):
    """Single data point for eval trending chart"""
    timestamp: str
    overall_score: float
    faithfulness: float
    answer_relevancy: float
    hallucination_detected: bool
    document_id: Optional[str] = None


class EvalDashboardResponse(BaseModel):
    """Full eval dashboard data"""
    total_evaluations: int
    avg_overall_score: float
    avg_faithfulness: float
    avg_relevancy: float
    hallucination_rate: float
    trend_data: List[EvalTrendPoint]


# ── Gap #2: Community endpoints ───────────────────────────────────────────────

class CommunityAssignResponse(BaseModel):
    """Response from community assignment task"""
    communities_found: int
    message: str


class CommunitySummaryResponse(BaseModel):
    """Summary of a graph community"""
    community_id: int
    entity_count: int
    entities: List[str]
    summary: str
    themes: List[str] = []


# ── Gap #9: Extended format upload ───────────────────────────────────────────

class SupportedFormatsResponse(BaseModel):
    """List of supported ingestion file formats"""
    formats: List[str]
    descriptions: Dict[str, str]


# ── MiroFish Point 1: Graph Memory Updater ────────────────────────────────────

class GraphUpdateRequest(BaseModel):
    """Request to merge text directly into the live knowledge graph"""
    text: str = Field(..., description="Raw text to extract entities/relationships from")
    source_label: Optional[str] = Field(
        "api_push",
        description="Traceability tag e.g. 'api_push', 'chat:conv_123'"
    )
    valid_from: Optional[datetime] = Field(
        None,
        description="Timestamp for temporal graph edges (default: now)"
    )


class GraphUpdateResponse(BaseModel):
    """Response from a graph memory update operation"""
    entities_added: int
    relationships_added: int
    entities_merged: int
    source_label: str
    timestamp: datetime
    message: str


# ── MiroFish Point 2: Entity Enricher ────────────────────────────────────────

class EnrichmentStatusResponse(BaseModel):
    """Response from entity enrichment task"""
    entities_enriched: int
    entities_skipped: int
    errors: int
    duration_seconds: float
    message: str


class EntitySummaryResponse(BaseModel):
    """Entity profile summary returned from the graph"""
    entity_name: str
    entity_type: Optional[str] = None
    summary: Optional[str] = None
    summary_updated_at: Optional[str] = None
    has_summary: bool = False


# ── MiroFish Point 3: Report Agent ───────────────────────────────────────────

class ReportRequest(BaseModel):
    """Request to generate an analytical report"""
    topic: str = Field(..., description="High-level topic or question for analysis")
    report_type: Optional[Literal["executive", "detailed", "entity_focus"]] = Field(
        "detailed",
        description="'executive' (short), 'detailed' (full), 'entity_focus' (scoped to one entity)"
    )
    target_entity: Optional[str] = Field(
        None,
        description="For entity_focus — name of the entity to focus the report on"
    )


class ReportResponse(BaseModel):
    """Analytical report generated by the ReACT ReportAgent"""
    topic: str
    executive_summary: str
    sections: Dict[str, str]
    key_entities: List[str]
    confidence: float
    tool_calls_made: int
    generated_at: datetime
    markdown: str


# ── MiroFish Point 3b: Entity Interview ──────────────────────────────────────

class EntityChatRequest(BaseModel):
    """Request to chat with a single entity's knowledge neighborhood"""
    message: str = Field(..., description="Question to ask about the entity")
    conversation_id: Optional[str] = Field(
        None, description="Optional conversation ID for multi-turn context"
    )


class EntityChatResponse(BaseModel):
    """Response from entity-scoped chat"""
    response: str
    entity_name: str
    neighborhood_size: int
    conversation_id: str


# ── MiroFish Point 4: Ontology Drift Detection ───────────────────────────────

class DriftReportResponse(BaseModel):
    """Schema drift report from OntologyDriftDetector"""
    id: str
    detected_at: datetime
    new_entity_types: List[str]
    new_relationship_types: List[str]
    removed_entity_types: List[str]
    removed_relationship_types: List[str]
    sample_size: int
    drift_score: float
    status: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class DriftListResponse(BaseModel):
    """List of drift reports"""
    reports: List[DriftReportResponse]
    total: int
