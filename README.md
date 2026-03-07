"""
Comprehensive README for the Graph RAG as a Service Platform
"""

# Graph RAG as a Service

An extensible, production-grade Agentic Graph RAG platform that unifies knowledge from multiple sources into an intelligent retrieval system.

## 🚀 Features

### Document-to-Graph Pipeline
- **Automated Knowledge Graph Construction**: Automatically construct knowledge graphs from unstructured documents
- **LLM-Powered Ontology Generation**: Dynamic ontology discovery with versioning and evolution support
- **Multi-LLM Support**: Compatible with OpenAI, Anthropic, Google Gemini, and Ollama
- **Entity Resolution & Deduplication**: Advanced multi-stage entity resolution with semantic similarity
- **Hybrid Storage**: Unified Neo4j implementation for both graph and vector storage

### Agentic Retrieval System
- **Dynamic Tool Selection**: Intelligent routing between vector search, graph traversal, and Cypher queries
- **Multi-Step Reasoning**: Query decomposition with iterative refinement
- **LangGraph Orchestration**: State machine-based agent workflow with fallback mechanisms
- **Hallucination Guards**: Schema validation and self-correcting Cypher generation
- **Semantic Caching**: Redis-based caching for improved performance

### Production-Grade Architecture
- **FastAPI Backend**: Async API with JWT authentication and RBAC
- **Celery Workers**: Asynchronous document ingestion with task queuing
- **OpenTelemetry**: Distributed tracing and metrics collection
- **Modular Design**: Pluggable GraphStore, VectorStore, and LLMProvider abstractions

## 📋 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway (FastAPI)                     │
│                  Authentication & Authorization                  │
└────────────────┬─────────────────────────────────┬──────────────┘
                 │                                 │
    ┌────────────▼──────────┐          ┌──────────▼─────────────┐
    │  Ingestion Pipeline   │          │  Retrieval Agent       │
    │  - Document Processing│          │  - LangGraph Workflow  │
    │  - Ontology Discovery │          │  - Tool Selection      │
    │  - Entity Extraction  │          │  - Response Synthesis  │
    │  - Async Workers      │          │  - Semantic Cache      │
    └───────────┬───────────┘          └──────────┬─────────────┘
                │                                 │
       ┌────────▼─────────┐          ┌───────────▼──────────┐
       │  Neo4j Graph DB  │◄─────────┤  Vector Search Tool  │
       │  - Entities      │          │  Graph Traversal     │
       │  - Relationships │          │  Cypher Generation   │
       │  - Vector Index  │          │  Metadata Filtering  │
       └──────────────────┘          └──────────────────────┘
```

## 🛠️ Technology Stack

- **Language**: Python 3.12
- **API Framework**: FastAPI with async/await support
- **Orchestration**: LangGraph for agent workflows
- **LLMs**: Multi-provider support (OpenAI, Anthropic, Gemini, Ollama)
- **Embeddings**: Ollama BGE-M3 (1024 dimensions)
- **Graph Database**: Neo4j 5.x with vector capabilities
- **Vector Store**: Neo4j Vector Index (unified storage)
- **Task Queue**: Celery with Redis broker
- **Observability**: OpenTelemetry + Prometheus-compatible metrics
- **Package Manager**: UV (fast Python package management)

## 📦 Installation

### Prerequisites
- Python 3.12+
- Neo4j 5.x
- Redis
- Ollama (optional, for local LLMs)

### Setup

1. **Clone the repository**
```bash
git clone <repository-url>
cd graph-RAG
```

2. **Install dependencies with UV**
```bash
uv sync
```

3. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. **Start Neo4j**
```bash
# Using Docker
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j
```

5. **Start Redis**
```bash
# Using Docker
docker run -d \
  --name redis \
  -p 6379:6379 \
  redis
```

6. **Start Ollama (optional)**
```bash
# Download and start Ollama
ollama pull llama3.2
ollama pull bge-m3
```

## 🚀 Usage

### Start the API Server

```bash
# Windows
start-server.bat

# Mac / Linux
chmod +x start-server.sh && ./start-server.sh

# Or directly
uv run python main.py
```

API available at `http://localhost:8000`  
Interactive docs: `http://localhost:8000/docs`

### Start Celery Worker (new terminal)

```bash
# Windows
start-worker.bat

# Mac / Linux
chmod +x start-worker.sh && ./start-worker.sh

# Or directly
uv run celery -A src.graph_rag_service.workers.celery_worker worker --loglevel=info
```

### Start the Streamlit Frontend (new terminal)

```bash
cd frontend
uv run streamlit run app.py
```

Frontend available at `http://localhost:8501`

### API Examples

#### 1. Get Access Token
```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'
```

#### 2. Upload Document
```bash
curl -X POST "http://localhost:8000/api/documents/upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@document.pdf"
```

#### 3. Query Knowledge Base
```bash
curl -X POST "http://localhost:8000/api/query" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the main topics covered in the documents?",
    "top_k": 5
  }'
```

#### 4. Get Ontology
```bash
curl -X GET "http://localhost:8000/api/ontology" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### 5. Visualize Graph
```bash
curl -X GET "http://localhost:8000/api/graph/visualization?limit=50" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 🏗️ Project Structure

```
graph-RAG/
├── src/graph_rag_service/
│   ├── api/                    # FastAPI application
│   │   ├── server.py          # Main API server
│   │   ├── auth.py            # Authentication & authorization
│   │   └── models.py          # Pydantic models
│   ├── core/                   # Core abstractions
│   │   ├── abstractions.py    # Abstract base classes
│   │   ├── models.py          # Data models
│   │   ├── neo4j_store.py     # Neo4j implementation
│   │   ├── llm_factory.py     # Multi-LLM support
│   │   └── entity_resolver.py # Entity deduplication
│   ├── ingestion/              # Document ingestion pipeline
│   │   ├── document_processor.py
│   │   ├── ontology_generator.py
│   │   ├── extractor.py
│   │   └── pipeline.py
│   ├── retrieval/              # Agentic retrieval system
│   │   ├── tools.py           # Retrieval tools
│   │   └── agent.py           # LangGraph agent
│   ├── workers/                # Celery workers
│   │   └── celery_worker.py
│   ├── observability/          # Monitoring & tracing
│   │   └── tracing.py
│   ├── config.py              # Configuration management
│   └── main.py                # Application entry point
├── tests/                      # Test suite
├── data/uploads/              # Uploaded documents
├── .env.example               # Environment variables template
├── pyproject.toml             # Project dependencies
└── README.md                  # This file
```

## 🔑 Key Features Explained

### 1. Pluggable Architecture
The system uses abstract base classes (`GraphStore`, `VectorStore`, `LLMProvider`) to ensure no vendor lock-in. Easily swap Neo4j for Neptune, or add new LLM providers.

### 2. Entity Resolution
Multi-stage entity resolution with:
- **Blocking**: Group by entity type and name similarity
- **Semantic Comparison**: Use embeddings for deep similarity
- **Configurable Thresholds**: Fine-tune precision vs recall

### 3. Ontology Evolution
- **Initial Generation**: LLM analyzes sample chunks to propose ontology
- **Versioning**: Track schema changes with `v1.0`, `v1.1`, etc.
- **Human-in-the-Loop**: Visual editor for ontology approval and refinement

### 4. Agentic Retrieval
The retrieval agent:
1. Decomposes complex queries into sub-queries
2. Routes each sub-query to the optimal tool (vector/graph/cypher)
3. Validates results against schema (hallucination guard)
4. Synthesizes final response with reasoning chain
5. Implements timeout and fallback mechanisms

### 5. Async Ingestion
- Upload returns immediately with task ID
- Celery workers process documents in background
- Poll `/api/documents/status/{task_id}` for progress
- Scalable: Add more workers to increase throughput

## 🧪 Testing

```bash
# Run tests
uv run pytest

# With coverage
uv run pytest --cov=graph_rag_service
```

## 📊 Monitoring

The system provides:
- **Health Check**: `/api/system/health`
- **System Stats**: `/api/system/stats`
- **OpenTelemetry Traces**: Agent reasoning steps and tool calls
- **Metrics**: Document ingestion rates, query latencies, entity counts

## 🔐 Security Features

- **JWT Authentication**: Token-based auth with expiration
- **RBAC**: Role-based access control with scopes
- **Input Validation**: Pydantic models for all requests
- **Cypher Injection Prevention**: Schema validation and whitelist
- **File Upload Limits**: Size and type restrictions

## 🚀 Production Deployment

### Docker Deployment
```bash
# Build image
docker build -t graph-rag-service .

# Run with docker-compose
docker-compose up -d
```

### Environment Variables
Key settings in `.env`:
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- `REDIS_HOST`, `REDIS_PORT`
- `DEFAULT_LLM_PROVIDER` (openai, anthropic, gemini, ollama)
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`
- `OLLAMA_BASE_URL`, `OLLAMA_MODEL`

## 📄 License

MIT License - see LICENSE file for details

---

**Project Status**: Production-ready MVP with extensible architecture

For questions or issues, please open a GitHub issue or contact the maintainers.
