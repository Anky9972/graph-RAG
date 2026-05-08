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

@router.post("/api/eval/score", response_model=EvalResponse, tags=["Evaluation"])
async def evaluate_response(
    request: EvalRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Run RAGAS-style quality evaluation on a Q&A pair.
    Measures faithfulness, relevancy, and context precision.
    Results are persisted in Neo4j for the quality dashboard.
    """
    from ...retrieval.tools import RAGEvaluator
    from ...core.llm_factory import LLMFactory
    from ...core.models import EvalResult

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
    eval_id = await request.app.state.graph_store.save_eval_result(eval_record)

    return EvalResponse(
        question=request.question,
        faithfulness=metrics["faithfulness"],
        answer_relevancy=metrics["answer_relevancy"],
        context_precision=metrics["context_precision"],
        overall_score=metrics["overall_score"],
        hallucination_detected=metrics["hallucination_detected"],
        eval_id=eval_id
    )



@router.get("/api/eval/dashboard", response_model=EvalDashboardResponse, tags=["Evaluation"])
async def get_eval_dashboard(request: Request, 
    limit: int = 100,
    current_user: User = Depends(get_current_user)
):
    """Retrieve evaluation history for the quality dashboard"""
    rows = await request.app.state.graph_store.get_eval_results(limit=limit)

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


