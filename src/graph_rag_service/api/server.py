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
from .auth import (
    get_current_user,
    create_access_token,
    verify_password,
    get_password_hash,
    User,
    check_scope
)

from ..config import settings
from ..core.neo4j_store import Neo4jStore
from ..retrieval.agent import AgentRetrievalSystem
from ..ingestion.pipeline import IngestionPipeline
from ..core.storage import get_storage
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
# SECURITY: allow_origins=["*"] and allow_credentials=True cannot be used together
# (browsers reject credentialed cross-origin requests to wildcard origins).
# Allowed origins are driven by the CORS_ORIGINS env var (comma-separated list).
# Defaults to localhost only. Set appropriately for production.
_raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
import re
def is_valid_origin(origin: str) -> bool:
    if origin == "*": return True
    # Basic URL validation regex for CORS origins (scheme://host[:port])
    pattern = re.compile(r"^https?://[a-zA-Z0-9.-]+(:\d+)?$")
    return bool(pattern.match(origin))

_allowed_origins: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip() and is_valid_origin(o.strip())]
if not _allowed_origins:
    _allowed_origins = ["http://localhost:3000"]
_is_wildcard = "*" in _allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    # credentials (cookies / Authorization headers) must be False when using wildcard
    allow_credentials=not _is_wildcard,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
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
    if settings.environment == "production" and settings.secret_key == "change-this-in-production-to-a-secure-random-key":
        raise RuntimeError("CRITICAL: You must change SECRET_KEY in production to a secure random key.")

    global graph_store, retrieval_agent, ingestion_pipeline, redis_client
    
    # Initialize Neo4j
    graph_store = Neo4jStore()
    await graph_store.connect()
    # Expose on app.state so admin dependency injection can reach it
    app.state.graph_store = graph_store
    
    # Initialize retrieval agent
    retrieval_agent = AgentRetrievalSystem(
        graph_store=graph_store,
        llm_provider=settings.default_llm_provider
    )
    app.state.retrieval_agent = retrieval_agent
    
    # Initialize ingestion pipeline
    ingestion_pipeline = IngestionPipeline(
        graph_store=graph_store,
        llm_provider=settings.default_llm_provider
    )
    await ingestion_pipeline.initialize()
    app.state.ingestion_pipeline = ingestion_pipeline
    
    # Initialize Redis
    redis_client = redis.from_url(settings.redis_url)
    app.state.redis_client = redis_client
    


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


# Routers
from .routers import evaluation
app.include_router(evaluation.router)
from .routers import query
app.include_router(query.router)
from .routers import documents
app.include_router(documents.router)
from .routers import entities
app.include_router(entities.router)
from .routers import auth
app.include_router(auth.router)
from .routers import report
app.include_router(report.router)
from .routers import memory
app.include_router(memory.router)
from .routers import ontology
app.include_router(ontology.router)
from .routers import graph
app.include_router(graph.router)
from .routers import system
app.include_router(system.router)

import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Serve React frontend if built (for Hugging Face Spaces / Demo Mode)
frontend_path = os.path.join(os.path.dirname(__file__), "../../../../frontend-react/dist")
if os.path.isdir(frontend_path):
    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(frontend_path, "index.html"))
        
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
