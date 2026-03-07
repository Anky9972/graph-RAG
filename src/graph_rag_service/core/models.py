"""
Core data models for Graph RAG Service
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
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
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Lyzr AI",
                "type": "Company",
                "properties": {"industry": "AI", "founded": "2023"},
                "confidence": 0.95
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
    
    class Config:
        json_schema_extra = {
            "example": {
                "source": "Lyzr AI",
                "target": "OpenAI",
                "type": "PARTNERS_WITH",
                "confidence": 0.9
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


class QueryResult(BaseModel):
    """Result of a retrieval query"""
    answer: str
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning_chain: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    retrieval_method: str = "hybrid"
    processing_time_seconds: float = 0.0


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
