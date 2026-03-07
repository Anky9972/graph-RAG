"""
API models and schemas for requests/responses
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# Authentication
class LoginRequest(BaseModel):
    username: str
    password: str


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


# Query
class QueryRequest(BaseModel):
    query: str = Field(..., description="User query")
    top_k: Optional[int] = Field(5, description="Number of results to retrieve")
    streaming: Optional[bool] = Field(False, description="Enable streaming responses")
    document_id: Optional[str] = Field(None, description="Filter query to a specific document")


class QueryResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    reasoning_chain: List[str]
    confidence: float
    retrieval_method: str
    processing_time_seconds: float


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
    properties: Dict[str, Any] = {}


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    properties: Dict[str, Any] = {}


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
