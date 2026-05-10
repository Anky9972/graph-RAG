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
from pydantic import BaseModel
from pathlib import Path
import httpx

class SettingsUpdateRequest(BaseModel):
    default_llm_provider: Optional[str] = None
    embedding_provider: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    google_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    ollama_embedding_model: Optional[str] = None
    huggingface_api_key: Optional[str] = None
    huggingface_model: Optional[str] = None
    huggingface_embedding_model: Optional[str] = None

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
    
    tenant_id = current_user.tenant_id
    params = {"tenant_id": tenant_id} if tenant_id else {}
    
    # Count documents
    doc_query = "MATCH (d:Document {tenant_id: $tenant_id}) RETURN count(d) as count" if tenant_id else "MATCH (d:Document) RETURN count(d) as count"
    doc_result = await request.app.state.graph_store.execute_query(doc_query, params)
    documents_count = doc_result[0]["count"] if doc_result else 0
    
    # Count entities
    entity_query = "MATCH (e:Entity {tenant_id: $tenant_id}) RETURN count(e) as count" if tenant_id else "MATCH (e:Entity) RETURN count(e) as count"
    entity_result = await request.app.state.graph_store.execute_query(entity_query, params)
    entities_count = entity_result[0]["count"] if entity_result else 0
    
    # Count relationships
    rel_query = "MATCH ()-[r {tenant_id: $tenant_id}]->() RETURN count(r) as count" if tenant_id else "MATCH ()-[r]->() RETURN count(r) as count"
    rel_result = await request.app.state.graph_store.execute_query(rel_query, params)
    relationships_count = rel_result[0]["count"] if rel_result else 0
    
    # Count chunks
    chunk_query = "MATCH (c:Chunk {tenant_id: $tenant_id}) RETURN count(c) as count" if tenant_id else "MATCH (c:Chunk) RETURN count(c) as count"
    chunk_result = await request.app.state.graph_store.execute_query(chunk_query, params)
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


# ── Settings Endpoint ────────────────────────────────────────────────────────

@router.get("/api/system/settings", tags=["System"])
async def get_settings(current_user: User = Depends(get_current_user)):
    """Get current global settings"""
    return {
        "default_llm_provider": settings.default_llm_provider,
        "embedding_provider": settings.embedding_provider,
        "openai_api_key": settings.openai_api_key,
        "openai_model": settings.openai_model,
        "anthropic_api_key": settings.anthropic_api_key,
        "anthropic_model": settings.anthropic_model,
        "google_api_key": settings.google_api_key,
        "gemini_model": settings.gemini_model,
        "ollama_base_url": settings.ollama_base_url,
        "ollama_model": settings.ollama_model,
        "ollama_embedding_model": settings.ollama_embedding_model,
        "huggingface_api_key": getattr(settings, 'huggingface_api_key', None),
        "huggingface_model": getattr(settings, 'huggingface_model', None),
        "huggingface_embedding_model": getattr(settings, 'huggingface_embedding_model', None),
    }

@router.post("/api/system/settings", tags=["System"])
async def update_settings(update_req: SettingsUpdateRequest, current_user: User = Depends(get_current_user)):
    """Update global settings dynamically and persist to .env"""
    update_data = update_req.model_dump(exclude_unset=True)
    
    # Update in memory
    for key, value in update_data.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
            
    # Persist to .env
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, "r") as f:
            lines = f.readlines()
            
        new_lines = []
        updated_keys = set()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
                
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                if k.lower() in update_data:
                    new_val = update_data[k.lower()]
                    if new_val is not None:
                        new_lines.append(f"{k.upper()}={new_val}\n")
                    else:
                        new_lines.append(f"{k.upper()}=\n")
                    updated_keys.add(k.lower())
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
                
        # Append keys that were not in .env before
        for k, v in update_data.items():
            if k not in updated_keys and v is not None:
                new_lines.append(f"{k.upper()}={v}\n")
                
        with open(env_path, "w") as f:
            f.writelines(new_lines)
    else:
        # If .env does not exist, create it and write all the updated data
        new_lines = []
        for k, v in update_data.items():
            if v is not None:
                new_lines.append(f"{k.upper()}={v}\n")
        with open(env_path, "w") as f:
            f.writelines(new_lines)
            
    return {"message": "Settings updated successfully"}

@router.get("/api/system/ollama/models", tags=["System"])
async def get_ollama_models(base_url: str = Query(..., description="Ollama Base URL")):
    """Fetch available models from an Ollama instance"""
    models = []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/tags", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                models = [m["name"] for m in data.get("models", [])]
    except Exception as e:
        logger.error(f"Failed to fetch Ollama models: {e}")
        
    # Popular cloud models for suggestion
    popular = ["llama3:8b", "llama3.1:8b", "mistral:7b", "gemma:7b", "phi3:mini", "deepseek-coder:6.7b", "nomic-embed-text"]
    for p in popular:
        if p not in models:
            models.append(p)
            
    return {"models": models}

@router.get("/api/system/huggingface/models", tags=["System"])
async def get_hf_models():
    """Fetch trending HuggingFace models"""
    models = [
        "meta-llama/Meta-Llama-3-8B-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.2",
        "google/gemma-7b-it",
        "BAAI/bge-large-en-v1.5",
        "sentence-transformers/all-MiniLM-L6-v2"
    ]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://huggingface.co/api/models?sort=trending&limit=30", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                for m in data:
                    if m.get("id") and m.get("id") not in models:
                        models.append(m["id"])
    except Exception as e:
        logger.error(f"Failed to fetch HuggingFace models: {e}")
        
    return {"models": models}

# ── Graph Export Endpoint ─────────────────────────────────────────────────────


