"""
FastAPI application - Main API server
Unified API gateway for the Graph RAG service
"""

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import shutil
import json
import asyncio
import os
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
    RegisterRequest,
    TokenResponse,
    DocumentUploadResponse,
    DocumentInfo,
    DocumentListResponse,
    QueryRequest,
    QueryResponse,
    ConfidenceJudgmentResponse,
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
    DeduplicateResponse,
    Message,
    Conversation,
    ConversationListResponse,
    ScrapeRequest,
    CrawlRequest,
    EntityUpdateRequest,
    # New models (Gap #8, #2, #9)
    EvalRequest,
    EvalResponse,
    EvalDashboardResponse,
    EvalTrendPoint,
    CommunityAssignResponse,
    CommunitySummaryResponse,
    SupportedFormatsResponse,
    # MiroFish integration models
    GraphUpdateRequest,
    GraphUpdateResponse,
    EnrichmentStatusResponse,
    EntitySummaryResponse,
    ReportRequest,
    ReportResponse,
    EntityChatRequest,
    EntityChatResponse,
    DriftReportResponse,
    DriftListResponse,
)

from ..config import settings
from ..core.neo4j_store import Neo4jStore
from ..retrieval.agent import AgentRetrievalSystem
from ..retrieval.report_agent import ReportAgent
from ..ingestion.pipeline import IngestionPipeline
from ..ingestion.ontology_generator import OntologyGenerator
from ..core.entity_resolver import SemanticEntityResolver
from ..core.llm_factory import LLMFactory, UnifiedLLMProvider
from ..core.storage import get_storage
from ..workers.celery_worker import celery_app, ingest_document_task
from ..services.graph_memory_updater import GraphMemoryUpdater
from ..services.entity_enricher import EntityEnricher
from ..services.ontology_drift_detector import OntologyDriftDetector
from . import admin
from .simulation import router as simulation_router

# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Agentic Graph RAG as a Service - Production-grade knowledge graph platform"
)

app.include_router(simulation_router)

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
storage = get_storage()


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
    


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    if graph_store:
        await graph_store.disconnect()
    if ingestion_pipeline:
        await ingestion_pipeline.close()
    if redis_client:
        await redis_client.close()


# Include Sub-routers
app.include_router(admin.router)

# Authentication Endpoints

@app.post("/api/auth/register", response_model=User, tags=["Authentication"])
async def register(request: RegisterRequest):
    """Register a new user"""
    existing_user = await graph_store.get_user(request.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    hashed_password = get_password_hash(request.password)
    user_data = {
        "username": request.username,
        "hashed_password": hashed_password,
        "email": request.email,
        "full_name": request.full_name,
        "disabled": False,
        "scopes": request.scopes
    }
    
    await graph_store.create_user(user_data)
    
    return User(
        username=request.username,
        email=request.email,
        full_name=request.full_name,
        disabled=False,
        scopes=request.scopes
    )

@app.post("/api/auth/login", response_model=TokenResponse, tags=["Authentication"])
async def login(request: LoginRequest):
    """
    Login and get access token
    Verifies user against Neo4j database
    """
    user_data = await graph_store.get_user(request.username)
    if not user_data or not verify_password(request.password, user_data["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if user_data.get("disabled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    
    # Create access token
    access_token = create_access_token(
        data={
            "sub": user_data["username"],
            "scopes": user_data.get("scopes", ["read", "write"])
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


@app.post("/api/documents/scrape", response_model=DocumentUploadResponse, tags=["Documents"])
async def scrape_url(
    request: ScrapeRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Scrape URL content into text and ingest it.
    """
    import httpx
    from bs4 import BeautifulSoup
    import markdownify
    import re
    from ..ingestion.web_crawler import WebCrawler

    try:
        import sys
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')

        # We will attempt to use the powerful AsyncWebCrawler which runs Playwright headless and naturally bypasses 403 blocks.
        crawler = WebCrawler(max_depth=0, max_pages=1)
        results = await crawler.crawl(request.url)
        
        if not results or not results[0].get("markdown"):
            raise ValueError("No content was returned by the crawler.")
            
        text = results[0]["markdown"]
        title = results[0].get("title", "scraped_page")
        if not title:
            title = "scraped_page"
            
        safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', title)
        filename = f"{safe_title}.md"
        
        # Save to disk
        file_path = settings.upload_dir / filename
        
        with file_path.open("w", encoding="utf-8") as buffer:
            buffer.write(text)
            
        file_size = file_path.stat().st_size
        
        # Queue ingestion
        task = ingest_document_task.delay(
            str(file_path),
            ontology_dict=None
        )
        
        return DocumentUploadResponse(
            document_id=str(file_path.stem),
            filename=filename,
            size_bytes=file_size,
            task_id=task.id,
            message="URL scraped and ingestion initiated successfully."
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scrape URL: {str(e)}"
        )


@app.post("/api/documents/crawl", tags=["Documents"])
async def crawl_urls(
    request: CrawlRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Advanced async Web Crawling using locally-hosted Crawl4AI (Playwright).
    This extracts clean Markdown format and queues items into Celery for Graph ingestion.
    """
    from ..ingestion.web_crawler import WebCrawler
    import re
    import hashlib
    
    crawler = WebCrawler(max_depth=request.max_depth, max_pages=request.max_pages)
    
    async def run_crawl_and_ingest():
        try:
            results = await crawler.crawl(request.url)
            for page in results:
                if not page.get("markdown"):
                    continue
                    
                # Create a safe filename
                safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', page.get("title", "page_") or "page_")
                url_hash = hashlib.md5(page['url'].encode()).hexdigest()[:6]
                filename = f"crawled_{safe_title}_{url_hash}.txt"
                
                file_content = f"# Source Metadata\n- URL: {page['url']}\n- Title: {page['title']}\n\n"
                file_content += page["markdown"]
                
                storage.save_file(filename, file_content.encode("utf-8"))
                    
                # Queue parsing
                ingest_document_task.delay(filename, ontology_dict=None)
                
        except Exception as e:
            import logging
            logging.error(f"Crawling pipeline failed for {request.url}: {e}")
            
    background_tasks.add_task(run_crawl_and_ingest)
    
    return {
        "message": f"Crawler started asynchronously for {request.url} (up to {request.max_pages} pages)",
        "status": "processing"
    }


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
    # We must retrieve the filename from the graph before deleting the node
    query = "MATCH (d:Document {id: $doc_id}) RETURN d.filename as filename"
    results = await graph_store.execute_query(query, {"doc_id": document_id})
    filename_to_delete = results[0]["filename"] if results and results[0].get("filename") else None

    delete_query = """
    MATCH (d:Document {id: $doc_id})
    OPTIONAL MATCH (d)-[:CONTAINS]->(c:Chunk)
    DETACH DELETE c, d
    """
    await graph_store.execute_query(delete_query, {"doc_id": document_id})

    # Remove uploaded file from storage
    if filename_to_delete:
        try:
            storage.delete_file(filename_to_delete)
        except Exception:
            pass

    return {"status": "deleted", "document_id": document_id}

@app.get("/api/documents/{document_id}/download", tags=["Documents"])
async def download_document(
    document_id: str,
    current_user: User = Depends(get_current_user)
):
    """Download an uploaded document"""
    from fastapi.responses import FileResponse
    
    # 1. Look up the real filename associated with this hashed ID
    query = "MATCH (d:Document {id: $doc_id}) RETURN d.filename as filename"
    results = await graph_store.execute_query(query, {"doc_id": document_id})
    
    filename_target = results[0]["filename"] if results and results[0].get("filename") else None
    
    if filename_target:
        possible_path = settings.upload_dir / filename_target
        if possible_path.exists():
            return FileResponse(
                path=possible_path,
                filename=filename_target,
                content_disposition_type="inline"
            )
            
    # 2. Backups: Iterate and match stem or try URL fallback
    for f in settings.upload_dir.iterdir():
        if f.stem == document_id or f.name.startswith(document_id):
            return FileResponse(
                path=f,
                filename=f.name,
                content_disposition_type="inline"
            )
            
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Document file '{filename_target}' not found on disk"
    )



@app.get("/api/documents/{document_id}/preview", tags=["Documents"])
async def preview_document(
    document_id: str,
    current_user: User = Depends(get_current_user)
):
    """Return raw text content of a document for in-app preview (works for .txt, .md scraped files)."""
    from fastapi.responses import JSONResponse

    query = "MATCH (d:Document {id: $doc_id}) RETURN d.filename as filename, d.file_type as file_type"
    results = await graph_store.execute_query(query, {"doc_id": document_id})

    if not results or not results[0].get("filename"):
        raise HTTPException(status_code=404, detail="Document not found in graph")

    filename = results[0]["filename"]
    file_type = results[0]["file_type"] or ""
    file_path = settings.upload_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found on disk")

    if file_type.lower() not in (".txt", ".md", ""):
        raise HTTPException(status_code=415, detail="Preview only supported for text files. Use download for PDFs.")

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        word_count = len(content.split())
        char_count = len(content)
        return JSONResponse({
            "filename": filename,
            "file_type": file_type,
            "word_count": word_count,
            "char_count": char_count,
            "content": content
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")


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


# Conversations / Memory Endpoints

@app.get("/api/conversations", response_model=ConversationListResponse, tags=["Memory"])
async def list_conversations(current_user: User = Depends(get_current_user)):
    """List all conversation threads for current user"""
    query = """
    MATCH (u:User {username: $username})-[:HAS_CONVERSATION]->(c:Conversation)
    RETURN c.id as id, c.title as title, c.created_at as created_at, c.updated_at as updated_at
    ORDER BY c.updated_at DESC
    """
    results = await graph_store.execute_query(query, {"username": current_user.username})
    
    convs = []
    for r in results:
        convs.append(Conversation(
            id=r["id"],
            title=r["title"],
            created_at=r.get("created_at", datetime.now().isoformat()),
            updated_at=r.get("updated_at", datetime.now().isoformat())
        ))
    return ConversationListResponse(conversations=convs)


@app.get("/api/conversations/{conversation_id}", response_model=Conversation, tags=["Memory"])
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get a specific conversation thread and its messages"""
    query = """
    MATCH (u:User {username: $username})-[:HAS_CONVERSATION]->(c:Conversation {id: $conversation_id})
    OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
    RETURN c.id as id, c.title as title, c.created_at as created_at, c.updated_at as updated_at,
           m.id as msg_id, m.role as role, m.content as content, 
           m.reasoning as reasoning_str, m.sources as sources_str, m.created_at as msg_created_at
    ORDER BY m.created_at ASC
    """
    results = await graph_store.execute_query(query, {
        "username": current_user.username,
        "conversation_id": conversation_id
    })
    
    if not results:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    c_info = results[0]
    messages = []
    import json
    for r in results:
        if r.get("msg_id"):
            reasoning = json.loads(r["reasoning_str"]) if r.get("reasoning_str") else []
            sources = json.loads(r["sources_str"]) if r.get("sources_str") else []
            messages.append(Message(
                id=r["msg_id"],
                role=r["role"],
                content=r["content"],
                reasoning=reasoning,
                sources=sources,
                created_at=r.get("msg_created_at", "")
            ))
            
    return Conversation(
        id=c_info["id"],
        title=c_info["title"],
        created_at=c_info.get("created_at", ""),
        updated_at=c_info.get("updated_at", ""),
        messages=messages
    )


@app.delete("/api/conversations/{conversation_id}", tags=["Memory"])
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete a conversation thread"""
    query = """
    MATCH (u:User {username: $username})-[:HAS_CONVERSATION]->(c:Conversation {id: $conversation_id})
    OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
    DETACH DELETE c, m
    """
    await graph_store.execute_query(query, {
        "username": current_user.username,
        "conversation_id": conversation_id
    })
    return {"status": "deleted", "conversation_id": conversation_id}


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

    import uuid
    import json
    conversation_id = request.conversation_id or str(uuid.uuid4())
    
    # 1. Initialize conversation and user message in Neo4j
    now_str = datetime.now().isoformat()
    init_query = """
    MATCH (u:User {username: $username})
    MERGE (u)-[:HAS_CONVERSATION]->(c:Conversation {id: $conversation_id})
    ON CREATE SET c.title = $title, c.created_at = $now, c.updated_at = $now
    ON MATCH SET c.updated_at = $now
    CREATE (c)-[:HAS_MESSAGE]->(m:Message {
        id: $msg_id, role: 'user', content: $query, created_at: $now
    })
    """
    await graph_store.execute_query(init_query, {
        "username": current_user.username,
        "conversation_id": conversation_id,
        "title": request.query[:40] + ("..." if len(request.query) > 40 else ""),
        "now": now_str,
        "msg_id": str(uuid.uuid4()),
        "query": request.query
    })

    async def save_assistant_message(content, reasoning, sources):
        save_query = """
        MATCH (c:Conversation {id: $conversation_id})
        SET c.updated_at = $now
        CREATE (c)-[:HAS_MESSAGE]->(m:Message {
            id: $msg_id, role: 'assistant', content: $content, 
            created_at: $now, reasoning: $reasoning, sources: $sources
        })
        """
        # Serialize sources (convert dicts to string) to store cleanly
        sources_serializable = []
        for s in sources:
            if isinstance(s, dict):
                sources_serializable.append(s)
            elif hasattr(s, "dict"):
                sources_serializable.append(s.dict())
            else:
                sources_serializable.append({"text": str(s)})
                
        await graph_store.execute_query(save_query, {
            "conversation_id": conversation_id,
            "now": datetime.now().isoformat(),
            "msg_id": str(uuid.uuid4()),
            "content": content,
            "reasoning": json.dumps(reasoning),
            "sources": json.dumps(sources_serializable)
        })

    if request.streaming:
        async def event_stream():
            reasoning_steps = []
            final_answer = ""
            final_sources = []

            # Yield conversation ID meta event so frontend knows the thread ID
            yield f"data: {json.dumps({'type': 'meta', 'conversation_id': conversation_id})}\n\n"

            async for chunk in retrieval_agent.astream(
                query=request.query,
                top_k=request.top_k,
                document_id=request.document_id,
                use_got=request.use_got or False,
            ):
                steps = chunk.get("reasoning_steps", [])
                new_steps = steps[len(reasoning_steps):]
                for step in new_steps:
                    reasoning_steps.append(step)
                    yield f"data: {json.dumps({'type': 'step', 'content': step})}\n\n"

                if chunk.get("answer"):
                    final_answer = chunk["answer"]
                    final_sources = chunk.get("contexts", [])
                    payload = {
                        "type": "answer",
                        "answer": chunk["answer"],
                        "confidence": chunk.get("confidence", 0.0),
                        "retrieval_method": "agentic_hybrid",
                        "reasoning_chain": chunk.get("reasoning_steps", []),
                        "sources": chunk.get("contexts", []),
                        "drift_expanded": chunk.get("drift_expanded", False),
                    }
                    yield f"data: {json.dumps(payload, default=str)}\n\n"

            if final_answer and final_sources:
                from src.graph_rag_service.config import settings
                if settings.enable_llm_judge:
                    yield f"data: {json.dumps({'type': 'step', 'content': 'LLM Judge verifying context grounding...'})}\n\n"
                    try:
                        judge_data = await retrieval_agent.judge.score(
                            query=request.query,
                            answer=final_answer,
                            contexts=final_sources
                        )
                        payload["confidence"] = judge_data["score"]
                        payload["hallucination_risk"] = judge_data["hallucination_risk"]
                        payload["confidence_reasoning"] = judge_data["reasoning"]
                        yield f"data: {json.dumps(payload, default=str)}\n\n"
                    except Exception as e:
                        print(f"Judge stream error: {e}")

            await save_assistant_message(final_answer, reasoning_steps, final_sources)
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # Non-streaming path
    result = await retrieval_agent.query(
        query=request.query,
        top_k=request.top_k,
        document_id=request.document_id,
        use_got=request.use_got or False,
    )

    await save_assistant_message(result.answer, result.reasoning_chain, result.sources)

    # Build confidence judgment response if available
    cj_response = None
    if result.confidence_judgment:
        cj = result.confidence_judgment
        cj_response = ConfidenceJudgmentResponse(
            score=cj.score,
            reasoning=cj.reasoning,
            grounded_claims=cj.grounded_claims,
            ungrounded_claims=cj.ungrounded_claims,
            hallucination_risk=cj.hallucination_risk
        )

    return QueryResponse(
        answer=result.answer,
        sources=result.sources,
        reasoning_chain=result.reasoning_chain,
        confidence=result.confidence,
        confidence_judgment=cj_response,
        retrieval_method=result.retrieval_method,
        processing_time_seconds=result.processing_time_seconds,
        conversation_id=conversation_id,
        drift_expanded=result.drift_expanded,
        total_sub_queries=result.total_sub_queries,
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


@app.get("/api/ontology/stats", tags=["Ontology"])
async def get_ontology_stats(
    document_id: str = None,
    current_user: User = Depends(get_current_user)
):
    """Return entity type counts and relationship type counts, optionally filtered to a document."""
    from fastapi.responses import JSONResponse

    if document_id:
        entity_q = """
        MATCH (:Document {id: $doc_id})-[:CONTAINS]->(:Chunk)-[:MENTIONS]->(e:Entity)
        RETURN e.type as type, count(DISTINCT e) as count
        ORDER BY count DESC
        """
        rel_q = """
        MATCH (:Document {id: $doc_id})-[:CONTAINS]->(:Chunk)-[:MENTIONS]->(a:Entity)
        MATCH (a)-[r]->(b:Entity)<-[:MENTIONS]-(:Chunk)<-[:CONTAINS]-(:Document {id: $doc_id})
        RETURN type(r) as rel_type, count(r) as count
        ORDER BY count DESC
        """
        entity_rows = await graph_store.execute_query(entity_q, {"doc_id": document_id})
        rel_rows = await graph_store.execute_query(rel_q, {"doc_id": document_id})
    else:
        entity_q = """
        MATCH (e:Entity) RETURN e.type as type, count(e) as count ORDER BY count DESC
        """
        rel_q = """
        MATCH ()-[r]->() WHERE type(r) <> 'HAS_CONVERSATION' AND type(r) <> 'HAS_MESSAGE'
        AND type(r) <> 'CONTAINS' AND type(r) <> 'MENTIONS'
        RETURN type(r) as rel_type, count(r) as count ORDER BY count DESC LIMIT 20
        """
        entity_rows = await graph_store.execute_query(entity_q)
        rel_rows = await graph_store.execute_query(rel_q)

    entity_stats = [{"type": r["type"] or "Unknown", "count": r["count"]} for r in entity_rows if r.get("type")]
    rel_stats = [{"type": r["rel_type"] or "Unknown", "count": r["count"]} for r in rel_rows if r.get("rel_type")]

    return JSONResponse({
        "entity_stats": entity_stats,
        "relationship_stats": rel_stats,
        "total_entities": sum(s["count"] for s in entity_stats),
        "total_relationships": sum(s["count"] for s in rel_stats)
    })


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
    if request.document_id:
        sample_query = "MATCH (d:Document {id: $doc_id})-[:CONTAINS]->(c:Chunk) RETURN c.text as text LIMIT 10"
        sample_rows = await graph_store.execute_query(sample_query, {"doc_id": request.document_id})
    else:
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
    current_user: User = Depends(get_current_user)
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
    current_user: User = Depends(get_current_user)
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
    document_id: str = None,
    current_user: User = Depends(get_current_user)
):
    """Get graph data for visualization"""
    
    # Query for nodes and relationships
    if document_id:
        # Collect entity IDs for this document first, then filter edges to stay within that set.
        # We cannot use `d` in a WHERE clause after WITH drops it (Neo4j 5 syntax rule).
        query = """
        MATCH (:Document {id: $document_id})-[:CONTAINS]->(:Chunk)-[:MENTIONS]->(n:Entity)
        WITH DISTINCT n LIMIT $limit
        OPTIONAL MATCH (n)-[r]->(m:Entity)<-[:MENTIONS]-(:Chunk)<-[:CONTAINS]-(:Document {id: $document_id})
        RETURN 
            collect(DISTINCT {id: coalesce(n.id, toString(id(n))), label: n.name, type: n.type, description: n.description, properties: properties(n)}) as nodes,
            collect(DISTINCT {source: coalesce(n.id, toString(id(n))), target: coalesce(m.id, toString(id(m))), type: type(r)}) as edges
        """
        result = await graph_store.execute_query(query, {"limit": limit, "document_id": document_id})
    else:
        query = """
        MATCH (n:Entity)
        WITH n LIMIT $limit
        OPTIONAL MATCH (n)-[r]->(m:Entity)
        RETURN 
            collect(DISTINCT {id: coalesce(n.id, toString(id(n))), label: n.name, type: n.type, description: n.description, properties: properties(n)}) as nodes,
            collect(DISTINCT {source: coalesce(n.id, toString(id(n))), target: coalesce(m.id, toString(id(m))), type: type(r)}) as edges
        """
        result = await graph_store.execute_query(query, {"limit": limit})

    
    if not result:
        return GraphVisualizationResponse(nodes=[], edges=[])
    
    data = result[0]
    
    import json as _json

    def _clean_neo4j_types(val):
        if isinstance(val, dict):
            return {k: _clean_neo4j_types(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_clean_neo4j_types(v) for v in val]
        if isinstance(val, (str, int, float, bool, type(None))):
            return val
        # For Neo4j DateTime/Date objects
        if hasattr(val, "iso_format"):
            return val.iso_format()
        return str(val)

    def _parse_props(raw):
        """Properties are stored as a JSON string in Neo4j or returned as map; coerce back to serializable dict."""
        props = {}
        if isinstance(raw, dict):
            props = raw
        elif isinstance(raw, str):
            try:
                props = _json.loads(raw)
            except Exception:
                pass
        return _clean_neo4j_types(props)

    # Convert to response model
    nodes = [
        GraphNode(
            id=str(n["id"]),
            label=n.get("label", "Unknown"),
            type=n.get("type", "Entity"),
            description=n.get("description"),
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


@app.get("/api/system/my-stats", tags=["System"])
async def get_my_stats(current_user: User = Depends(get_current_user)):
    """Get activity stats for the currently authenticated user."""
    from fastapi.responses import JSONResponse

    username = current_user.username

    conv_q = """
    MATCH (u:User {username: $username})-[:HAS_CONVERSATION]->(c:Conversation)
    RETURN count(DISTINCT c) as conversation_count
    """
    msg_q = """
    MATCH (u:User {username: $username})-[:HAS_CONVERSATION]->(c:Conversation)-[:HAS_MESSAGE]->(m)
    WHERE m.role = 'user'
    RETURN count(m) as message_count, max(m.timestamp) as last_active
    """
    try:
        conv_rows = await graph_store.execute_query(conv_q, {"username": username})
        msg_rows = await graph_store.execute_query(msg_q, {"username": username})
        conversation_count = conv_rows[0]["conversation_count"] if conv_rows else 0
        message_count = msg_rows[0]["message_count"] if msg_rows else 0
        last_active = msg_rows[0]["last_active"] if msg_rows else None
        if hasattr(last_active, "iso_format"):
            last_active = last_active.iso_format()
    except Exception:
        conversation_count = 0
        message_count = 0
        last_active = None

    return JSONResponse({
        "username": username,
        "conversation_count": conversation_count,
        "message_count": message_count,
        "last_active": last_active,
    })


@app.post("/api/admin/documents/{doc_id}/reingest", tags=["Admin"])
async def reingest_document(
    doc_id: str,
    current_user: User = Depends(get_current_user)
):
    """Re-queue a document for ingestion processing (admin only)."""
    from fastapi.responses import JSONResponse
    if "admin" not in (current_user.scopes or []):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Fetch document node from graph
    doc_q = "MATCH (d:Document {id: $doc_id}) RETURN d.id as id, d.filename as filename, d.file_path as file_path, d.source as source LIMIT 1"
    rows = await graph_store.execute_query(doc_q, {"doc_id": doc_id})
    if not rows:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc = rows[0]
    file_path = doc.get("file_path") or doc.get("source")
    filename = doc.get("filename", doc_id)

    if not file_path:
        raise HTTPException(status_code=422, detail="Document has no stored file path; cannot re-ingest.")

    import os
    if not os.path.exists(file_path):
        raise HTTPException(status_code=422, detail=f"Source file not found on disk: {file_path}")

    # Reset status in graph
    reset_q = "MATCH (d:Document {id: $doc_id}) SET d.status = 'pending' RETURN d.id"
    await graph_store.execute_query(reset_q, {"doc_id": doc_id})

    # Dispatch Celery task
    from ..workers.celery_app import celery_app as celery
    task = celery.send_task(
        "graph_rag_service.workers.tasks.process_document",
        args=[file_path, doc_id],
        kwargs={}
    )

    return JSONResponse({"status": "queued", "doc_id": doc_id, "filename": filename, "task_id": task.id})


# ── Gap #8: Evaluation / Quality Dashboard Endpoints ──────────────────────────

@app.post("/api/eval/score", response_model=EvalResponse, tags=["Evaluation"])
async def evaluate_response(
    request: EvalRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Run RAGAS-style quality evaluation on a Q&A pair.
    Measures faithfulness, relevancy, and context precision.
    Results are persisted in Neo4j for the quality dashboard.
    """
    from ..retrieval.tools import RAGEvaluator
    from ..core.llm_factory import LLMFactory
    from ..core.models import EvalResult

    llm = LLMFactory.create(provider=settings.default_llm_provider)
    evaluator = RAGEvaluator(llm)

    metrics = await evaluator.evaluate(
        question=request.question,
        answer=request.answer,
        contexts=request.contexts,
        ground_truth=request.ground_truth
    )

    eval_record = EvalResult(
        question=request.question,
        answer=request.answer,
        faithfulness=metrics["faithfulness"],
        answer_relevancy=metrics["answer_relevancy"],
        context_precision=metrics["context_precision"],
        overall_score=metrics["overall_score"],
        hallucination_detected=metrics["hallucination_detected"],
        document_id=request.document_id
    )
    eval_id = await graph_store.save_eval_result(eval_record)

    return EvalResponse(
        question=request.question,
        faithfulness=metrics["faithfulness"],
        answer_relevancy=metrics["answer_relevancy"],
        context_precision=metrics["context_precision"],
        overall_score=metrics["overall_score"],
        hallucination_detected=metrics["hallucination_detected"],
        eval_id=eval_id
    )


@app.get("/api/eval/dashboard", response_model=EvalDashboardResponse, tags=["Evaluation"])
async def get_eval_dashboard(
    limit: int = 100,
    current_user: User = Depends(get_current_user)
):
    """Retrieve evaluation history for the quality dashboard"""
    rows = await graph_store.get_eval_results(limit=limit)

    if not rows:
        return EvalDashboardResponse(
            total_evaluations=0,
            avg_overall_score=0.0,
            avg_faithfulness=0.0,
            avg_relevancy=0.0,
            hallucination_rate=0.0,
            trend_data=[]
        )

    total = len(rows)
    avg_score = sum(r.get("overall_score", 0) for r in rows) / total
    avg_faith = sum(r.get("faithfulness", 0) for r in rows) / total
    avg_rel = sum(r.get("answer_relevancy", 0) for r in rows) / total
    hall_rate = sum(1 for r in rows if r.get("hallucination_detected")) / total

    trend = [
        EvalTrendPoint(
            timestamp=str(r.get("timestamp", ""))[:19],
            overall_score=r.get("overall_score", 0.0),
            faithfulness=r.get("faithfulness", 0.0),
            answer_relevancy=r.get("answer_relevancy", 0.0),
            hallucination_detected=bool(r.get("hallucination_detected")),
            document_id=r.get("document_id")
        )
        for r in rows
    ]

    return EvalDashboardResponse(
        total_evaluations=total,
        avg_overall_score=round(avg_score, 4),
        avg_faithfulness=round(avg_faith, 4),
        avg_relevancy=round(avg_rel, 4),
        hallucination_rate=round(hall_rate, 4),
        trend_data=trend
    )


# ── Gap #2: Community Detection Endpoints ─────────────────────────────────────

@app.post("/api/graph/communities/assign", response_model=CommunityAssignResponse, tags=["Graph"])
async def assign_communities(
    current_user: User = Depends(get_current_user)
):
    """
    Detect and assign community IDs to all entities using connected-components (WCC).
    Run this after ingesting new documents to update community clustering.
    """
    count = await graph_store.assign_community_ids()
    return CommunityAssignResponse(
        communities_found=count,
        message=f"Assigned {count} community IDs to entities. Community search is now active."
    )


@app.get("/api/graph/communities", tags=["Graph"])
async def list_communities(
    limit: int = 20,
    current_user: User = Depends(get_current_user)
):
    """List top communities with entity counts"""
    from fastapi.responses import JSONResponse
    query = """
    MATCH (e:Entity)
    WHERE e.community_id IS NOT NULL
    RETURN e.community_id as community_id,
           count(e) as entity_count,
           collect(e.name)[0..5] as sample_entities
    ORDER BY entity_count DESC
    LIMIT $limit
    """
    rows = await graph_store.execute_query(query, {"limit": limit})
    return JSONResponse({"communities": rows, "total": len(rows)})


# ── Gap #5: Temporal Query Endpoint ───────────────────────────────────────────

@app.get("/api/entities/{entity_name}/at-time", tags=["Entities"])
async def get_entity_at_time(
    entity_name: str,
    at_time: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get the relationships of an entity at a specific point in time.
    Supports temporal knowledge graph queries.
    at_time format: ISO 8601 e.g. '2023-06-01T00:00:00'
    """
    from fastapi.responses import JSONResponse
    from datetime import datetime as dt
    try:
        time_obj = dt.fromisoformat(at_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO 8601.")

    results = await graph_store.get_entities_at_time(entity_name=entity_name, at_time=time_obj)
    return JSONResponse({"entity": entity_name, "at_time": at_time, "relationships": results})


# ── Gap #9: Supported Formats ─────────────────────────────────────────────────

@app.get("/api/system/formats", response_model=SupportedFormatsResponse, tags=["System"])
async def get_supported_formats():
    """List supported ingestion file formats"""
    return SupportedFormatsResponse(
        formats=settings.allowed_file_types,
        descriptions={
            ".pdf": "PDF documents (LlamaParse or pypdf)",
            ".txt": "Plain text files",
            ".md": "Markdown files",
            ".docx": "Microsoft Word documents",
            ".csv": "CSV spreadsheets (rows → entity facts)",
            ".xlsx": "Excel spreadsheets (all sheets processed)",
            ".pptx": "PowerPoint presentations (slides + notes)",
            ".json": "JSON data files (nested structures flattened)",
        }
    )


# ── Graph Export Endpoint ─────────────────────────────────────────────────────

@app.get("/api/graph/export", tags=["Graph"])
async def export_graph(
    format: str = "json",
    document_id: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Export the knowledge graph in multiple formats.
    Supported: json, cypher, graphml
    """
    from fastapi.responses import JSONResponse, PlainTextResponse

    doc_filter = "MATCH (:Document {id: $doc_id})-[:CONTAINS]->(:Chunk)-[:MENTIONS]->(e:Entity)" if document_id else "MATCH (e:Entity)"
    params = {"doc_id": document_id} if document_id else {}

    node_query = f"""
    {doc_filter}
    RETURN DISTINCT e.id as id, e.name as name, e.type as type,
           e.community_id as community_id, e.valid_from as valid_from, e.valid_until as valid_until
    LIMIT 2000
    """
    rel_query = """
    MATCH (a:Entity)-[r]->(b:Entity)
    WHERE type(r) NOT IN ['HAS_CONVERSATION', 'HAS_MESSAGE', 'CONTAINS', 'MENTIONS']
    RETURN a.name as source, b.name as target, type(r) as relationship,
           r.valid_from as valid_from, r.confidence as confidence
    LIMIT 5000
    """

    nodes = await graph_store.execute_query(node_query, params)
    rels = await graph_store.execute_query(rel_query)

    if format == "cypher":
        lines = ["// Graph export — Cypher format"]
        for n in nodes:
            escaped = (n.get('name') or '').replace("'", "\\'")
            lines.append(f"MERGE (:Entity {{name: '{escaped}', type: '{n.get('type', '')}'}});")
        for r in rels:
            src = (r.get('source') or '').replace("'", "\\'")
            tgt = (r.get('target') or '').replace("'", "\\'")
            rel = r.get('relationship', 'RELATED_TO')
            lines.append(f"MATCH (a:Entity {{name: '{src}'}}), (b:Entity {{name: '{tgt}'}}) MERGE (a)-[:{rel}]->(b);")
        return PlainTextResponse("\n".join(lines), media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=graph_export.cypher"})

    elif format == "graphml":
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<graphml xmlns="http://graphml.graphdrawing.org/graphml">',
                 '<graph id="G" edgedefault="directed">']
        for n in nodes:
            nid = (n.get('id') or n.get('name') or '').replace('&', '&amp;').replace('<', '&lt;')
            label = (n.get('name') or '').replace('&', '&amp;').replace('<', '&lt;')
            ntype = n.get('type', 'Entity')
            lines.append(f'  <node id="{nid}"><data key="label">{label}</data><data key="type">{ntype}</data></node>')
        for i, r in enumerate(rels):
            src = (r.get('source') or '').replace('&', '&amp;').replace('<', '&lt;')
            tgt = (r.get('target') or '').replace('&', '&amp;').replace('<', '&lt;')
            rel = r.get('relationship', 'RELATED_TO')
            lines.append(f'  <edge id="e{i}" source="{src}" target="{tgt}"><data key="label">{rel}</data></edge>')
        lines.extend(['</graph>', '</graphml>'])
        return PlainTextResponse("\n".join(lines), media_type="application/xml",
            headers={"Content-Disposition": "attachment; filename=graph_export.graphml"})

    # Default: JSON
    return JSONResponse({
        "nodes": nodes,
        "edges": rels,
        "node_count": len(nodes),
        "edge_count": len(rels),
        "export_format": "json"
    })


# ═══════════════════════════════════════════════════════════════════════════
# MiroFish Point 1: Graph Memory Updater Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/graph/update", response_model=GraphUpdateResponse, tags=["Graph"])
async def update_graph_from_text(
    request: GraphUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Merge raw text directly into the live knowledge graph.

    Entities and relationships are extracted via LLM and merged using MERGE
    (idempotent). Call this endpoint whenever new facts become available
    without needing a full document re-ingest cycle.

    Inspired by MiroFish's zep_graph_memory_updater.py.
    """
    updater = GraphMemoryUpdater(
        graph_store=graph_store,
        llm_provider=settings.default_llm_provider,
    )
    result = await updater.update_from_text(
        text=request.text,
        source_label=request.source_label or "api_push",
        valid_from=request.valid_from,
    )
    return GraphUpdateResponse(
        entities_added=result.entities_added,
        relationships_added=result.relationships_added,
        entities_merged=result.entities_merged,
        source_label=result.source_label,
        timestamp=result.timestamp,
        message=result.message,
    )


# ═══════════════════════════════════════════════════════════════════════════
# MiroFish Point 2: Entity Enricher Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/entities/enrich", response_model=EnrichmentStatusResponse, tags=["Entities"])
async def trigger_entity_enrichment(
    min_connections: int = 1,
    overwrite: bool = False,
    current_user: User = Depends(get_current_user),
):
    """
    Trigger entity enrichment: traverse each entity's graph neighborhood and
    synthesize an LLM profile summary stored as `e.summary`.

    Run after ingestion to enable entity-level retrieval.
    Inspired by MiroFish's oasis_profile_generator.py.
    """
    enricher = EntityEnricher(
        graph_store=graph_store,
        llm_provider=settings.default_llm_provider,
    )
    result = await enricher.enrich_all_entities(
        min_connections=min_connections,
        overwrite=overwrite,
    )
    return EnrichmentStatusResponse(
        entities_enriched=result.entities_enriched,
        entities_skipped=result.entities_skipped,
        errors=result.errors,
        duration_seconds=result.duration_seconds,
        message=result.message,
    )


@app.get("/api/entities/{entity_name}/summary", response_model=EntitySummaryResponse, tags=["Entities"])
async def get_entity_summary(
    entity_name: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get the enriched profile summary for a specific entity.
    Returns the LLM-synthesized description stored on the graph node.
    """
    enricher = EntityEnricher(graph_store=graph_store)
    summary = await enricher.get_entity_summary(entity_name)

    # Also fetch entity type
    rows = await graph_store.execute_query(
        "MATCH (e:Entity {name: $name}) RETURN e.type as type, "
        "toString(e.summary_updated_at) as updated_at",
        {"name": entity_name},
    )
    entity_type = rows[0].get("type") if rows else None
    updated_at = rows[0].get("updated_at") if rows else None

    return EntitySummaryResponse(
        entity_name=entity_name,
        entity_type=entity_type,
        summary=summary,
        summary_updated_at=updated_at,
        has_summary=bool(summary),
    )


# ═══════════════════════════════════════════════════════════════════════════
# MiroFish Point 3: Analytical Report Agent
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/report", response_model=ReportResponse, tags=["Report"])
async def generate_report(
    request: ReportRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Generate an analytical report using the full ReACT ReportAgent.

    The agent:
    1. Decomposes the topic into sub-questions
    2. Iteratively calls InsightForge / PanoramaSearch / QuickSearch tools
    3. Writes each section from retrieved knowledge graph data
    4. Compiles a structured markdown report

    Inspired by MiroFish's report_agent.py + InsightForge/PanoramaSearch/QuickSearch.
    """
    llm = UnifiedLLMProvider(provider=settings.default_llm_provider)
    agent = ReportAgent(store=graph_store, llm=llm)
    result = await agent.generate_report(
        topic=request.topic,
        report_type=request.report_type or "detailed",
        target_entity=request.target_entity,
    )
    return ReportResponse(
        topic=result.topic,
        executive_summary=result.executive_summary,
        sections=result.sections,
        key_entities=result.key_entities,
        confidence=result.confidence,
        tool_calls_made=result.tool_calls_made,
        generated_at=result.generated_at,
        markdown=result.markdown,
    )


# ═══════════════════════════════════════════════════════════════════════════
# MiroFish Point 3b: Entity Interview ("Talk to an Entity")
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/entities/{entity_name}/chat", response_model=EntityChatResponse, tags=["Entities"])
async def entity_interview(
    entity_name: str,
    request: EntityChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Have a focused conversation scoped to a single entity's graph neighborhood.

    The LLM answers entirely from that entity's knowledge graph context —
    not from its training data. Multi-turn supported via conversation_id.

    Inspired by MiroFish's live interview with simulation personas.
    """
    import uuid as _uuid

    # Fetch entity + 2-hop neighborhood
    neighbors = await graph_store.get_neighbors(entity_name, depth=2)

    # Fetch entity summary + direct relationships
    entity_rows = await graph_store.execute_query(
        "MATCH (e:Entity {name: $name}) RETURN e.type as type, e.summary as summary",
        {"name": entity_name},
    )
    entity_type = entity_rows[0].get("type", "Entity") if entity_rows else "Entity"
    entity_summary = entity_rows[0].get("summary") if entity_rows else None

    rel_rows = await graph_store.execute_query(
        """
        MATCH (e:Entity {name: $name})-[r]-(other:Entity)
        RETURN type(r) as rel_type, other.name as other_name, other.type as other_type
        LIMIT 25
        """,
        {"name": entity_name},
    )
    rel_lines = [
        f"  - {r['rel_type']} → {r['other_name']} ({r['other_type']})"
        for r in rel_rows
    ]
    neighborhood_size = len(neighbors)

    # Build scoped system prompt
    context_parts = [f"Entity: {entity_name} (Type: {entity_type})"]
    if entity_summary:
        context_parts.append(f"\nProfile summary:\n{entity_summary}")
    if rel_lines:
        context_parts.append(f"\nKnown relationships:\n" + "\n".join(rel_lines))
    context_parts.append(
        "\n\nAnswer questions about this entity ONLY from the above graph context. "
        "Do not add information not present in the context. "
        "If the context is insufficient, say so."
    )

    system_prompt = "\n".join(context_parts)

    # Load conversation history (last 5 exchanges if conversation_id given)
    conversation_id = request.conversation_id or str(_uuid.uuid4())
    history_prompt = ""
    if request.conversation_id:
        history_rows = await graph_store.execute_query(
            """
            MATCH (c:Conversation {id: $conv_id})-[:HAS_MESSAGE]->(m:Message)
            RETURN m.role as role, m.content as content
            ORDER BY m.created_at DESC
            LIMIT 10
            """,
            {"conv_id": request.conversation_id},
        )
        if history_rows:
            history_parts = [
                f"{r['role'].upper()}: {r['content'][:200]}"
                for r in reversed(history_rows)
            ]
            history_prompt = "\n\nPrevious conversation:\n" + "\n".join(history_parts)

    llm = UnifiedLLMProvider(provider=settings.default_llm_provider)
    full_prompt = (
        f"{history_prompt}\n\nUser question: {request.message}"
        if history_prompt
        else request.message
    )

    response_text = await llm.complete(
        prompt=full_prompt,
        system_prompt=system_prompt,
        temperature=0.3,
    )

    return EntityChatResponse(
        response=response_text.strip(),
        entity_name=entity_name,
        neighborhood_size=neighborhood_size,
        conversation_id=conversation_id,
    )


# ═══════════════════════════════════════════════════════════════════════════
# MiroFish Point 4: Ontology Drift Detection Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/ontology/drift/detect", response_model=DriftReportResponse, tags=["Ontology"])
async def trigger_drift_detection(
    sample_size: int = 10,
    current_user: User = Depends(get_current_user),
):
    """
    Manually trigger a drift detection cycle.
    Samples random chunks, proposes a new ontology, diffs against current.
    Returns a pending drift report for admin review.
    """
    detector = OntologyDriftDetector(
        graph_store=graph_store,
        llm_provider=settings.default_llm_provider,
    )
    report = await detector.detect_drift(sample_size=sample_size)
    if not report:
        raise HTTPException(
            status_code=404,
            detail="No ontology exists yet. Ingest documents first.",
        )
    return DriftReportResponse(
        id=report.id,
        detected_at=report.detected_at,
        new_entity_types=report.new_entity_types,
        new_relationship_types=report.new_relationship_types,
        removed_entity_types=report.removed_entity_types,
        removed_relationship_types=report.removed_relationship_types,
        sample_size=report.sample_size,
        drift_score=report.drift_score,
        status=report.status,
    )


@app.get("/api/ontology/drift", response_model=DriftListResponse, tags=["Ontology"])
async def list_drift_reports(
    status: Optional[str] = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
):
    """List all drift reports, optionally filtered by status (pending/approved/rejected)."""
    detector = OntologyDriftDetector(graph_store=graph_store)
    reports = await detector.list_drift_reports(status=status, limit=limit)
    report_responses = [
        DriftReportResponse(
            id=r.id,
            detected_at=r.detected_at,
            new_entity_types=r.new_entity_types,
            new_relationship_types=r.new_relationship_types,
            removed_entity_types=r.removed_entity_types,
            removed_relationship_types=r.removed_relationship_types,
            sample_size=r.sample_size,
            drift_score=r.drift_score,
            status=r.status,
            approved_by=r.approved_by,
            approved_at=r.approved_at,
        )
        for r in reports
    ]
    return DriftListResponse(reports=report_responses, total=len(report_responses))


@app.post("/api/ontology/drift/{report_id}/approve", tags=["Ontology"])
async def approve_drift_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Approve a drift report: merge the new entity/relationship types into
    the live ontology and bump the version number.
    """
    detector = OntologyDriftDetector(
        graph_store=graph_store,
        llm_provider=settings.default_llm_provider,
    )
    success = await detector.apply_drift_report(
        report_id=report_id,
        approved_by=current_user.username,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Drift report not found")
    return {"status": "approved", "report_id": report_id}


@app.post("/api/ontology/drift/{report_id}/reject", tags=["Ontology"])
async def reject_drift_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
):
    """Reject a drift report without applying any ontology changes."""
    detector = OntologyDriftDetector(graph_store=graph_store)
    success = await detector.reject_drift_report(report_id)
    if not success:
        raise HTTPException(status_code=404, detail="Drift report not found")
    return {"status": "rejected", "report_id": report_id}


# ── Frontend Static Files Hosting ─────────────────────────────────────────────

FRONTEND_DIST = r"D:\Desktop_March_26\LYZR\graph-RAG\frontend-react\dist"

if os.path.exists(FRONTEND_DIST) and os.path.isdir(FRONTEND_DIST):
    # Mount frontend static assets if they exist (Vite uses /assets by default)
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.exists(assets_dir) and os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    # Catch-all route for SPA routing (except for /api and /docs)
    @app.get("/{full_path:path}", tags=["Frontend SPA"])
    async def serve_frontend(full_path: str):
        # Exclude API and Swagger UI routes from SPA catch-all
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
            raise HTTPException(status_code=404, detail="API route not found")
            
        file_path = os.path.join(FRONTEND_DIST, full_path)
        # Serve literal requested file if it exists (e.g. vite.svg, favicon.ico)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
            
        # Fallback to index.html for client-side routing
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
            
        raise HTTPException(status_code=404, detail="Frontend path not found")
else:
    @app.get("/", tags=["Root"])
    async def root():
        """Root endpoint (fallback when frontend is not built)"""
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "status": "running",
            "docs": "/docs",
            "message": "Frontend build not mounted. Please build the React app or check FRONTEND_DIST path."
        }

