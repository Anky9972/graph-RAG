from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, UploadFile, File, Form, Query
from typing import List, Dict, Any, Optional

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

@router.get("/api/conversations", response_model=ConversationListResponse, tags=["Memory"])
async def list_conversations(request: Request, current_user: User = Depends(get_current_user)):
    """List all conversation threads for current user"""
    query = """
    MATCH (u:User {username: $username})-[:HAS_CONVERSATION]->(c:Conversation)
    RETURN c.id as id, c.title as title, c.created_at as created_at, c.updated_at as updated_at
    ORDER BY c.updated_at DESC
    """
    results = await request.app.state.graph_store.execute_query(query, {"username": current_user.username})
    
    convs = []
    for r in results:
        convs.append(Conversation(
            id=r["id"],
            title=r["title"],
            created_at=r.get("created_at", datetime.now().isoformat()),
            updated_at=r.get("updated_at", datetime.now().isoformat())
        ))
    return ConversationListResponse(conversations=convs)



@router.get("/api/conversations/{conversation_id}", response_model=Conversation, tags=["Memory"])
async def get_conversation(request: Request, 
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
    results = await request.app.state.graph_store.execute_query(query, {
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



@router.delete("/api/conversations/{conversation_id}", tags=["Memory"])
async def delete_conversation(request: Request, 
    conversation_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete a conversation thread"""
    query = """
    MATCH (u:User {username: $username})-[:HAS_CONVERSATION]->(c:Conversation {id: $conversation_id})
    OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
    DETACH DELETE c, m
    """
    await request.app.state.graph_store.execute_query(query, {
        "username": current_user.username,
        "conversation_id": conversation_id
    })
    return {"status": "deleted", "conversation_id": conversation_id}


# Query Endpoints


