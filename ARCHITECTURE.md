# Graph RAG Service - Project Documentation

## System Architecture

### Overview
The Graph RAG Service is built as a modular, production-grade platform with the following key components:

1. **API Gateway (FastAPI)**: Handles all HTTP requests, authentication, and routing
2. **Ingestion Pipeline**: Processes documents and constructs knowledge graphs
3. **Retrieval Agent (LangGraph)**: Intelligent query routing and response synthesis
4. **Storage Layer**: Neo4j for graph + vector storage
5. **Task Queue**: Celery + Redis for async processing
6. **Observability**: OpenTelemetry for tracing and metrics

### Design Principles

#### 1. No Vendor Lock-in
All core components are abstracted behind interfaces:
- `GraphStore`: Can swap Neo4j for AWS Neptune
- `VectorStore`: Supports multiple vector databases
- `LLMProvider`: Works with any LLM (OpenAI, Anthropic, Gemini, Ollama)

#### 2. Production-Ready
- **Async Processing**: Non-blocking I/O for all database operations
- **Background Jobs**: Celery workers handle heavy ingestion tasks
- **Authentication**: JWT-based with RBAC support
- **Error Handling**: Graceful degradation and fallback mechanisms
- **Observability**: Full tracing and metrics collection

#### 3. Intelligent Retrieval
The agentic system:
- Decomposes complex queries into sub-queries
- Dynamically selects retrieval methods (vector vs graph vs cypher)
- Validates outputs against schema (hallucination guard)
- Provides reasoning chains for transparency

## Components Deep Dive

### Core Abstractions (`src/graph_rag_service/core/`)

#### GraphStore Interface
```python
class GraphStore(ABC):
    @abstractmethod
    async def create_node(entity: Entity) -> str
    @abstractmethod
    async def create_relationship(relationship: Relationship) -> str
    @abstractmethod
    async def execute_query(query: str, params: dict) -> List[dict]
    @abstractmethod
    async def find_path(source: str, target: str, max_depth: int) -> List[dict]
```

Implementation: `Neo4jStore` provides unified graph + vector storage using Neo4j 5.x vector capabilities.

#### LLMProvider Interface
```python
class LLMProvider(ABC):
    @abstractmethod
    async def complete(prompt: str, **kwargs) -> str
    @abstractmethod
    async def embed(text: str) -> List[float]
```

Implementation: `UnifiedLLMProvider` wraps OpenAI, Anthropic, Gemini, and Ollama with a consistent interface.

#### Entity Resolution
Multi-stage resolution:
1. **Blocking**: Group by entity type and name similarity (fast reject)
2. **Semantic Check**: Compare embeddings for deep similarity
3. **Threshold Matching**: Configurable thresholds (0.85 default)
4. **Auto-merge**: High confidence merges (>0.95)
5. **Human Review Queue**: Medium confidence flagged for review (0.85-0.95)

### Ingestion Pipeline (`src/graph_rag_service/ingestion/`)

#### Flow
1. **Document Processing**: Extract text from PDF/TXT/MD/DOCX
2. **Chunking**: Split into overlapping chunks (1024 tokens, 200 overlap)
3. **Ontology Generation**: LLM analyzes samples to propose entity/relationship types
4. **Entity Extraction**: Extract entities and relationships per chunk
5. **Entity Resolution**: Deduplicate and merge entities
6. **Embedding Generation**: Create vector embeddings (BGE-M3)
7. **Graph Construction**: Store in Neo4j with hybrid nodes

#### Hybrid Nodes
Each chunk is stored as both:
- A `(:Chunk)` node with text and embedding
- Connected to `(:Entity)` nodes via `[:MENTIONS]` relationships

This preserves source text for grounding while enabling abstract graph queries.

### Retrieval System (`src/graph_rag_service/retrieval/`)

#### Tools
1. **VectorSearchTool**: Semantic similarity using embeddings
2. **GraphTraversalTool**: Relationship exploration and path finding
3. **CypherGenerationTool**: Text-to-Cypher with validation
4. **MetadataFilterTool**: Structured queries on attributes

#### Agent Workflow (LangGraph)
```
[Query] → [Decompose] → [Route] → [Vector/Graph/Cypher] → [Synthesize] → [Response]
                           ↑                                      ↓
                           └─────────────────────────────────────┘
                                    (Iterative refinement)
```

#### Hallucination Guards
- **Schema Injection**: Prompt includes allowed entity/relationship types
- **Cypher Validation**: Parse and validate against whitelist
- **Self-Correction**: Feed errors back to LLM to fix syntax
- **Fallback**: If graph fails, degrade to vector search

### API Layer (`src/graph_rag_service/api/`)

#### Endpoints
- `POST /api/auth/login`: Get JWT token
- `POST /api/documents/upload`: Upload document (returns task ID)
- `GET /api/documents/status/{task_id}`: Check ingestion progress
- `POST /api/query`: Execute agentic query
- `GET /api/ontology`: Get current ontology schema
- `PUT /api/ontology`: Update ontology (admin only)
- `GET /api/graph/visualization`: Get graph data for visualization
- `GET /api/system/health`: System health check
- `GET /api/system/stats`: System statistics

#### Authentication
- JWT tokens with configurable expiration (default: 30 min)
- RBAC with scopes: `read`, `write`, `admin`
- Dependency injection for protected endpoints

### Workers (`src/graph_rag_service/workers/`)

#### Celery Tasks
- `ingest_document`: Process single document
- `ingest_documents_batch`: Process multiple documents
- `health_check`: Worker health verification

#### Configuration
- Broker: Redis
- Result Backend: Redis
- Serializer: JSON
- Task timeout: 1 hour (configurable)

### Observability (`src/graph_rag_service/observability/`)

#### OpenTelemetry Integration
- **Traces**: Agent reasoning steps, tool calls, database queries
- **Metrics**: 
  - `documents_ingested`: Counter
  - `queries_executed`: Counter
  - `query_duration_seconds`: Histogram
  - `entities_extracted`: Counter

#### Structured Logging
- Log level: INFO (configurable)
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- All async operations logged with context

## Configuration

### Environment Variables
Key settings in `.env`:
- **Neo4j**: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- **Redis**: `REDIS_HOST`, `REDIS_PORT`
- **LLM Provider**: `DEFAULT_LLM_PROVIDER` (openai/anthropic/gemini/ollama)
- **API Keys**: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`
- **Ollama**: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_EMBEDDING_MODEL`
- **Security**: `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`

### Tuning Parameters
- `CHUNK_SIZE`: 1024 (text chunk size)
- `CHUNK_OVERLAP`: 200 (overlap between chunks)
- `MAX_AGENT_ITERATIONS`: 5 (max reasoning steps)
- `AGENT_TIMEOUT_SECONDS`: 30 (query timeout)
- `ENTITY_RESOLUTION_THRESHOLD`: 0.85 (similarity threshold)
- `DEFAULT_TOP_K`: 5 (retrieval results)
- `GRAPH_MAX_DEPTH`: 3 (graph traversal depth)

## Deployment

### Local Development
```bash
# 1. Ensure Neo4j and Redis are running
# 2. Configure .env with connection details

# 3. Start API server
./start-server.sh  # or start-server.bat on Windows

# 4. Start workers
./start-worker.sh  # or start-worker.bat on Windows
```

### Production Considerations
1. **Database**: Use managed Neo4j (Aura) or self-hosted cluster
2. **Redis**: Use managed Redis (AWS ElastiCache, Redis Cloud)
3. **Worker Scaling**: Add more Celery workers based on ingestion load
4. **API Scaling**: Run multiple API instances behind load balancer
5. **Monitoring**: Integrate with Prometheus/Grafana for metrics
6. **Secrets**: Use secret management (AWS Secrets Manager, HashiCorp Vault)

## Extensibility

### Adding New LLM Provider
1. Implement `LLMProvider` interface
2. Add to `LLMFactory.create()` method
3. Update config with new provider settings

### Adding New Graph Database
1. Implement `GraphStore` interface
2. Update `IngestionPipeline` to use new store
3. Test with existing workflows

### Custom Retrieval Tools
1. Create new tool class with `run()` method
2. Add to `AgentRetrievalSystem.tools`
3. Update routing logic in `_route_query()`

## Testing Strategy

### Unit Tests
- Test each component independently
- Mock external dependencies (Neo4j, Redis, LLMs)
- Focus on business logic

### Integration Tests
- Test component interactions
- Use test database instances
- Verify end-to-end flows

### Performance Tests
- Benchmark ingestion throughput
- Measure query latencies
- Stress test with concurrent requests

## Future Enhancements

### Phase 1 (Current MVP)
- ✅ Core ingestion pipeline
- ✅ Agentic retrieval system
- ✅ Multi-LLM support
- ✅ Entity resolution
- ✅ Async workers

### Phase 2 (Next Steps)
- [ ] React frontend with visual ontology editor
- [ ] Graph visualization (D3.js/Cytoscape)
- [ ] Advanced ontology evolution with migrations
- [ ] Semantic cache with Redis
- [ ] Batch ingestion optimization

### Phase 3 (Advanced Features)
- [ ] Multi-tenant support with data isolation
- [ ] Fine-tuned entity extraction models
- [ ] Graph neural network embeddings
- [ ] Automated ontology quality metrics
- [ ] Export/import ontology schemas

## Troubleshooting

### Common Issues

#### Neo4j Connection Failed
- Verify Neo4j is running and accessible
- Verify credentials in `.env`
- Try connecting with cypher-shell: `cypher-shell -u neo4j -p password`

#### Celery Worker Not Processing
- Check Redis is running: `redis-cli ping`
- Verify broker URL in `.env`
- Check worker logs

#### Ollama Models Not Found
- Pull models: `ollama pull llama3.2 && ollama pull bge-m3`
- Verify Ollama is running: `curl http://localhost:11434/api/tags`

#### Query Returns No Results
- Verify documents are ingested: `GET /api/system/stats`
- Check ontology exists: `GET /api/ontology`
- Try simpler queries first

## Support

For issues or questions:
1. Check documentation and troubleshooting guide
2. Search existing GitHub issues
3. Open new issue with:
   - Clear description
   - Steps to reproduce
   - Environment details
   - Relevant logs

---

**Last Updated**: February 2026
**Version**: 0.1.0
