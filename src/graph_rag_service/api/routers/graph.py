from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, UploadFile, File, Form, Query, Body
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

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

@router.get("/api/graph/visualization", response_model=GraphVisualizationResponse, tags=["Graph"])
async def get_graph_visualization(request: Request, 
    limit: int = 50,
    document_id: str = None,
    current_user: User = Depends(get_current_user)
):
    """Get graph data for visualization"""
    
    # Query for nodes and relationships
    if document_id:
        # Collect entity IDs for this document first, then filter edges to stay within that set.
        # We cannot use `d` in a WHERE clause after WITH drops it (Neo4j 5 syntax rule).
        query = """
        MATCH (:Document {id: $document_id})-[:CONTAINS]->(:Chunk)-[:MENTIONS]->(n:Entity)
        WHERE n.tenant_id = $tenant_id
        WITH DISTINCT n LIMIT $limit
        OPTIONAL MATCH (n)-[r]->(m:Entity)<-[:MENTIONS]-(:Chunk)<-[:CONTAINS]-(:Document {id: $document_id})
        WHERE m.tenant_id = $tenant_id
        RETURN 
            collect(DISTINCT {id: coalesce(n.id, toString(id(n))), label: n.name, type: n.type, description: n.description, properties: properties(n)}) as nodes,
            collect(DISTINCT {source: coalesce(n.id, toString(id(n))), target: coalesce(m.id, toString(id(m))), type: type(r)}) as edges
        """
        result = await request.app.state.graph_store.execute_query(query, {"limit": limit, "document_id": document_id, "tenant_id": current_user.tenant_id})
    else:
        query = """
        MATCH (n:Entity)
        WHERE n.tenant_id = $tenant_id
        WITH n LIMIT $limit
        OPTIONAL MATCH (n)-[r]->(m:Entity)
        WHERE m.tenant_id = $tenant_id
        RETURN 
            collect(DISTINCT {id: coalesce(n.id, toString(id(n))), label: n.name, type: n.type, description: n.description, properties: properties(n)}) as nodes,
            collect(DISTINCT {source: coalesce(n.id, toString(id(n))), target: coalesce(m.id, toString(id(m))), type: type(r)}) as edges
        """
        result = await request.app.state.graph_store.execute_query(query, {"limit": limit, "tenant_id": current_user.tenant_id})

    
    if not result:
        return GraphVisualizationResponse(nodes=[], edges=[])
    
    data = result[0]
    
    import json as _json

    def _clean_neo4j_types(val):
        if isinstance(val, dict):
            return {k: _clean_neo4j_types(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_clean_neo4j_types(v) for v in val]
        if isinstance(val, (str, int, float, bool, type(None))):
            return val
        # For Neo4j DateTime/Date objects
        if hasattr(val, "iso_format"):
            return val.iso_format()
        return str(val)

    def _parse_props(raw):
        """Properties are stored as a JSON string in Neo4j or returned as map; coerce back to serializable dict."""
        props = {}
        if isinstance(raw, dict):
            props = raw
        elif isinstance(raw, str):
            try:
                props = _json.loads(raw)
            except Exception:
                pass
        return _clean_neo4j_types(props)

    # Convert to response model
    nodes = [
        GraphNode(
            id=str(n["id"]),
            label=n.get("label", "Unknown"),
            type=n.get("type", "Entity"),
            description=n.get("description"),
            properties=_parse_props(n.get("properties"))
        )
        for n in data.get("nodes", []) if n
    ]
    
    edges = [
        GraphEdge(
            source=str(e["source"]),
            target=str(e["target"]),
            type=e.get("type", "RELATED_TO")
        )
        for e in data.get("edges", []) if e and e.get("target")
    ]
    
    return GraphVisualizationResponse(nodes=nodes, edges=edges)


# System Endpoints


@router.post("/api/graph/communities/assign", response_model=CommunityAssignResponse, tags=["Graph"])
async def assign_communities(request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Detect and assign community IDs using Hierarchical Leiden clustering.
    Run this after ingesting new documents to update community clustering.
    Runs as a background task to prevent API timeouts.
    """
    from ...retrieval.communities import CommunityBuilder
    
    async def build_communities_task():
        try:
            builder = CommunityBuilder(request.app.state.graph_store, request.app.state.retrieval_agent.llm)
            await builder.run_leiden(current_user.tenant_id)
            await builder.create_community_nodes(current_user.tenant_id)
            await builder.generate_all_reports(current_user.tenant_id)
            import logging
            logging.getLogger(__name__).info(f"Community indexing completed for tenant {current_user.tenant_id}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Community indexing failed for tenant {current_user.tenant_id}: {e}")

    background_tasks.add_task(build_communities_task)
    
    return CommunityAssignResponse(
        communities_found=-1, # Unknown at start time
        message="Community indexing started in the background. Reports will be available once complete."
    )



@router.get("/api/graph/communities", tags=["Graph"])
async def list_communities(request: Request, 
    limit: int = 20,
    current_user: User = Depends(get_current_user)
):
    """List top communities with entity counts"""
    from fastapi.responses import JSONResponse
    query = """
    MATCH (c:Community)
    WHERE c.tenant_id = $tenant_id
    OPTIONAL MATCH (e:Entity)-[:IN_COMMUNITY]->(c)
    RETURN c.id as community_id,
           count(e) as entity_count,
           collect(c.title)[0..1] as sample_entities
    ORDER BY entity_count DESC
    LIMIT $limit
    """
    rows = await request.app.state.graph_store.execute_query(query, {"limit": limit, "tenant_id": current_user.tenant_id})
    return JSONResponse({"communities": rows, "total": len(rows)})


# ── Gap #5: Temporal Query Endpoint ───────────────────────────────────────────


@router.get("/api/graph/export", tags=["Graph"])
async def export_graph(request: Request, 
    format: str = "json",
    document_id: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Export the knowledge graph in multiple formats.
    Supported: json, cypher, graphml
    """
    from fastapi.responses import JSONResponse, PlainTextResponse

    doc_filter = "MATCH (:Document {id: $doc_id})-[:CONTAINS]->(:Chunk)-[:MENTIONS]->(e:Entity) WHERE e.tenant_id = $tenant_id" if document_id else "MATCH (e:Entity) WHERE e.tenant_id = $tenant_id"
    params = {"doc_id": document_id, "tenant_id": current_user.tenant_id} if document_id else {"tenant_id": current_user.tenant_id}

    node_query = f"""
    {doc_filter}
    RETURN DISTINCT e.id as id, e.name as name, e.type as type,
           e.community_id as community_id, e.valid_from as valid_from, e.valid_until as valid_until
    LIMIT 2000
    """
    rel_query = """
    MATCH (a:Entity)-[r]->(b:Entity)
    WHERE type(r) NOT IN ['HAS_CONVERSATION', 'HAS_MESSAGE', 'CONTAINS', 'MENTIONS']
      AND a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id
    RETURN a.name as source, b.name as target, type(r) as relationship,
           r.valid_from as valid_from, r.confidence as confidence
    LIMIT 5000
    """

    nodes = await request.app.state.graph_store.execute_query(node_query, params)
    rels = await request.app.state.graph_store.execute_query(rel_query, {"tenant_id": current_user.tenant_id})

    if format == "cypher":
        lines = ["// Graph export — Cypher format"]
        for n in nodes:
            escaped = (n.get('name') or '').replace("'", "\\'")
            lines.append(f"MERGE (:Entity {{name: '{escaped}', type: '{n.get('type', '')}'}});")
        for r in rels:
            src = (r.get('source') or '').replace("'", "\\'")
            tgt = (r.get('target') or '').replace("'", "\\'")
            rel = (r.get('relationship') or 'RELATED_TO').replace("`", "")
            # Ensure the relationship type is safely escaped by wrapping in backticks
            lines.append(f"MATCH (a:Entity {{name: '{src}'}}), (b:Entity {{name: '{tgt}'}}) MERGE (a)-[:`{rel}`]->(b);")
        return PlainTextResponse("\n".join(lines), media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=graph_export.cypher"})

    elif format == "graphml":
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<graphml xmlns="http://graphml.graphdrawing.org/graphml">',
                 '<graph id="G" edgedefault="directed">']
        for n in nodes:
            nid = (n.get('id') or n.get('name') or '').replace('&', '&amp;').replace('<', '&lt;')
            label = (n.get('name') or '').replace('&', '&amp;').replace('<', '&lt;')
            ntype = n.get('type', 'Entity')
            lines.append(f'  <node id="{nid}"><data key="label">{label}</data><data key="type">{ntype}</data></node>')
        for i, r in enumerate(rels):
            src = (r.get('source') or '').replace('&', '&amp;').replace('<', '&lt;')
            tgt = (r.get('target') or '').replace('&', '&amp;').replace('<', '&lt;')
            rel = r.get('relationship', 'RELATED_TO')
            lines.append(f'  <edge id="e{i}" source="{src}" target="{tgt}"><data key="label">{rel}</data></edge>')
        lines.extend(['</graph>', '</graphml>'])
        return PlainTextResponse("\n".join(lines), media_type="application/xml",
            headers={"Content-Disposition": "attachment; filename=graph_export.graphml"})

    # Default: JSON
    return JSONResponse({
        "nodes": nodes,
        "edges": rels,
        "node_count": len(nodes),
        "edge_count": len(rels),
        "export_format": "json"
    })


# ═══════════════════════════════════════════════════════════════════════════
# MiroFish Point 1: Graph Memory Updater Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/api/graph/update", response_model=GraphUpdateResponse, tags=["Graph"])
async def update_graph_from_text(
    payload: GraphUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Merge raw text directly into the live knowledge graph.

    Entities and relationships are extracted via LLM and merged using MERGE
    (idempotent). Call this endpoint whenever new facts become available
    without needing a full document re-ingest cycle.

    Inspired by MiroFish's zep_graph_memory_updater.py.
    """
    from ...services.graph_memory_updater import GraphMemoryUpdater
    updater = GraphMemoryUpdater(
        graph_store=request.app.state.graph_store,
        llm_provider=settings.default_llm_provider,
    )
    result = await updater.update_from_text(
        text=payload.text,
        source_label=payload.source_label or "api_push",
        valid_from=payload.valid_from,
        tenant_id=current_user.tenant_id,
    )
    return GraphUpdateResponse(
        entities_added=result.entities_added,
        relationships_added=result.relationships_added,
        entities_merged=result.entities_merged,
        source_label=result.source_label,
        timestamp=result.timestamp,
        message=result.message,
    )


# ═══════════════════════════════════════════════════════════════════════════
# MiroFish Point 2: Entity Enricher Endpoints
# ═══════════════════════════════════════════════════════════════════════════



@router.delete("/api/graph/purge-tenant", tags=["Graph"])
async def purge_tenant_data(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user)
):
    """
    Delete ALL graph data (nodes + relationships) belonging to a given tenant.

    P1 fix: Users may purge their OWN tenant without admin scope \u2014 this
    enables benchmark cleanup in local dev without seeded admin credentials.
    Admin users can purge any tenant regardless of ownership.
    """
    target_tenant_id = payload.get("tenant_id")
    if not target_tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required.")

    is_admin = "admin" in current_user.scopes
    is_own_tenant = target_tenant_id == current_user.tenant_id

    if not is_admin and not is_own_tenant:
        raise HTTPException(
            status_code=403,
            detail="You may only purge your own tenant. Admin scope is required to purge other tenants."
        )

    # Hard-delete all nodes scoped to this tenant, EXCEPT User nodes
    query = """
    CALL apoc.periodic.iterate(
      'MATCH (n {tenant_id: $tid}) WHERE NOT n:User RETURN n',
      'DETACH DELETE n',
      {batchSize: 500, params: {tid: $tid}}
    )
    YIELD batches, total
    RETURN batches, total
    """
    try:
        result = await request.app.state.graph_store.execute_query(query, {"tid": target_tenant_id})
        deleted = result[0].get("total", 0) if result else 0
    except Exception:
        # Fall back to simple DETACH DELETE if APOC not available
        fallback = "MATCH (n {tenant_id: $tid}) WHERE NOT n:User DETACH DELETE n"
        await request.app.state.graph_store.execute_query(fallback, {"tid": target_tenant_id})
        deleted = -1  # Unknown

    return {"status": "purged", "tenant_id": target_tenant_id, "nodes_deleted": deleted}
