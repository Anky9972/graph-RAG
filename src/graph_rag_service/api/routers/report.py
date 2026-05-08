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

@router.post("/api/report", response_model=ReportResponse, tags=["Report"])
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
    agent = ReportAgent(store=request.app.state.graph_store, llm=llm)
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


