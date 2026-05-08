from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, UploadFile, File, Form, Query
from typing import List, Dict, Any, Optional

from ...core.neo4j_store import Neo4jStore
from ...retrieval.agent import AgentRetrievalSystem
from ...ingestion.pipeline import IngestionPipeline
from ...config import settings
from ...api.models import *
from ...api.auth import get_current_user, User
import redis

# Dependency injection for global state
def get_graph_store(request: Request) -> Neo4jStore:
    return request.app.state.graph_store

def get_retrieval_agent(request: Request) -> AgentRetrievalSystem:
    return request.app.state.retrieval_agent

def get_ingestion_pipeline(request: Request) -> IngestionPipeline:
    return request.app.state.ingestion_pipeline

def get_redis_client(request: Request) -> redis.Redis:
    return request.app.state.redis_client

router = APIRouter()

from ...core.storage import get_storage
storage = get_storage()

@router.post("/api/auth/register", response_model=User, tags=["Authentication"])
async def register(request: RegisterRequest):
    """Register a new user"""
    existing_user = await request.app.state.graph_store.get_user(request.username)
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
    
    await request.app.state.graph_store.create_user(user_data)
    
    return User(
        username=request.username,
        email=request.email,
        full_name=request.full_name,
        disabled=False,
        scopes=request.scopes
    )


@router.post("/api/auth/login", response_model=TokenResponse, tags=["Authentication"])
async def login(request: LoginRequest):
    """
    Login and get access token
    Verifies user against Neo4j database
    """
    user_data = await request.app.state.graph_store.get_user(request.username)
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



@router.get("/api/auth/me", response_model=User, tags=["Authentication"])
async def get_me(request: Request, current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user


# Document Upload & Ingestion Endpoints


