# CORTEX — Agentic Graph RAG Platform

> **CORTEX** is a production-grade, agentic Knowledge Graph platform that transforms unstructured documents and web content into an intelligent, queryable knowledge graph — with a full-featured React UI, streaming AI chat, real-time graph visualization, simulation personas, and deep ontology governance.

---

## ✨ What's Been Built

### 🖥️ Full-Stack Application

| Layer | Stack |
|---|---|
| **Backend API** | FastAPI (async) + Python 3.12 |
| **Task Queue** | Celery + Redis |
| **Graph + Vector DB** | Neo4j 5.x (unified) |
| **LLM Layer** | OpenAI, Anthropic, Google Gemini, Ollama |
| **Frontend** | React 18 + TypeScript + Vite |
| **Unified Start** | `npm run rag` (concurrently launches all 3 processes) |

---

## 🚀 Features

### 📥 Document Ingestion Pipeline

- **Multi-format ingestion**: PDF, TXT, MD, DOCX, CSV, XLSX, PPTX, JSON
- **Web scraping**: Single-page scrape via `POST /api/documents/scrape`
- **Deep web crawling**: Multi-depth Playwright-powered crawler (`POST /api/documents/crawl`) via Crawl4AI
- **Async Celery workers**: Upload returns instantly with a `task_id`; background workers build the graph
- **Re-ingest**: Admin can trigger re-processing of any stored document
- **Document preview & download**: In-browser preview of text/Markdown; PDF download via API

### 🔭 Ontology Management

- **Auto-generation**: LLM analyzes document chunks to propose entity types & relationship types
- **LLM-powered refinement**: `POST /api/ontology/refine` — refine schema with optional human feedback
- **Versioning**: Each schema change bumps the version (`v1.0` → `v1.1`, etc.)
- **Document-scoped stats**: `/api/ontology/stats?document_id=...` returns entity/relationship breakdowns for a specific document
- **Visual editor**: Ontology view in UI with editable entity types and relationship types
- **Ontology Drift Detection**: Automated drift detection compares live graph against new chunk samples; exposes pending/approved/rejected drift reports with admin approve/reject workflow

### 🤖 Agentic Retrieval System

- **LangGraph orchestration**: State-machine ReACT agent with multi-step reasoning and fallback mechanisms
- **Tool routing**: Dynamically selects from Vector Search, Graph Traversal, Cypher Generation, Metadata Filtering, Community Search, and Temporal Queries
- **Streaming responses**: Server-Sent Events (SSE) with real-time reasoning steps surfaced in the UI
- **Multi-turn conversations**: Persistent conversation threads stored in Neo4j, per-user
- **Document-scoped queries**: Filter retrieval to a specific document via `document_id`
- **Graph of Thoughts (GoT)**: Optional GoT reasoning mode for complex multi-hop queries
- **LLM-as-a-Judge (inline)**: Optional per-response quality scoring with hallucination risk, grounded/ungrounded claims, and confidence reasoning displayed in chat
- **Confidence display**: Confidence score, hallucination risk, and judge reasoning shown directly in the chat bubble

### 📊 RAGAS Evaluation & Quality Dashboard

- **`POST /api/eval/score`**: Run RAGAS-style evaluation on any Q&A pair (faithfulness, relevancy, context precision, hallucination detection)
- **`GET /api/eval/dashboard`**: Aggregate evaluation history — avg scores, hallucination rate, trend timeline
- Results persisted in Neo4j for longitudinal quality tracking

### 🗺️ Graph Intelligence

- **D3 force-directed visualization**: Interactive knowledge graph with zoom, pan, node selection, and a details modal
- **Graph Export**: Export full or document-scoped graph as JSON, Cypher, or GraphML
- **Community Detection**: Weakly-connected-components (WCC) community assignment with `POST /api/graph/communities/assign`
- **Community listing**: `GET /api/graph/communities` — top communities by entity count
- **Temporal Queries**: `GET /api/entities/{entity_name}/at-time` — retrieve entity relationships at a historical point in time
- **Semantic Entity Deduplication**: Multi-stage entity resolution with configurable similarity thresholds (`POST /api/entities/deduplicate`)
- **Entity Enrichment**: LLM-synthesized profile summaries for every entity, stored as `e.summary` (`POST /api/entities/enrich`)
- **Entity Chat (scoped)**: `POST /api/entities/{entity_name}/chat` — multi-turn conversation scoped entirely to a single entity's graph neighborhood
- **Graph Memory Updater**: Push raw text directly into the live knowledge graph without re-ingesting a document (`POST /api/graph/update`)

### 📝 Analytical Report Agent (ReACT)

- **`POST /api/report`**: ReACT multi-step report agent using InsightForge / PanoramaSearch / QuickSearch tools
- Decomposes topic into sub-questions → retrieves graph data → synthesizes sections → compiles structured markdown report
- Exposed in the **Insights** view (copy/download report as Markdown)

### 🎭 Simulation & Persona Engine

- **Persona generation**: Celery task that generates personas from graph entities (`POST /api/v1/simulation/generate_personas`)
- **Simulation ticks**: Background tick loop (`POST /api/v1/simulation/tick`)
- **Live persona interview**: `POST /api/v1/simulation/interview` — roleplay chat with any graph entity injecting their Neo4j memory as system context
- **SimulationRunView**: Dedicated UI view for managing and interacting with simulation personas

### 🛡️ Admin Dashboard

- **System statistics**: Node count, relationship count, LLM provider, environment
- **User management**: List users, update scopes/roles (RBAC)
- **Document vault**: View and delete all ingested documents
- **Graph CRUD**: Search, inspect, and delete graph nodes from the admin panel
- **Ontology governance**: Review and approve/reject pending ontology proposals
- **Celery task monitor**: View active and reserved tasks from the admin panel
- **Self-demotion guard**: Admins cannot demote their own account
- **Re-ingest button**: Re-queue any stored document from the document vault
- **User activity metrics**: Per-user conversation count, message count, last active timestamp

### 🔐 Authentication & Security

- **JWT authentication**: Token-based auth with configurable expiry
- **RBAC scopes**: `read`, `write`, `admin` scopes enforced per endpoint
- **User registration**: `POST /api/auth/register`
- **Pydantic validation**: All API inputs validated at the model layer
- **Cypher injection prevention**: Schema validation and query whitelisting
- **File upload limits**: File size and MIME type enforcement

### 🌐 Frontend (React/TypeScript)

Seven fully implemented views accessible from the `CORTEX` top navigation bar:

| Route | View | Description |
|---|---|---|
| `/` | **Home** | Animated stats dashboard — documents, entities, relationships, graph health |
| `/process` | **Process** | Upload files or scrape/crawl URLs; view ingestion queue and document list |
| `/ontology` | **Ontology** | View/edit the live ontology schema; run LLM refinement; inspect entity/relationship stats per doc |
| `/interact` | **Interact** | Streaming AI chat with reasoning steps, confidence, hallucination risk; conversation history |
| `/simulate` | **Simulate** | Simulation persona management and live interview interface |
| `/insights` | **Insights** | Topic-driven analytical report generation with copy/download |
| `/admin` | **Admin** _(admin-only)_ | Full admin panel for users, docs, tasks, ontology governance |

### 🔭 Observability

- **OpenTelemetry**: Distributed tracing (silenced from console; configured for export)
- **Health check**: `GET /api/system/health` — Neo4j, Redis, Celery worker status
- **System stats**: `GET /api/system/stats` — document, entity, relationship, chunk counts
- **User stats**: `GET /api/system/my-stats` — per-user conversation and message activity

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          React Frontend (CORTEX)                             │
│    Home │ Process │ Ontology │ Interact │ Simulate │ Insights │ Admin        │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │ HTTP / SSE
┌─────────────────────────────▼───────────────────────────────────────────────┐
│                     FastAPI Gateway (port 8000)                              │
│          JWT Auth · RBAC Scopes · CORS · OpenTelemetry                      │
└──────┬──────────────────────┬──────────────────────┬────────────────────────┘
       │                      │                      │
┌──────▼──────┐   ┌───────────▼──────────┐  ┌───────▼────────────────────┐
│  Ingestion  │   │  ReACT Agent System  │  │  Report Agent (ReACT)      │
│  Pipeline   │   │  - Vector Search     │  │  - InsightForge            │
│  - Parser   │   │  - Graph Traversal   │  │  - PanoramaSearch          │
│  - Ontology │   │  - Cypher Gen (GoT)  │  │  - QuickSearch             │
│  - Extractor│   │  - Community Search  │  │  - Markdown output         │
│  - Web      │   │  - Temporal Queries  │  └────────────────────────────┘
│    Crawler  │   │  - LLM-as-a-Judge    │
└──────┬──────┘   └─────────┬────────────┘
       │                    │
┌──────▼────────────────────▼──────────────────┐
│              Neo4j 5.x Database               │
│  Entities · Chunks · Relationships ·          │
│  Vector Index · Conversations ·               │
│  EvalResults · DriftReports · Users           │
└───────────────────────────────────────────────┘
       │
┌──────▼──────────────────────┐
│  Celery Workers (Redis)     │
│  - Async document ingestion │
│  - Persona generation       │
│  - Simulation ticks         │
└─────────────────────────────┘
```

---

## 📦 Project Structure

```
graph-RAG/
├── src/graph_rag_service/
│   ├── api/
│   │   ├── server.py          # Main FastAPI app + all API routes (1900 lines)
│   │   ├── auth.py            # JWT auth + RBAC helpers
│   │   ├── admin.py           # Admin sub-router
│   │   ├── simulation.py      # Simulation / persona interview router
│   │   └── models.py          # All Pydantic request/response models
│   ├── core/
│   │   ├── abstractions.py    # Abstract base classes (GraphStore, VectorStore, LLMProvider)
│   │   ├── models.py          # Domain data models
│   │   ├── neo4j_store.py     # Full Neo4j implementation (graph + vector)
│   │   ├── llm_factory.py     # Multi-LLM provider factory + UnifiedLLMProvider
│   │   ├── entity_resolver.py # Semantic entity deduplication
│   │   └── storage.py         # File storage abstraction
│   ├── ingestion/
│   │   ├── pipeline.py        # End-to-end ingestion orchestrator
│   │   ├── document_processor.py  # Multi-format document parsing
│   │   ├── ontology_generator.py  # LLM ontology generation + refinement
│   │   ├── extractor.py       # Entity + relationship extraction
│   │   ├── web_crawler.py     # Playwright-based deep web crawler (Crawl4AI)
│   │   └── persona_generator.py   # Simulation persona generation
│   ├── retrieval/
│   │   ├── agent.py           # LangGraph ReACT retrieval agent
│   │   ├── tools.py           # Retrieval tools + RAGEvaluator (RAGAS)
│   │   └── report_agent.py    # ReACT analytical report agent
│   ├── services/
│   │   ├── graph_memory_updater.py   # Push raw text → live graph
│   │   ├── entity_enricher.py        # LLM entity profile summaries
│   │   └── ontology_drift_detector.py # Automated schema drift detection
│   ├── workers/
│   │   └── celery_worker.py   # Celery app + ingest_document_task
│   ├── observability/
│   │   └── tracing.py         # OpenTelemetry setup (console suppressed)
│   ├── config.py              # Pydantic settings (all env vars)
│   └── main.py                # Uvicorn entry point
├── frontend-react/
│   └── src/
│       ├── views/
│       │   ├── Home.tsx            # Animated stats dashboard
│       │   ├── Process.tsx         # Document upload + URL scrape/crawl
│       │   ├── Ontology.tsx        # Schema editor + stats
│       │   ├── InteractionView.tsx # Streaming chat + conversation history
│       │   ├── SimulationRunView.tsx # Persona simulation UI
│       │   ├── InsightsView.tsx    # Report generation + copy/download
│       │   ├── AdminDashboard.tsx  # Full admin panel
│       │   └── Login.tsx           # Login page
│       ├── components/
│       │   └── GraphCanvas.tsx     # D3 force-directed graph + node modal
│       ├── context/
│       │   └── AuthContext.tsx     # JWT auth context + hooks
│       └── App.tsx                 # Router + top-nav (CORTEX branding)
├── tests/                      # Test suite
├── data/uploads/               # Uploaded documents (local storage)
├── .env.example                # All configurable environment variables
├── pyproject.toml              # Python project + uv dependencies
├── package.json                # Unified start scripts (npm run rag)
├── ARCHITECTURE.md             # Detailed architecture design doc
└── QUICKSTART.md               # 5-minute quick start guide
```

---

## ⚡ Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+
- Neo4j 5.x (running)
- Redis (running)
- Ollama *(optional, for local LLMs)*

### 1. Clone & Install

```bash
git clone <repository-url>
cd graph-RAG

# Installs Python deps (uv), frontend (npm), and Playwright Chromium
npm install
```

### 2. Configure Environment

```bash
cp .env.example .env
# Fill in NEO4J_URI, NEO4J_PASSWORD, and your LLM API keys
```

### 3. Start Neo4j

```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:latest
```

### 4. Start Redis

```bash
docker run -d --name redis -p 6379:6379 redis:alpine
```

### 5. Launch Everything

```bash
npm run rag
```

This starts three color-coded processes concurrently:

| Process | URL |
|---|---|
| **API Server** | `http://localhost:8000` |
| **API Docs** | `http://localhost:8000/docs` |
| **React Frontend** | `http://localhost:5173` |

> Default credentials: `admin` / `admin`

---

## 🔑 Environment Variables

Copy `.env.example` to `.env` and configure:

```env
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# LLM Provider (openai | anthropic | gemini | ollama)
DEFAULT_LLM_PROVIDER=gemini
GOOGLE_API_KEY=your-key-here

# Optional: OpenAI / Anthropic
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Optional: Ollama (local)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=deepseek-r1:7b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# Feature flags
ENABLE_LLM_JUDGE=true

# Security
SECRET_KEY=change-this-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

---

## 🌐 API Reference

### Authentication
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Register new user |
| `POST` | `/api/auth/login` | Login → JWT token |
| `GET` | `/api/auth/me` | Get current user info |

### Documents
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/documents/upload` | Upload file (PDF, DOCX, TXT, MD, CSV, XLSX, PPTX, JSON) |
| `POST` | `/api/documents/scrape` | Scrape single URL → ingest |
| `POST` | `/api/documents/crawl` | Deep multi-page Playwright crawl → ingest *(API Only)* |
| `GET` | `/api/documents` | List all ingested documents |
| `DELETE` | `/api/documents/{id}` | Delete document + graph chunks |
| `GET` | `/api/documents/{id}/download` | Download source file |
| `GET` | `/api/documents/{id}/preview` | Preview text content |
| `GET` | `/api/documents/status/{task_id}` | Ingestion task status |

### Query & Chat
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/query` | Agentic query (streaming or JSON); supports `document_id`, `use_got` |
| `GET` | `/api/conversations` | List conversation threads |
| `GET` | `/api/conversations/{id}` | Get conversation + messages |
| `DELETE` | `/api/conversations/{id}` | Delete conversation |

### Ontology
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/ontology` | Get current ontology |
| `PUT` | `/api/ontology` | Update ontology (admin) |
| `POST` | `/api/ontology/refine` | LLM-powered ontology refinement |
| `GET` | `/api/ontology/stats` | Entity/relationship counts (optional doc filter) |
| `POST` | `/api/ontology/drift/detect` | Trigger drift detection |
| `GET` | `/api/ontology/drift` | List drift reports |
| `POST` | `/api/ontology/drift/{id}/approve` | Approve drift → merge into ontology |
| `POST` | `/api/ontology/drift/{id}/reject` | Reject drift report |

### Graph
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/graph/visualization` | Graph nodes + edges for D3 rendering |
| `GET` | `/api/graph/export` | Export graph (json \| cypher \| graphml) |
| `POST` | `/api/graph/update` | Push raw text → merge into live graph |
| `POST` | `/api/graph/communities/assign` | Run WCC community detection |
| `GET` | `/api/graph/communities` | List top communities |

### Entities
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/entities/deduplicate` | Semantic entity resolution + merge |
| `POST` | `/api/entities/enrich` | Generate LLM summaries for all entities |
| `GET` | `/api/entities/{name}/summary` | Get enriched entity profile |
| `POST` | `/api/entities/{name}/chat` | Multi-turn entity-scoped chat |
| `GET` | `/api/entities/{name}/at-time` | Temporal query (ISO 8601 date) |

### Reports & Evaluation
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/report` | Generate ReACT analytical report (markdown) |
| `POST` | `/api/eval/score` | RAGAS evaluation of a Q&A pair |
| `GET` | `/api/eval/dashboard` | Evaluation history dashboard |

### Simulation
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/simulation/interview` | Live persona interview (in-character LLM) |
| `GET` | `/api/v1/simulation/report` | Sandbox analytical report *(API Only)* |
| `POST` | `/api/v1/simulation/generate_personas` | Queue persona generation task *(API Only)* |
| `POST` | `/api/v1/simulation/tick` | Advance simulation tick *(API Only)* |

### System & Admin
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/system/health` | Neo4j + Redis + Celery health |
| `GET` | `/api/system/stats` | Document, entity, relationship counts |
| `GET` | `/api/system/my-stats` | Current user's activity stats |
| `GET` | `/api/system/formats` | Supported ingestion file formats |
| `GET` | `/api/admin/stats` | Admin-only system stats |
| `GET` | `/api/admin/users` | List all users |
| `PUT` | `/api/admin/users/{username}/role` | Update user scopes |
| `GET` | `/api/admin/tasks` | View Celery tasks |
| `GET` | `/api/admin/documents` | Admin document vault |
| `POST` | `/api/admin/documents/{id}/reingest` | Re-queue document for ingestion |
| `GET` | `/api/admin/graph/nodes` | Search graph nodes |
| `DELETE` | `/api/admin/graph/nodes/{id}` | Delete a graph node |

---

## 🧪 Testing

```bash
# Run tests
uv run pytest

# With coverage
uv run pytest --cov=src/graph_rag_service
```

---

## 🚀 Production Deployment

| Process | Command |
|---|---|
| **API Server** | `uv run python main.py` |
| **Celery Worker** | `uv run celery -A src.graph_rag_service.workers.celery_worker worker --loglevel=info --concurrency=4 --pool=threads` |
| **React Build** | `cd frontend-react && npm run build` |

The built React assets can be served directly by FastAPI (static file mount), or deployed to a CDN separately. Neo4j and Redis can be run via Docker, managed cloud services (AuraDB, Redis Cloud), or self-hosted.

---

## 📄 Additional Documentation

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — Deep dive into the system design, data flow, and component interactions
- **[QUICKSTART.md](./QUICKSTART.md)** — 5-minute environment setup guide
- **`/docs`** — Interactive Swagger UI (auto-generated from FastAPI)

---

**Project Status**: Production-grade MVP · Actively developed  
**License**: Proprietary — all rights reserved
