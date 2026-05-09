from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, UploadFile, File, Form, Query
from typing import List, Dict, Any, Optional

from ...core.neo4j_store import Neo4jStore
from ...retrieval.agent import AgentRetrievalSystem
from ...ingestion.pipeline import IngestionPipeline
from ...config import settings
from ...api.models import RegisterRequest, LoginRequest, TokenResponse
from ...api.auth import get_current_user, User, get_password_hash, verify_password, create_access_token
from fastapi import status
from datetime import timedelta
import redis
from ..dependencies import get_graph_store, get_retrieval_agent, get_ingestion_pipeline, get_redis_client

router = APIRouter()

from ...core.storage import get_storage
storage = get_storage()

@router.post("/api/auth/register", response_model=User, tags=["Authentication"])
async def register(payload: RegisterRequest, request: Request):
    """Register a new user"""
    existing_user = await request.app.state.graph_store.get_user(payload.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    hashed_password = get_password_hash(payload.password)
    # SECURITY: Prevent unauthorized admin registration
    safe_scopes = [s for s in payload.scopes if s != "admin"]
    if not safe_scopes:
        safe_scopes = ["read", "write"]

    user_data = {
        "username": payload.username,
        "hashed_password": hashed_password,
        "email": payload.email,
        "full_name": payload.full_name,
        "disabled": False,
        "scopes": safe_scopes,
        "tenant_id": payload.tenant_id if hasattr(payload, "tenant_id") else settings.default_tenant_id
    }
    
    await request.app.state.graph_store.create_user(user_data)
    
    return User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        disabled=False,
        scopes=safe_scopes,
        tenant_id=user_data["tenant_id"]
    )


@router.post("/api/auth/login", response_model=TokenResponse, tags=["Authentication"])
async def login(payload: LoginRequest, request: Request):
    """
    Login and get access token
    Verifies user against Neo4j database
    """
    user_data = await request.app.state.graph_store.get_user(payload.username)
    if not user_data or not verify_password(payload.password, user_data["hashed_password"]):
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


