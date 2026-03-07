# Solution Architecture: Agentic Graph RAG as a Service

This document outlines a detailed technical approach to building the Agentic Graph RAG platform. It focuses on modularity, scalability, and the specific requirements of the Lyzr Hackathon, with a strong emphasis on production-grade robustness.

## 1. High-Level Architecture

The system is designed as a set of modular services centered around a shared Knowledge Graph and Vector Store, fortified with enterprise-grade security and observability layers.

```mermaid
graph TD
    User[User / Client] --> Auth[Auth & Access Control]
    Auth --> API[Unified API Gateway]
    
    subgraph "Observability Layer (OpenTelemetry)"
        Logs[Structured Logging]
        Traces[Agent Traces]
        Metrics[Performance Metrics]
    end
    
    API -.-> Logs & Traces & Metrics

    subgraph "Ingestion Pipeline (Async Workers)"
        API --> Queue[Task Queue (Redis/Celery)]
        Queue --> Ingest[Ingestion Worker]
        Ingest --> Chunking[Text Chunking]
        Chunking --> OntologyGen[LLM Ontology Gen (Versioned)]
        OntologyGen --> Extract[Entity & Relation Extraction]
        Extract --> Resolution[Entity Resolution / Dedup]
        Resolution --> GraphDB[(Neo4j / Neptune)]
        Resolution --> VectorDB[(Vector Store)]
    end
    
    subgraph "Retrieval Context"
        API --> Agent[Agent Orchestrator]
        Agent --> Decomp[Query Decomposer]
        Decomp --> Router[Query Router / Planner]
        
        Router --> |Semantic Query| VectorSearch[Vector Search]
        Router --> |Deep Relation| GraphSearch[Graph Traversal / Cypher]
        Router --> |Structured| FilterSearch[Metadata Filter]
        
        VectorSearch & GraphSearch & FilterSearch --> Validator[Hallucination Guard / Schema Validator]
        Validator --> Synthesizer[Response Synthesizer]
        Synthesizer --> Agent
    end
```

## 2. Technology Stack Selection

*   **Language:** Python 3.12 (Standard for AI/ML engineering).
*   **API Framework:** FastAPI (Async support, auto-documentation).
*   **Orchestration:** LlamaIndex (Preferred for Graph RAG).
*   **LLM:** multi-LLM support like ollama, open ai, gemini,claude (use lang-graph) (Reasoning & Extraction) & `BAAI bge-m3` this model is available on ollama so we will use from ollama (Embeddings).
*   **Graph Database:** Neo4j (Primary) .
*   **Vector Store:** Neo4j Vector Index (for unified storage) or Qdrant/Chroma.
*   **Task Queue:** Celery with Redis (for async ingestion).
*   **Monitoring:** OpenTelemetry + Prometheus/Grafana.
*   **Frontend:**  React vite + tailwind css (for Visual Ontology Editor).

## 3. Production-Grade Components

### A. Document-to-Graph Pipeline (Ingestion)

This pipeline converts unstructured text into a structured Knowledge Graph, robust to schema changes and duplicates.

1.  **Ontology Generation & Evolution:**
    *   *Initial:* Ask LLM to identify high-level concepts (nodes) and interactions (edges) from first $N$ chunks.
    *   *Visual Editor:* Human approval step to refine the JSON schema.
    *   **Drift Handling:** Incorporate an "Ontology Versioning" system. Every node/edge is tagged with `ontology_version: v1.0`. New documents causing schema changes trigger a "Migration Proposal" for approval.

2.  **Extraction & Embedding:**
    *   **Prompt Engineering:** "Given text + Ontology v1.0, extract entities/relationships."
    *   **Hybrid Nodes:** Create `(:Chunk)` nodes linked to `(:Entity)` nodes (`(:Chunk)-[:MENTIONS]->(:Entity)`). This preserves ground truth source text alongside abstract graph relationships.

3.  **Advanced Entity Resolution:**
    *   *Naive:* Exact string match.
    *   *Production:* Multi-stage blocking and merging.
        1.  **Blocking:** Group entities by Label and similar name (e.g., phonetic match).
        2.  **Semantic Check:** Compare embeddings of candidates.
        3.  **Threshold:** If similarity > 0.95 -> Auto-merge. If 0.85-0.95 -> Flag for "Human Review Queue".

### B. The Agentic Retrieval System (The Brain)

A state machine loop designed for accuracy and fail-safe operation.

**1. Query Decomposition & Routing**
Instead of a single step, the Agent breaks down complexity:
*   *User Query:* "How is the CEO of Lyzr related to OpenAI?"
*   *Decomposition:*
    1.  "Identify Lyzr CEO" (Vector/Graph lookup) -> *Result: user_X*
    2.  "Find path between user_X and OpenAI" (Graph traversal).
*   *Router:* Dynamically selects tools for each sub-step.

**2. Tool Implementation with Guardrails:**
*   **Vector Tool:** Top-k retrieval using embedding similarity.
*   **Graph Tool (Text-to-Cypher):** Uses LLM to generate Cypher.
    *   **Hallucination Guard:** The tool injects the *strict* allowed schema into the prompt. Generated Cypher is parsed and validated against a "Relationship Whitelist" before execution to prevent schema injection or invalid edge types.
*   **Filter Tool:** Converts natural language to structured DB filters (WHERE clauses).

**3. Latency & Performance Strategy:**
*   **Timeouts:** Hard limit on agent reasoning steps (e.g., max 5 loops).
*   **Fallback:** If Graph tool fails or times out, degrade gracefully to pure Vector Search for a "best effort" answer.

### C. Parity & Extensibility Layer

We define abstract base class interfaces to ensure no vendor lock-in.

```python
class GraphStore(ABC):
    @abstractmethod
    def execute_query(self, query: str, params: dict): pass

class VectorStore(ABC):
    @abstractmethod
    def search(self, query_vector: List[float], k: int): pass

class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str): pass

# Implementations: Neo4jStore, NeptuneStore, QdrantStore, OpenAIProvider, etc.
```

## 4. Scalability, Security & Observability

To meet "Production-Grade" criteria, these non-functional requirements are critical:

1.  **Access Control (RBAC):**
    *   Pre-retrieval enforcement.
    *   All queries filter by `user.tenant_id` or `user.permissions` to ensure users only retrieve data they are authorized to see.
    
2.  **Observability:**
    *   **Tracing:** Log every step of the Agent's reasoning chain (Input -> Decomp -> Tool Call -> Result). This is vital for debugging "why did the bot say that?".
    *   **Metrics:** Track Token Usage, Latency p95, and Cache Hit Rates.

3.  **Async Ingestion:**
    *   Ingestion is decoupled from the user request loop.
    *   File Upload API -> Pushes ID to Redis Queue -> Background Worker picks up -> Runs Extraction -> Updates Graph.

4.  **Caching Strategy:**
    *   **Semantic Cache (Redis):** Before hitting the LLM, check if a semantically similar query has been answered recently. reduces cost and latency.
    *   **Embedding Cache:** Store computed embeddings to avoid re-calculation for identical text chunks.

## 5. Implementation Plan

### Phase 1: Foundation (Hours 1-4)
1.  Set up Repository, Python envf (Neo4j/Redis).
2.  Implement `GraphStore` & `VectorStore` abstractions.
3.  Create Basic Auth & Middleware logging.

### Phase 2: Ingestion Engine (Hours 5-12)
1.  Implement PDF extractor & Async Worker skeleton.
2.  Build "Ontology Proposer" & "Graph Extractor" prompts.
3.  Implement Entity Resolution logic.

### Phase 3: The Retrieval Agent (Hours 13-20)
1.  Set up Agent loop with Query Decomposition.
2.  Implement `Text2Cypher` with schema validation.
3.  Implement Latency Timeouts & Fallbacks.

### Phase 4: Refinement & UI (Hours 21-24)
1.  Build Visual Editor (Streamlit).
2.  Add simple Evaluation Script (run known queries, check answers).
3.  Write `README.md` highlighting the "Production Thinking" (RBAC, Async, Observability).

## 6. Key Innovations
1.  **Hybrid Chunk Nodes:** Storing source text explicitly in the graph for ground-truth verification.
2.  **Self-Correcting Cypher:** If Cypher execution fails, feed the error back to the LLM to fix syntax automatically.
3.  **Adaptive Retrieval:** The agent assigns a "confidence score" to each retrieval method. If Vector Search confidence is low (<0.7), it automatically triggers Graph Traversal to boost context.
