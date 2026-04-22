"""
Configuration management for Graph RAG Service
Extended with: temporal, multi-tenant, eval, semantic-cache, hybrid search, GoT settings
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
    app_version: str = "2.0.0"
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
    use_llama_parse: bool = True

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

    # ── Gap #1: Hybrid BM25 + Vector ──────────────────────────────────────────
    enable_hybrid_search: bool = True
    hybrid_bm25_weight: float = 0.3      # weight for BM25 in RRF fusion
    hybrid_vector_weight: float = 0.7    # weight for vector in RRF fusion
    rrf_k: int = 60                      # RRF ranking constant

    # ── Gap #2: Community Summaries (LazyGraphRAG) ────────────────────────────
    enable_community_search: bool = True
    community_summary_cache_ttl: int = 7200     # 2 hours in Redis
    max_community_entities: int = 50

    # ── Gap #3: DRIFT-style Query Expansion ───────────────────────────────────
    enable_drift_expansion: bool = True
    drift_expansion_threshold: float = 0.5     # confidence below this triggers drift
    max_drift_expansions: int = 2

    # ── Gap #4: LLM-as-a-Judge ────────────────────────────────────────────────
    enable_llm_judge: bool = True
    judge_temperature: float = 0.0

    # ── Gap #5: Temporal Knowledge Graph ─────────────────────────────────────
    enable_temporal_store: bool = True
    temporal_default_validity_days: int = 3650  # ~10 years default

    # ── Gap #6: Graph-of-Thought Parallel Exploration ─────────────────────────
    enable_graph_of_thought: bool = True
    got_parallel_timeout: float = 20.0          # seconds before parallel search aborts

    # ── Gap #7: Multi-Tenant ──────────────────────────────────────────────────
    enable_multi_tenant: bool = True
    default_tenant_id: str = "default"

    # ── Gap #8: Semantic Query Cache ─────────────────────────────────────────
    enable_semantic_cache: bool = True
    cache_ttl_seconds: int = 3600
    cache_similarity_threshold: float = 0.95   # cosine similarity for cache hit

    # ── Gap #9: Extended Ingestion Formats ───────────────────────────────────
    allowed_file_types: List[str] = [
        ".pdf", ".txt", ".md", ".docx",
        ".csv", ".xlsx", ".pptx", ".json"   # NEW
    ]

    # Retrieval Configuration
    default_top_k: int = 5
    vector_search_similarity_threshold: float = 0.7
    graph_max_depth: int = 3

    # File Upload Configuration
    max_upload_size_mb: int = 100
    upload_dir: Path = Path("data/uploads").resolve()

    # Observability
    enable_tracing: bool = False
    enable_metrics: bool = False
    log_level: str = "INFO"
    otel_exporter_endpoint: Optional[str] = None

    # ── MiroFish Point 2: Entity Enricher ─────────────────────────────────────
    entity_enrichment_min_connections: int = 1   # min graph degree to qualify
    entity_enrichment_batch_size: int = 20       # entities per LLM batch

    # ── MiroFish Point 4: Ontology Drift Detection ────────────────────────────
    enable_ontology_evolution: bool = True        # flag was defined; now wired
    drift_sample_size: int = 10                  # random chunks to re-sample
    drift_detection_schedule: str = "0 3 * * *" # cron: daily at 3 AM


    @property
    def redis_url(self) -> str:
        """Construct Redis URL"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def model_post_init(self, __context):
        """Fallback to local Ollama if cloud API keys are missing"""
        if self.default_llm_provider == "gemini" and not self.google_api_key:
            print("WARNING: No GOOGLE_API_KEY found. Falling back to Ollama for LLM.")
            self.default_llm_provider = "ollama"

        if self.embedding_provider == "gemini" and not self.google_api_key:
            print("WARNING: No GOOGLE_API_KEY found. Falling back to Ollama for embeddings.")
            self.embedding_provider = "ollama"

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
