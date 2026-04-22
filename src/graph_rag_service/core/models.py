"""
Core data models for Graph RAG Service
Extended with: temporal fields, tenant support, eval/confidence models
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any, Literal
from datetime import datetime
from enum import Enum


class NodeType(str, Enum):
    """Types of nodes in the knowledge graph"""
    ENTITY = "entity"
    CHUNK = "chunk"
    DOCUMENT = "document"


class RelationType(str, Enum):
    """Types of relationships in the knowledge graph"""
    MENTIONS = "MENTIONS"
    RELATED_TO = "RELATED_TO"
    PART_OF = "PART_OF"
    CONTAINS = "CONTAINS"


class OntologyVersion(str, Enum):
    """Ontology versions for schema evolution"""
    V1_0 = "v1.0"
    V1_1 = "v1.1"
    V2_0 = "v2.0"


class Entity(BaseModel):
    """Entity in the knowledge graph"""
    id: Optional[str] = None
    name: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
    ontology_version: str = "v1.0"
    confidence: float = 1.0
    # Temporal support (Gap #5)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    # Tenant support (Gap #7)
    tenant_id: Optional[str] = None
    # Community support (Gap #2)
    community_id: Optional[int] = None

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Lyzr AI",
                "type": "Company",
                "properties": {"industry": "AI", "founded": "2023"},
                "confidence": 0.95,
                "tenant_id": "org_abc123"
            }
        }


class Relationship(BaseModel):
    """Relationship between entities"""
    source: str
    target: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    ontology_version: str = "v1.0"
    # Temporal support (Gap #5)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    source_document_id: Optional[str] = None
    source_chunk_id: Optional[str] = None
    # Tenant support (Gap #7)
    tenant_id: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "source": "Lyzr AI",
                "target": "OpenAI",
                "type": "PARTNERS_WITH",
                "confidence": 0.9,
                "valid_from": "2023-01-01T00:00:00"
            }
        }


class Chunk(BaseModel):
    """Text chunk from document"""
    id: Optional[str] = None
    text: str
    document_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
    chunk_index: int = 0
    # Extended metadata for citation tracing
    page_number: Optional[int] = None
    section_title: Optional[str] = None


class Document(BaseModel):
    """Document metadata"""
    id: Optional[str] = None
    filename: str
    file_type: str
    content: Optional[str] = None
    size_bytes: int
    upload_date: datetime = Field(default_factory=datetime.utcnow)
    processed: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tenant_id: Optional[str] = None


class OntologySchema(BaseModel):
    """Ontology schema definition"""
    version: str = "v1.0"
    entity_types: List[str] = Field(default_factory=list)
    relationship_types: List[str] = Field(default_factory=list)
    properties: Dict[str, List[str]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved: bool = False


class ExtractionResult(BaseModel):
    """Result of entity/relationship extraction"""
    entities: List[Entity] = Field(default_factory=list)
    relationships: List[Relationship] = Field(default_factory=list)
    chunks: List[Chunk] = Field(default_factory=list)
    ontology_version: str = "v1.0"
    processing_time_seconds: float = 0.0


class ConfidenceJudgment(BaseModel):
    """LLM-as-a-Judge confidence assessment (Gap #4)"""
    score: float = Field(..., ge=0.0, le=1.0, description="0.0-1.0 grounding score")
    reasoning: str = Field(default="", description="Why this confidence score was assigned")
    grounded_claims: int = Field(default=0, description="# claims backed by retrieved context")
    ungrounded_claims: int = Field(default=0, description="# claims not traceable to context")
    hallucination_risk: Literal["low", "medium", "high"] = Field(default="low")


class QueryResult(BaseModel):
    """Result of a retrieval query — enriched with confidence judgment"""
    answer: str
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning_chain: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    # Gap #4 — real confidence metrics
    confidence_judgment: Optional[ConfidenceJudgment] = None
    retrieval_method: str = "hybrid"
    processing_time_seconds: float = 0.0
    # Gap #3 — DRIFT query metadata
    drift_expanded: bool = False
    total_sub_queries: int = 1


class AgentState(BaseModel):
    """State of the agentic retrieval system"""
    query: str
    decomposed_queries: List[str] = Field(default_factory=list)
    retrieved_contexts: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning_steps: List[str] = Field(default_factory=list)
    final_answer: Optional[str] = None
    iteration: int = 0
    confidence: float = 0.0


class SearchMethod(str, Enum):
    """Search methods for retrieval"""
    VECTOR = "vector"
    GRAPH = "graph"
    FILTER = "filter"
    HYBRID = "hybrid"
    COMMUNITY = "community"
    CYPHER = "cypher"


class EvalResult(BaseModel):
    """RAG evaluation result (Gap #8)"""
    question: str
    answer: str
    faithfulness: float = Field(..., ge=0.0, le=1.0)
    answer_relevancy: float = Field(..., ge=0.0, le=1.0)
    context_precision: float = Field(..., ge=0.0, le=1.0)
    context_recall: float = Field(default=0.0, ge=0.0, le=1.0)
    overall_score: float = Field(..., ge=0.0, le=1.0)
    hallucination_detected: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    document_id: Optional[str] = None


class CommunityReport(BaseModel):
    """Community summary for LazyGraphRAG (Gap #2)"""
    community_id: int
    entity_count: int
    entities: List[str]
    summary: str
    themes: List[str] = Field(default_factory=list)
    relevance_score: float = 0.0
    generated_at: datetime = Field(default_factory=datetime.utcnow)
