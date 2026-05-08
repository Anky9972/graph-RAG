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

@router.post("/api/entities/deduplicate", response_model=DeduplicateResponse, tags=["Entities"])
async def deduplicate_entities(request: Request, 
    current_user: User = Depends(get_current_user)
):
    """Run semantic entity resolution and merge duplicates (admin only)"""
    # Load all entities from Neo4j
    entity_query = """
    MATCH (e:Entity)
    RETURN e.id as id, e.name as name, e.type as type
    """
    rows = await request.app.state.graph_store.execute_query(entity_query)

    from ...core.models import Entity as EntityModel
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
                    await request.app.state.graph_store.merge_entities(canonical_id, dupe.id)
                    merged_count += 1
                except Exception:
                    pass

    return DeduplicateResponse(merged_count=merged_count, groups=groups_out)



@router.get("/api/entities/{entity_name}/at-time", tags=["Entities"])
async def get_entity_at_time(request: Request, 
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

    results = await request.app.state.graph_store.get_entities_at_time(entity_name=entity_name, at_time=time_obj)
    return JSONResponse({"entity": entity_name, "at_time": at_time, "relationships": results})


# ── Gap #9: Supported Formats ─────────────────────────────────────────────────


@router.post("/api/entities/enrich", response_model=EnrichmentStatusResponse, tags=["Entities"])
async def trigger_entity_enrichment(request: Request, 
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
        graph_store=request.app.state.graph_store,
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



@router.get("/api/entities/{entity_name}/summary", response_model=EntitySummaryResponse, tags=["Entities"])
async def get_entity_summary(request: Request, 
    entity_name: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get the enriched profile summary for a specific entity.
    Returns the LLM-synthesized description stored on the graph node.
    """
    enricher = EntityEnricher(graph_store=request.app.state.graph_store)
    summary = await enricher.get_entity_summary(entity_name)

    # Also fetch entity type
    rows = await request.app.state.graph_store.execute_query(
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


@router.post("/api/entities/{entity_name}/chat", response_model=EntityChatResponse, tags=["Entities"])
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
    neighbors = await request.app.state.graph_store.get_neighbors(entity_name, depth=2)

    # Fetch entity summary + direct relationships
    entity_rows = await request.app.state.graph_store.execute_query(
        "MATCH (e:Entity {name: $name}) RETURN e.type as type, e.summary as summary",
        {"name": entity_name},
    )
    entity_type = entity_rows[0].get("type", "Entity") if entity_rows else "Entity"
    entity_summary = entity_rows[0].get("summary") if entity_rows else None

    rel_rows = await request.app.state.graph_store.execute_query(
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
        history_rows = await request.app.state.graph_store.execute_query(
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


