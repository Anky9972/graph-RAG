from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, UploadFile, File, Form, Query, Response
from typing import List, Dict, Any, Optional
from ...workers.celery_worker import celery_app

logger = logging.getLogger(__name__)

from ...core.neo4j_store import Neo4jStore
from ...retrieval.agent import AgentRetrievalSystem
from ...ingestion.pipeline import IngestionPipeline
from ...config import settings
from ...api.models import *
from ...api.auth import get_current_user, User
import redis
from ..dependencies import get_graph_store, get_retrieval_agent, get_ingestion_pipeline, get_redis_client

router = APIRouter()

from ...core.storage import get_storage
storage = get_storage()

@router.get("/api/system/health", response_model=SystemHealthResponse, tags=["System"])
async def health_check(request: Request, response: Response):
    """System health check"""
    
    neo4j_connected = False
    redis_connected = False
    workers_active = 0
    gds_version = None
    
    try:
        # Check Neo4j
        await request.app.state.graph_store.execute_query("RETURN 1")
        neo4j_connected = True
        
        # Check GDS
        try:
            gds_res = await request.app.state.graph_store.execute_query("RETURN gds.version() as version")
            if gds_res:
                gds_version = gds_res[0]["version"]
        except Exception:
            pass
            
    except Exception as e:
        logger.error(f"Neo4j health check failed: {e}")
    
    try:
        # Check Redis
        if hasattr(request.app.state, 'redis_client'):
            await request.app.state.redis_client.ping()
            redis_connected = True
        else:
            redis_connected = True # If redis isn't configured, ignore it
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
    
    try:
        # Check Celery workers
        inspect = celery_app.control.inspect()
        active = inspect.active()
        if active:
            workers_active = len(active)
    except Exception as e:
        logger.warning(f"Celery health check failed: {e}")
    
    overall_status = "healthy" if (neo4j_connected and redis_connected) else "degraded"
    
    if overall_status == "degraded":
        response.status_code = 503
    
    return SystemHealthResponse(
        status=overall_status,
        version=settings.app_version,
        neo4j_connected=neo4j_connected,
        redis_connected=redis_connected,
        workers_active=workers_active,
        gds_version=gds_version,
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
    )



@router.get("/api/system/stats", response_model=SystemStatsResponse, tags=["System"])
async def get_system_stats(request: Request, current_user: User = Depends(get_current_user)):
    """Get system statistics"""
    
    # Count documents
    doc_query = "MATCH (d:Document) RETURN count(d) as count"
    doc_result = await request.app.state.graph_store.execute_query(doc_query)
    documents_count = doc_result[0]["count"] if doc_result else 0
    
    # Count entities
    entity_query = "MATCH (e:Entity) RETURN count(e) as count"
    entity_result = await request.app.state.graph_store.execute_query(entity_query)
    entities_count = entity_result[0]["count"] if entity_result else 0
    
    # Count relationships
    rel_query = "MATCH ()-[r]->() RETURN count(r) as count"
    rel_result = await request.app.state.graph_store.execute_query(rel_query)
    relationships_count = rel_result[0]["count"] if rel_result else 0
    
    # Count chunks
    chunk_query = "MATCH (c:Chunk) RETURN count(c) as count"
    chunk_result = await request.app.state.graph_store.execute_query(chunk_query)
    chunks_count = chunk_result[0]["count"] if chunk_result else 0
    
    ontology = request.app.state.ingestion_pipeline.get_ontology()
    ontology_version = ontology.version if ontology else "none"
    
    return SystemStatsResponse(
        documents_count=documents_count,
        entities_count=entities_count,
        relationships_count=relationships_count,
        chunks_count=chunks_count,
        ontology_version=ontology_version
    )



@router.get("/api/system/my-stats", tags=["System"])
async def get_my_stats(request: Request, current_user: User = Depends(get_current_user)):
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
    RETURN count(m) as message_count, max(m.created_at) as last_active
    """
    try:
        conv_rows = await request.app.state.graph_store.execute_query(conv_q, {"username": username})
        msg_rows = await request.app.state.graph_store.execute_query(msg_q, {"username": username})
        conversation_count = conv_rows[0]["conversation_count"] if conv_rows else 0
        message_count = msg_rows[0]["message_count"] if msg_rows else 0
        last_active = msg_rows[0]["last_active"] if msg_rows else None
        if hasattr(last_active, "isoformat"):
            last_active = last_active.isoformat()
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



@router.get("/api/system/formats", response_model=SupportedFormatsResponse, tags=["System"])
async def get_supported_formats(request: Request):
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


