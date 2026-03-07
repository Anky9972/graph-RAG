"""
Configuration management for Graph RAG Service
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List
from pathlib import Path


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow"
    )
    
    # Application
    app_name: str = "Graph RAG Service"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "development"
    
    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4
    
    # Security
    secret_key: str = "change-this-in-production-to-a-secure-random-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # Neo4j Configuration
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"
    
    # Redis Configuration
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    
    # Celery Configuration
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    
    # LLM Configuration
    default_llm_provider: str = "ollama"  # ollama, openai, anthropic, gemini
    
    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4"
    
    # Anthropic
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4"
    
    # Google Gemini
    google_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"
    
    # LlamaCloud (for LlamaParse)
    llama_cloud_api_key: Optional[str] = None
    use_llama_parse: bool = True  # Use LlamaParse for PDF extraction
    
    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "deepseek-v3.1:671b-cloud"
    ollama_embedding_model: str = "nomic-embed-text"
    
    # Embedding Configuration
    embedding_provider: str = "ollama"  # ollama, openai
    embedding_dimension: int = 768  # nomic-embed-text dimension
    
    # Ingestion Configuration
    chunk_size: int = 1024
    chunk_overlap: int = 200
    max_concurrent_extractions: int = 2
    
    # Ontology Configuration
    ontology_version: str = "v1.0"
    enable_ontology_evolution: bool = True
    entity_resolution_threshold: float = 0.85
    
    # Agent Configuration
    max_agent_iterations: int = 5
    agent_timeout_seconds: int = 30
    enable_hallucination_guard: bool = True
    
    # Retrieval Configuration
    default_top_k: int = 5
    vector_search_similarity_threshold: float = 0.7
    graph_max_depth: int = 3
    enable_semantic_cache: bool = True
    cache_ttl_seconds: int = 3600
    
    # File Upload Configuration
    max_upload_size_mb: int = 100
    allowed_file_types: List[str] = [".pdf", ".txt", ".md", ".docx"]
    upload_dir: Path = Path("data/uploads")
    
    # Observability
    enable_tracing: bool = True
    enable_metrics: bool = True
    log_level: str = "INFO"
    otel_exporter_endpoint: Optional[str] = None
    
    @property
    def redis_url(self) -> str:
        """Construct Redis URL"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
    
    def get_llm_config(self, provider: Optional[str] = None) -> dict:
        """Get LLM configuration for specified provider"""
        provider = provider or self.default_llm_provider
        
        configs = {
            "openai": {
                "api_key": self.openai_api_key,
                "model": self.openai_model,
            },
            "anthropic": {
                "api_key": self.anthropic_api_key,
                "model": self.anthropic_model,
            },
            "gemini": {
                "api_key": self.google_api_key,
                "model": self.gemini_model,
            },
            "ollama": {
                "base_url": self.ollama_base_url,
                "model": self.ollama_model,
            },
        }
        
        return configs.get(provider, configs["ollama"])


# Global settings instance
settings = Settings()
