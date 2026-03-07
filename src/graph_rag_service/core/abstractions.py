"""
Abstract base classes for pluggable components
Ensures no vendor lock-in and easy extensibility
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from .models import Entity, Relationship, Chunk


class GraphStore(ABC):
    """Abstract interface for graph database operations"""
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to graph database"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to graph database"""
        pass
    
    @abstractmethod
    async def create_node(self, entity: Entity) -> str:
        """
        Create a node in the graph
        
        Args:
            entity: Entity to create
            
        Returns:
            ID of created node
        """
        pass
    
    @abstractmethod
    async def create_relationship(self, relationship: Relationship) -> str:
        """
        Create a relationship between nodes
        
        Args:
            relationship: Relationship to create
            
        Returns:
            ID of created relationship
        """
        pass
    
    @abstractmethod
    async def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute a raw query (Cypher for Neo4j, Gremlin for Neptune)
        
        Args:
            query: Query string
            params: Query parameters
            
        Returns:
            Query results
        """
        pass
    
    @abstractmethod
    async def find_path(self, source: str, target: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        """
        Find paths between two entities
        
        Args:
            source: Source entity name
            target: Target entity name
            max_depth: Maximum path depth
            
        Returns:
            List of paths
        """
        pass
    
    @abstractmethod
    async def get_neighbors(self, entity_name: str, depth: int = 1) -> List[Dict[str, Any]]:
        """
        Get neighboring entities
        
        Args:
            entity_name: Entity to get neighbors for
            depth: Traversal depth
            
        Returns:
            List of neighboring entities and relationships
        """
        pass
    
    @abstractmethod
    async def merge_entities(self, entity1_id: str, entity2_id: str) -> str:
        """
        Merge duplicate entities
        
        Args:
            entity1_id: First entity ID
            entity2_id: Second entity ID (will be merged into first)
            
        Returns:
            ID of merged entity
        """
        pass


class VectorStore(ABC):
    """Abstract interface for vector database operations"""
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to vector store"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to vector store"""
        pass
    
    @abstractmethod
    async def add_vectors(
        self,
        vectors: List[List[float]],
        metadata: List[Dict[str, Any]],
        ids: Optional[List[str]] = None
    ) -> List[str]:
        """
        Add vectors to the store
        
        Args:
            vectors: List of embedding vectors
            metadata: Metadata for each vector
            ids: Optional IDs for vectors
            
        Returns:
            List of vector IDs
        """
        pass
    
    @abstractmethod
    async def search(
        self,
        query_vector: List[float],
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors
        
        Args:
            query_vector: Query embedding
            k: Number of results
            filter: Metadata filters
            
        Returns:
            List of similar items with scores
        """
        pass
    
    @abstractmethod
    async def delete_vectors(self, ids: List[str]) -> None:
        """
        Delete vectors by ID
        
        Args:
            ids: Vector IDs to delete
        """
        pass


class LLMProvider(ABC):
    """Abstract interface for LLM operations"""
    
    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        Generate completion from prompt
        
        Args:
            prompt: User prompt
            system_prompt: System prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated text
        """
        pass
    
    @abstractmethod
    async def complete_structured(
        self,
        prompt: str,
        response_model: type,
        system_prompt: Optional[str] = None
    ) -> Any:
        """
        Generate structured output conforming to a model
        
        Args:
            prompt: User prompt
            response_model: Pydantic model for response
            system_prompt: System prompt
            
        Returns:
            Parsed response as response_model instance
        """
        pass
    
    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """
        Generate embedding for text
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector
        """
        pass
    
    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        pass


class EntityResolver(ABC):
    """Abstract interface for entity resolution"""
    
    @abstractmethod
    async def resolve(
        self,
        entities: List[Entity],
        threshold: float = 0.85
    ) -> Dict[str, List[Entity]]:
        """
        Resolve and deduplicate entities
        
        Args:
            entities: List of entities to resolve
            threshold: Similarity threshold for matching
            
        Returns:
            Dictionary mapping canonical entity to duplicates
        """
        pass
    
    @abstractmethod
    async def compute_similarity(self, entity1: Entity, entity2: Entity) -> float:
        """
        Compute similarity between two entities
        
        Args:
            entity1: First entity
            entity2: Second entity
            
        Returns:
            Similarity score (0-1)
        """
        pass
