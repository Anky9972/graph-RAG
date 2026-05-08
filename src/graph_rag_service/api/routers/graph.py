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
        WITH DISTINCT n LIMIT $limit
        OPTIONAL MATCH (n)-[r]->(m:Entity)<-[:MENTIONS]-(:Chunk)<-[:CONTAINS]-(:Document {id: $document_id})
        RETURN 
            collect(DISTINCT {id: coalesce(n.id, toString(id(n))), label: n.name, type: n.type, description: n.description, properties: properties(n)}) as nodes,
            collect(DISTINCT {source: coalesce(n.id, toString(id(n))), target: coalesce(m.id, toString(id(m))), type: type(r)}) as edges
        """
        result = await request.app.state.graph_store.execute_query(query, {"limit": limit, "document_id": document_id})
    else:
        query = """
        MATCH (n:Entity)
        WITH n LIMIT $limit
        OPTIONAL MATCH (n)-[r]->(m:Entity)
        RETURN 
            collect(DISTINCT {id: coalesce(n.id, toString(id(n))), label: n.name, type: n.type, description: n.description, properties: properties(n)}) as nodes,
            collect(DISTINCT {source: coalesce(n.id, toString(id(n))), target: coalesce(m.id, toString(id(m))), type: type(r)}) as edges
        """
        result = await request.app.state.graph_store.execute_query(query, {"limit": limit})

    
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
    current_user: User = Depends(get_current_user)
):
    """
    Detect and assign community IDs to all entities using connected-components (WCC).
    Run this after ingesting new documents to update community clustering.
    """
    count = await request.app.state.graph_store.assign_community_ids()
    return CommunityAssignResponse(
        communities_found=count,
        message=f"Assigned {count} community IDs to entities. Community search is now active."
    )



@router.get("/api/graph/communities", tags=["Graph"])
async def list_communities(request: Request, 
    limit: int = 20,
    current_user: User = Depends(get_current_user)
):
    """List top communities with entity counts"""
    from fastapi.responses import JSONResponse
    query = """
    MATCH (e:Entity)
    WHERE e.community_id IS NOT NULL
    RETURN e.community_id as community_id,
           count(e) as entity_count,
           collect(e.name)[0..5] as sample_entities
    ORDER BY entity_count DESC
    LIMIT $limit
    """
    rows = await request.app.state.graph_store.execute_query(query, {"limit": limit})
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

    doc_filter = "MATCH (:Document {id: $doc_id})-[:CONTAINS]->(:Chunk)-[:MENTIONS]->(e:Entity)" if document_id else "MATCH (e:Entity)"
    params = {"doc_id": document_id} if document_id else {}

    node_query = f"""
    {doc_filter}
    RETURN DISTINCT e.id as id, e.name as name, e.type as type,
           e.community_id as community_id, e.valid_from as valid_from, e.valid_until as valid_until
    LIMIT 2000
    """
    rel_query = """
    MATCH (a:Entity)-[r]->(b:Entity)
    WHERE type(r) NOT IN ['HAS_CONVERSATION', 'HAS_MESSAGE', 'CONTAINS', 'MENTIONS']
    RETURN a.name as source, b.name as target, type(r) as relationship,
           r.valid_from as valid_from, r.confidence as confidence
    LIMIT 5000
    """

    nodes = await request.app.state.graph_store.execute_query(node_query, params)
    rels = await request.app.state.graph_store.execute_query(rel_query)

    if format == "cypher":
        lines = ["// Graph export — Cypher format"]
        for n in nodes:
            escaped = (n.get('name') or '').replace("'", "\\'")
            lines.append(f"MERGE (:Entity {{name: '{escaped}', type: '{n.get('type', '')}'}});")
        for r in rels:
            src = (r.get('source') or '').replace("'", "\\'")
            tgt = (r.get('target') or '').replace("'", "\\'")
            rel = r.get('relationship', 'RELATED_TO')
            lines.append(f"MATCH (a:Entity {{name: '{src}'}}), (b:Entity {{name: '{tgt}'}}) MERGE (a)-[:{rel}]->(b);")
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
    request: GraphUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Merge raw text directly into the live knowledge graph.

    Entities and relationships are extracted via LLM and merged using MERGE
    (idempotent). Call this endpoint whenever new facts become available
    without needing a full document re-ingest cycle.

    Inspired by MiroFish's zep_graph_memory_updater.py.
    """
    updater = GraphMemoryUpdater(
        graph_store=request.app.state.graph_store,
        llm_provider=settings.default_llm_provider,
    )
    result = await updater.update_from_text(
        text=request.text,
        source_label=request.source_label or "api_push",
        valid_from=request.valid_from,
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


