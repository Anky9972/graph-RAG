from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, UploadFile, File, Form, Query
from fastapi import status
from fastapi.responses import StreamingResponse
from typing import List, Dict, Any, Optional

from ...core.neo4j_store import Neo4jStore
from ...retrieval.agent import AgentRetrievalSystem
from ...ingestion.pipeline import IngestionPipeline
from ...config import settings
from ...api.models import *
from ...api.auth import get_current_user, User
import redis
from datetime import datetime, timezone
from ..dependencies import get_graph_store, get_retrieval_agent, get_ingestion_pipeline, get_redis_client

router = APIRouter()


@router.post("/api/query", tags=["Query"])
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

    # P1 Security: Cypher mode exposes freeform graph queries \u2014 restrict to admins.
    # Even with _tenant_safe() heuristics, multi-node patterns can leak cross-tenant data.
    effective_mode = request.mode or ("got" if request.use_got else "auto")
    if effective_mode == "cypher" and "admin" not in getattr(current_user, "scopes", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cypher query mode is restricted to admin users."
        )
    
    # 1. Initialize conversation and user message in Neo4j
    now_str = datetime.now(timezone.utc).isoformat()
    init_query = """
    MATCH (u:User {username: $username})
    MERGE (u)-[:HAS_CONVERSATION]->(c:Conversation {id: $conversation_id})
    ON CREATE SET c.title = $title, c.created_at = $now, c.updated_at = $now
    ON MATCH SET c.updated_at = $now
    CREATE (c)-[:HAS_MESSAGE]->(m:Message {
        id: $msg_id, role: 'user', content: $query, created_at: $now
    })
    """
    await request.app.state.graph_store.execute_query(init_query, {
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
                
        await request.app.state.graph_store.execute_query(save_query, {
            "conversation_id": conversation_id,
            "now": datetime.now(timezone.utc).isoformat(),
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

            async for chunk in request.app.state.retrieval_agent.astream(
                query=request.query,
                top_k=request.top_k,
                document_id=request.document_id,
                mode=request.mode or ("got" if request.use_got else "auto"),
                tenant_id=getattr(current_user, "tenant_id", None),
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
                if settings.enable_llm_judge:
                    yield f"data: {json.dumps({'type': 'step', 'content': 'LLM Judge verifying context grounding...'})}\n\n"
                    try:
                        judge_data = await request.app.state.retrieval_agent.judge.score(
                            query=request.query,
                            answer=final_answer,
                            contexts=final_sources
                        )
                        confidence_update = {
                            "type": "confidence_update",
                            "confidence": judge_data["score"],
                            "hallucination_risk": judge_data["hallucination_risk"],
                            "confidence_reasoning": judge_data["reasoning"],
                        }
                        yield f"data: {json.dumps(confidence_update, default=str)}\n\n"
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"Judge stream error: {e}")

            await save_assistant_message(final_answer, reasoning_steps, final_sources)
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # Non-streaming path
    result = await request.app.state.retrieval_agent.query(
        query=request.query,
        top_k=request.top_k,
        document_id=request.document_id,
        mode=request.mode or ("got" if request.use_got else "auto"),
        tenant_id=current_user.tenant_id,
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


