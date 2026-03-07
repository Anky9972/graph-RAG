"""
FastAPI application - Main API server
Unified API gateway for the Graph RAG service
"""

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pathlib import Path
import shutil
import json
import asyncio
from datetime import timedelta, datetime
from typing import List, Optional
import redis.asyncio as redis
from celery.result import AsyncResult

from .auth import (
    get_current_user,
    create_access_token,
    verify_password,
    get_password_hash,
    User,
    check_scope
)
from .models import (
    LoginRequest,
    TokenResponse,
    DocumentUploadResponse,
    DocumentInfo,
    DocumentListResponse,
    QueryRequest,
    QueryResponse,
    OntologyResponse,
    OntologyUpdateRequest,
    OntologyRefineRequest,
    OntologyRefineResponse,
    SystemHealthResponse,
    SystemStatsResponse,
    IngestionStatusResponse,
    GraphVisualizationResponse,
    GraphNode,
    GraphEdge,
    DeduplicateResponse
)

from ..config import settings
from ..core.neo4j_store import Neo4jStore
from ..retrieval.agent import AgentRetrievalSystem
from ..ingestion.pipeline import IngestionPipeline
from ..ingestion.ontology_generator import OntologyGenerator
from ..core.entity_resolver import SemanticEntityResolver
from ..core.llm_factory import LLMFactory
from ..workers.celery_worker import celery_app, ingest_document_task

# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Agentic Graph RAG as a Service - Production-grade knowledge graph platform"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances (will be initialized on startup)
graph_store: Optional[Neo4jStore] = None
retrieval_agent: Optional[AgentRetrievalSystem] = None
ingestion_pipeline: Optional[IngestionPipeline] = None
redis_client: Optional[redis.Redis] = None


@app.on_event("startup")
async def startup_event():
    """Initialize connections on startup"""
    global graph_store, retrieval_agent, ingestion_pipeline, redis_client
    
    # Initialize Neo4j
    graph_store = Neo4jStore()
    await graph_store.connect()
    
    # Initialize retrieval agent
    retrieval_agent = AgentRetrievalSystem(
        graph_store=graph_store,
        llm_provider=settings.default_llm_provider
    )
    
    # Initialize ingestion pipeline
    ingestion_pipeline = IngestionPipeline(
        graph_store=graph_store,
        llm_provider=settings.default_llm_provider
    )
    await ingestion_pipeline.initialize()
    
    # Initialize Redis
    redis_client = redis.from_url(settings.redis_url)
    
    # Create upload directory
    settings.upload_dir.mkdir(parents=True, exist_ok=True)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    if graph_store:
        await graph_store.disconnect()
    if ingestion_pipeline:
        await ingestion_pipeline.close()
    if redis_client:
        await redis_client.close()


# Authentication Endpoints

@app.post("/api/auth/login", response_model=TokenResponse, tags=["Authentication"])
async def login(request: LoginRequest):
    """
    Login and get access token
    
    For demo purposes, accepts any username/password
    In production, validate against user database
    """
    # Mock authentication - replace with real user validation
    if not request.username or not request.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Create access token
    access_token = create_access_token(
        data={
            "sub": request.username,
            "scopes": ["read", "write", "admin"]
        },
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes)
    )
    
    return TokenResponse(access_token=access_token)


@app.get("/api/auth/me", response_model=User, tags=["Authentication"])
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user


# Document Upload & Ingestion Endpoints

@app.post("/api/documents/upload", response_model=DocumentUploadResponse, tags=["Documents"])
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """
    Upload document for ingestion
    Returns task ID for tracking ingestion progress
    """
    
    # Validate file type
    file_extension = Path(file.filename).suffix
    if file_extension not in settings.allowed_file_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file_extension} not allowed. Allowed types: {settings.allowed_file_types}"
        )
    
    # Save file
    file_path = settings.upload_dir / file.filename
    
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    file_size = file_path.stat().st_size
    
    # Validate file size
    if file_size > settings.max_upload_size_mb * 1024 * 1024:
        file_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {settings.max_upload_size_mb}MB"
        )
    
    # Queue ingestion task
    task = ingest_document_task.delay(
        str(file_path),
        ontology_dict=None
    )
    
    return DocumentUploadResponse(
        document_id=str(file_path.stem),
        filename=file.filename,
        size_bytes=file_size,
        task_id=task.id,
        message="Document uploaded successfully. Ingestion in progress."
    )


@app.get("/api/documents", response_model=DocumentListResponse, tags=["Documents"])
async def list_documents(current_user: User = Depends(get_current_user)):
    """List all ingested documents"""
    query = """
    MATCH (d:Document)
    RETURN d.id as id, d.filename as filename, d.file_type as file_type,
           d.size_bytes as size_bytes, toString(d.upload_date) as upload_date
    ORDER BY d.upload_date DESC
    """
    results = await graph_store.execute_query(query)
    docs = [
        DocumentInfo(
            id=r["id"] or "",
            filename=r["filename"] or "",
            file_type=r["file_type"] or "",
            size_bytes=r["size_bytes"] or 0,
            upload_date=str(r["upload_date"] or "")[:19]
        )
        for r in results
    ]
    return DocumentListResponse(documents=docs, total=len(docs))


@app.delete("/api/documents/{document_id}", tags=["Documents"])
async def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete a document and all its chunks and entity links from the graph"""
    # Remove chunks + document node; entities shared with other docs are kept
    delete_query = """
    MATCH (d:Document {id: $doc_id})
    OPTIONAL MATCH (d)-[:CONTAINS]->(c:Chunk)
    DETACH DELETE c, d
    """
    await graph_store.execute_query(delete_query, {"doc_id": document_id})

    # Remove uploaded file if it still exists
    for f in settings.upload_dir.iterdir():
        if f.stem == document_id:
            f.unlink(missing_ok=True)
            break

    return {"status": "deleted", "document_id": document_id}


@app.get("/api/documents/status/{task_id}", response_model=IngestionStatusResponse, tags=["Documents"])
async def get_ingestion_status(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get ingestion task status"""
    
    task = AsyncResult(task_id, app=celery_app)
    
    if task.state == 'PENDING':
        response = {
            "task_id": task_id,
            "status": "pending",
            "progress": None,
            "result": None
        }
    elif task.state == 'PROCESSING':
        response = {
            "task_id": task_id,
            "status": "processing",
            "progress": task.info,
            "result": None
        }
    elif task.state == 'SUCCESS':
        response = {
            "task_id": task_id,
            "status": "completed",
            "progress": None,
            "result": task.info
        }
    else:
        response = {
            "task_id": task_id,
            "status": task.state.lower(),
            "progress": None,
            "result": str(task.info) if task.info else None
        }
    
    return IngestionStatusResponse(**response)


# Query Endpoints

@app.post("/api/query", tags=["Query"])
async def query(
    request: QueryRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Execute agentic query with dynamic tool selection.
    When streaming=True returns Server-Sent Events; otherwise returns JSON.
    Optionally filter to a specific document via document_id.
    """

    if request.streaming:
        async def event_stream():
            reasoning_steps = []

            async for chunk in retrieval_agent.astream(
                query=request.query,
                top_k=request.top_k,
                document_id=request.document_id,
            ):
                # Each chunk is a partial state dict yielded after each node
                steps = chunk.get("reasoning_steps", [])
                new_steps = steps[len(reasoning_steps):]
                for step in new_steps:
                    reasoning_steps.append(step)
                    yield f"data: {json.dumps({'type': 'step', 'content': step})}\n\n"

                if chunk.get("answer"):
                    payload = {
                        "type": "answer",
                        "answer": chunk["answer"],
                        "confidence": chunk.get("confidence", 0.0),
                        "retrieval_method": "agentic",
                        "reasoning_chain": chunk.get("reasoning_steps", []),
                        "sources": chunk.get("contexts", []),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # Non-streaming path
    result = await retrieval_agent.query(
        query=request.query,
        top_k=request.top_k,
        document_id=request.document_id,
    )

    return QueryResponse(
        answer=result.answer,
        sources=result.sources,
        reasoning_chain=result.reasoning_chain,
        confidence=result.confidence,
        retrieval_method=result.retrieval_method,
        processing_time_seconds=result.processing_time_seconds
    )


# Ontology Endpoints

@app.get("/api/ontology", response_model=OntologyResponse, tags=["Ontology"])
async def get_ontology(current_user: User = Depends(get_current_user)):
    """Get current ontology schema"""
    
    ontology = ingestion_pipeline.get_ontology()
    
    # Fallback: load from Neo4j (ontology is generated in the Celery worker process,
    # not in this server process, so we persist/load it via the graph store)
    if not ontology:
        ontology = await graph_store.load_ontology()
        if ontology:
            ingestion_pipeline.set_ontology(ontology)
    
    if not ontology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ontology available. Ingest documents first to generate ontology."
        )
    
    return OntologyResponse(
        version=ontology.version,
        entity_types=ontology.entity_types,
        relationship_types=ontology.relationship_types,
        properties=ontology.properties,
        created_at=ontology.created_at,
        approved=ontology.approved
    )


@app.post("/api/ontology/refine", response_model=OntologyRefineResponse, tags=["Ontology"])
async def refine_ontology(
    request: OntologyRefineRequest,
    current_user: User = Depends(get_current_user)
):
    """Use LLM to suggest ontology improvements based on current graph data + optional feedback"""

    current_ontology = ingestion_pipeline.get_ontology()
    if not current_ontology:
        current_ontology = await graph_store.load_ontology()
    if not current_ontology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ontology available to refine."
        )

    # Pull a sample of chunk texts from Neo4j to give the LLM context
    sample_query = "MATCH (c:Chunk) RETURN c.text as text LIMIT 10"
    sample_rows = await graph_store.execute_query(sample_query)

    from ..core.models import Chunk as ChunkModel
    sample_chunks = [
        ChunkModel(text=r["text"] or "", document_id="sample", chunk_index=i)
        for i, r in enumerate(sample_rows) if r.get("text")
    ]

    ontology_gen = OntologyGenerator(llm_provider=settings.default_llm_provider)
    refined = await ontology_gen.refine_ontology(
        current_schema=current_ontology,
        new_chunks=sample_chunks,
        feedback=request.feedback
    )

    # Persist and update in-memory
    await graph_store.save_ontology(refined)
    ingestion_pipeline.set_ontology(refined)

    return OntologyRefineResponse(
        version=refined.version,
        entity_types=refined.entity_types,
        relationship_types=refined.relationship_types,
        properties=refined.properties,
        created_at=refined.created_at,
        approved=refined.approved,
        changes=f"Refined from {current_ontology.version} to {refined.version}"
    )


@app.put("/api/ontology", response_model=OntologyResponse, tags=["Ontology"])
async def update_ontology(
    request: OntologyUpdateRequest,
    current_user: User = Depends(check_scope("admin"))
):
    """Update ontology schema (admin only)"""
    
    current_ontology = ingestion_pipeline.get_ontology()
    
    if not current_ontology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ontology to update"
        )
    
    # Update fields if provided
    if request.entity_types is not None:
        current_ontology.entity_types = request.entity_types
    if request.relationship_types is not None:
        current_ontology.relationship_types = request.relationship_types
    if request.properties is not None:
        current_ontology.properties = request.properties
    if request.approved is not None:
        current_ontology.approved = request.approved
    
    # Updated timestamp
    current_ontology.created_at = datetime.utcnow()
    
    ingestion_pipeline.set_ontology(current_ontology)
    
    return OntologyResponse(
        version=current_ontology.version,
        entity_types=current_ontology.entity_types,
        relationship_types=current_ontology.relationship_types,
        properties=current_ontology.properties,
        created_at=current_ontology.created_at,
        approved=current_ontology.approved
    )


# Graph Visualization Endpoints

@app.post("/api/entities/deduplicate", response_model=DeduplicateResponse, tags=["Entities"])
async def deduplicate_entities(
    current_user: User = Depends(check_scope("admin"))
):
    """Run semantic entity resolution and merge duplicates (admin only)"""
    # Load all entities from Neo4j
    entity_query = """
    MATCH (e:Entity)
    RETURN e.id as id, e.name as name, e.type as type
    """
    rows = await graph_store.execute_query(entity_query)

    from ..core.models import Entity as EntityModel
    entities = [
        EntityModel(id=r["id"], name=r["name"], type=r["type"])
        for r in rows if r.get("name")
    ]

    llm = LLMFactory.create(provider=settings.default_llm_provider)
    resolver = SemanticEntityResolver(llm)
    duplicate_groups = await resolver.resolve(entities)

    merged_count = 0
    groups_out = []
    for canonical_id, dupes in duplicate_groups.items():
        if len(dupes) > 1:
            group_names = [e.name for e in dupes]
            groups_out.append(group_names)
            # Merge each duplicate into the canonical entity
            for dupe in dupes[1:]:
                try:
                    await graph_store.merge_entities(canonical_id, dupe.id)
                    merged_count += 1
                except Exception:
                    pass

    return DeduplicateResponse(merged_count=merged_count, groups=groups_out)


@app.get("/api/graph/visualization", response_model=GraphVisualizationResponse, tags=["Graph"])
async def get_graph_visualization(
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Get graph data for visualization"""
    
    # Query for nodes and relationships
    query = """
    MATCH (n:Entity)
    WITH n LIMIT $limit
    OPTIONAL MATCH (n)-[r]->(m:Entity)
    RETURN 
        collect(DISTINCT {id: id(n), label: n.name, type: n.type, properties: n.properties}) as nodes,
        collect(DISTINCT {source: id(n), target: id(m), type: type(r)}) as edges
    """
    
    result = await graph_store.execute_query(query, {"limit": limit})
    
    if not result:
        return GraphVisualizationResponse(nodes=[], edges=[])
    
    data = result[0]
    
    import json as _json

    def _parse_props(raw):
        """Properties are stored as a JSON string in Neo4j; coerce back to dict."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return _json.loads(raw)
            except Exception:
                return {}
        return {}

    # Convert to response model
    nodes = [
        GraphNode(
            id=str(n["id"]),
            label=n.get("label", "Unknown"),
            type=n.get("type", "Entity"),
            properties=_parse_props(n.get("properties"))
        )
        for n in data.get("nodes", []) if n
    ]
    
    edges = [
        GraphEdge(
            source=str(e["source"]),
            target=str(e["target"]),
            type=e.get("type", "RELATED_TO")
        )
        for e in data.get("edges", []) if e and e.get("target")
    ]
    
    return GraphVisualizationResponse(nodes=nodes, edges=edges)


# System Endpoints

@app.get("/api/system/health", response_model=SystemHealthResponse, tags=["System"])
async def health_check():
    """System health check"""
    
    neo4j_connected = False
    redis_connected = False
    workers_active = 0
    
    try:
        # Check Neo4j
        await graph_store.execute_query("RETURN 1")
        neo4j_connected = True
    except:
        pass
    
    try:
        # Check Redis
        await redis_client.ping()
        redis_connected = True
    except:
        pass
    
    try:
        # Check Celery workers
        inspect = celery_app.control.inspect()
        active = inspect.active()
        if active:
            workers_active = len(active)
    except:
        pass
    
    overall_status = "healthy" if (neo4j_connected and redis_connected) else "degraded"
    
    return SystemHealthResponse(
        status=overall_status,
        version=settings.app_version,
        neo4j_connected=neo4j_connected,
        redis_connected=redis_connected,
        workers_active=workers_active,
        timestamp=datetime.utcnow()
    )


@app.get("/api/system/stats", response_model=SystemStatsResponse, tags=["System"])
async def get_system_stats(current_user: User = Depends(get_current_user)):
    """Get system statistics"""
    
    # Count documents
    doc_query = "MATCH (d:Document) RETURN count(d) as count"
    doc_result = await graph_store.execute_query(doc_query)
    documents_count = doc_result[0]["count"] if doc_result else 0
    
    # Count entities
    entity_query = "MATCH (e:Entity) RETURN count(e) as count"
    entity_result = await graph_store.execute_query(entity_query)
    entities_count = entity_result[0]["count"] if entity_result else 0
    
    # Count relationships
    rel_query = "MATCH ()-[r]->() RETURN count(r) as count"
    rel_result = await graph_store.execute_query(rel_query)
    relationships_count = rel_result[0]["count"] if rel_result else 0
    
    # Count chunks
    chunk_query = "MATCH (c:Chunk) RETURN count(c) as count"
    chunk_result = await graph_store.execute_query(chunk_query)
    chunks_count = chunk_result[0]["count"] if chunk_result else 0
    
    ontology = ingestion_pipeline.get_ontology()
    ontology_version = ontology.version if ontology else "none"
    
    return SystemStatsResponse(
        documents_count=documents_count,
        entities_count=entities_count,
        relationships_count=relationships_count,
        chunks_count=chunks_count,
        ontology_version=ontology_version
    )


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs"
    }
