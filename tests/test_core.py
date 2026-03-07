"""
Basic tests for core components
"""

import pytest
from src.graph_rag_service.core.models import Entity, Relationship, Chunk


def test_entity_creation():
    """Test creating an entity"""
    entity = Entity(
        name="Lyzr AI",
        type="Company",
        properties={"industry": "AI", "founded": "2023"}
    )
    
    assert entity.name == "Lyzr AI"
    assert entity.type == "Company"
    assert entity.properties["industry"] == "AI"
    assert entity.confidence == 1.0


def test_relationship_creation():
    """Test creating a relationship"""
    rel = Relationship(
        source="Lyzr AI",
        target="OpenAI",
        type="PARTNERS_WITH",
        confidence=0.9
    )
    
    assert rel.source == "Lyzr AI"
    assert rel.target == "OpenAI"
    assert rel.type == "PARTNERS_WITH"
    assert rel.confidence == 0.9


def test_chunk_creation():
    """Test creating a chunk"""
    chunk = Chunk(
        text="Sample text content",
        document_id="doc123",
        chunk_index=0
    )
    
    assert chunk.text == "Sample text content"
    assert chunk.document_id == "doc123"
    assert chunk.chunk_index == 0


@pytest.mark.asyncio
async def test_llm_factory():
    """Test LLM factory creation"""
    from src.graph_rag_service.core.llm_factory import LLMFactory
    
    # Test creating with default provider
    provider = LLMFactory.create()
    assert provider is not None
    assert provider.provider_name in ["ollama", "openai", "anthropic", "gemini"]


def test_config_loading():
    """Test configuration loading"""
    from src.graph_rag_service.config import settings
    
    assert settings.app_name == "Graph RAG Service"
    assert settings.app_version == "0.1.0"
    assert settings.default_llm_provider in ["ollama", "openai", "anthropic", "gemini"]
    assert settings.chunk_size > 0
    assert settings.default_top_k > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
