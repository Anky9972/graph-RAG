from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from celery.result import AsyncResult
from redis import Redis

from .auth import get_current_user, User
from ..config import settings
from ..core.neo4j_store import Neo4jStore
from ..workers.celery_worker import celery_app

router = APIRouter(prefix="/api/admin", tags=["Admin Dashboard"])

# ── Shared graph store dependency ─────────────────────────────────────────────
# Admin routes must NOT create a fresh Neo4j driver per request — that causes
# connection exhaustion and 50-200 ms of TCP handshake latency on every call.
# Instead we pull the shared store that was initialised in the startup event.
def get_graph_store(request: Request) -> Neo4jStore:
    """Return the app-level shared Neo4jStore (set during startup)."""
    store: Optional[Neo4jStore] = getattr(request.app.state, "graph_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph store not initialised yet.",
        )
    return store


# Re-use global objects by passing them explicitly if needed, 
# for now we'll import and instantiate lightweight ones or use dependencies
def check_admin_scope(user: User = Depends(get_current_user)):
    """Dependency to check if user has admin scope"""
    # Temporarily allowing loosely if scopes claim includes admin, or if we want to bypass for dev
    if "admin" not in user.scopes and user.username != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required - Not enough permissions"
        )
    return user

class SystemConfig(BaseModel):
    llm_provider: str
    embedding_provider: str
    chunk_size: int
    workers_online: int

class TaskDashboardResponse(BaseModel):
    active_tasks: int
    pending_tasks: List[Dict[str, Any]]
    failed_tasks: List[Dict[str, Any]]

@router.get("/stats", summary="Get global admin statistics")
async def get_admin_stats(
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store),
):
    """Get system-wide stats like document counts, node sizes, LLM costs (mocked for now)"""
    try:
        # Get actual counts from Graph
        nodes_q = "MATCH (n) RETURN count(n) as count"
        nodes_res = await store.execute_query(nodes_q)
        nodes_count = nodes_res[0]["count"] if nodes_res else 0
        
        edges_q = "MATCH ()-[r]->() RETURN count(r) as count"
        edges_res = await store.execute_query(edges_q)
        edges_count = edges_res[0]["count"] if edges_res else 0

        # LLM costs mock for MVP dashboard
        estimated_cost_usd = 2.45
        
        return {
            "graph": {
                "nodes": nodes_count,
                "relationships": edges_count
            },
            "costs": {
                "total_estimated_usd": estimated_cost_usd,
                "tokens_processed": 145000
            },
            "system": {
                "provider": settings.default_llm_provider,
                "environment": settings.environment
            }
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/tasks", summary="Get pending and active celery tasks")
async def get_tasks(admin_user: User = Depends(check_admin_scope)):
    """Fetch all tasks from workers (integration with Flower/Celery events)"""
    # For a direct Celery API pull we use the celery inspector
    i = celery_app.control.inspect()
    active = i.active() or {}
    reserved = i.reserved() or {}
    
    active_list = []
    for worker, tasks in active.items():
        active_list.extend([{"worker": worker, "id": t["id"], "name": t["name"]} for t in tasks])
        
    reserved_list = []
    for worker, tasks in reserved.items():
        reserved_list.extend([{"worker": worker, "id": t["id"], "name": t["name"]} for t in tasks])

    return TaskDashboardResponse(
        active_tasks=len(active_list),
        pending_tasks=reserved_list,
        failed_tasks=[] # Needs Redis result backend history query for real failures
    )

@router.post("/config", summary="Update system LLM configuration live")
async def update_config(config: SystemConfig, admin_user: User = Depends(check_admin_scope)):
    """Dynamically update configurations - requires restart logic usually, but here we mock DB save"""
    # In a full app, this would save to a Redis key or PG DB that the app reads from.
    settings.default_llm_provider = config.llm_provider
    return {"status": "success", "message": f"Updated config to use {config.llm_provider}"}

@router.get("/entities/review", summary="Get entities flagged for human review")
async def get_review_queue(
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store),
):
    """Fetch entities that resolved between 0.85-0.95 confidence"""
    # Mocking finding entities with a specific flag
    # You'd typically add a label :FlaggedForReview during ingestion
    query = "MATCH (e:Entity) WHERE e.needs_review = true RETURN e.id as id, e.name as name LIMIT 50"
    res = await store.execute_query(query)
    return {"queue": res}

@router.post("/entities/merge", summary="Force merge two entities")
async def force_merge_entities(
    source_id: str,
    target_id: str,
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store),
):
    """Admin override to merge two nodes"""
    try:
        query = '''
        MATCH (source:Entity {id: $source_id})
        MATCH (target:Entity {id: $target_id})
        CALL apoc.refactor.mergeNodes([target, source], {properties:"combine", mergeRels:true})
        YIELD node
        RETURN node.id as id
        '''
        res = await store.execute_query(query, {"source_id": source_id, "target_id": target_id})
        return {"status": "merged", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- NEW GRAPH CRUD ENDPOINTS ---

@router.get("/graph/nodes", summary="Search graph nodes for CRUD")
async def search_nodes(
    query: str = "",
    limit: int = 50,
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store),
):
    if query:
        cypher = """
        MATCH (n) 
        WHERE any(prop in keys(n) WHERE toString(n[prop]) CONTAINS $query) OR head(labels(n)) CONTAINS $query
        RETURN id(n) as id, labels(n) as labels, properties(n) as properties LIMIT $limit
        """
    else:
        cypher = "MATCH (n) RETURN id(n) as id, labels(n) as labels, properties(n) as properties LIMIT $limit"
    
    res = await store.execute_query(cypher, {"query": query, "limit": limit})
    return {"nodes": res}

@router.delete("/graph/nodes/{node_id}", summary="Delete a node and its edges")
async def delete_node(
    node_id: int,
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store),
):
    # SECURITY: only allow deletion of content nodes — never User/system/OntologyMeta nodes.
    _DELETABLE_LABELS = {"Entity", "Chunk", "Document", "OntologyProposal", "Community"}
    # First fetch the node labels
    label_q = "MATCH (n) WHERE id(n) = $node_id RETURN labels(n) as labels"
    label_res = await store.execute_query(label_q, {"node_id": node_id})
    if not label_res:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found.")
    node_labels = set(label_res[0].get("labels", []))
    if not node_labels.intersection(_DELETABLE_LABELS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Deletion of node with labels {node_labels} is not permitted.",
        )
    cypher = "MATCH (n) WHERE id(n) = $node_id DETACH DELETE n"
    await store.execute_query(cypher, {"node_id": node_id})
    return {"status": "success", "message": f"Node {node_id} deleted."}

# --- NEW DOCUMENT VAULT ENDPOINTS ---

@router.get("/documents", summary="List all ingested documents")
async def list_documents(
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store),
):
    cypher = "MATCH (d:Document) RETURN d.id as id, d.filename as filename, d.status as status, d.uploaded_at as uploaded_at"
    res = await store.execute_query(cypher)
    return {"documents": res}

@router.delete("/documents/{doc_id}", summary="Delete document and cascade graph chunks")
async def delete_document(
    doc_id: str,
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store),
):
    # Cascade delete logic in Neo4j
    cypher = """
    MATCH (d:Document {id: $doc_id})
    OPTIONAL MATCH (d)-[:CONTAINS]->(c:Chunk)
    DETACH DELETE c, d
    """
    await store.execute_query(cypher, {"doc_id": doc_id})
    return {"status": "success", "message": f"Document {doc_id} and components deleted."}

# --- NEW ONTOLOGY GOVERNANCE ENDPOINTS ---

@router.get("/ontology/pending", summary="List pending ontology suggestions")
async def get_pending_ontology(
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store),
):
    # Mock finding pending ontology nodes
    cypher = "MATCH (o:OntologyProposal) WHERE o.status = 'pending' RETURN o.id as id, o.type as type, o.name as name"
    res = await store.execute_query(cypher)
    # return dummy if empty for demo
    if not res:
        res = [
            {"id": "prop1", "type": "Entity", "name": "ArtificialIntelligenceModel"},
            {"id": "prop2", "type": "Relationship", "name": "OPTIMIZES_PERFORMANCE"}
        ]
    return {"proposals": res}

@router.post("/ontology/approve/{prop_id}", summary="Approve ontology type")
async def approve_ontology(
    prop_id: str, 
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store)
):
    cypher = "MATCH (o:OntologyProposal {id: $prop_id}) SET o.status = 'approved' RETURN o"
    await store.execute_query(cypher, {"prop_id": prop_id})
    return {"status": "approved", "id": prop_id}

@router.post("/ontology/reject/{prop_id}", summary="Reject ontology type")
async def reject_ontology(
    prop_id: str, 
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store)
):
    cypher = "MATCH (o:OntologyProposal {id: $prop_id}) SET o.status = 'rejected' RETURN o"
    await store.execute_query(cypher, {"prop_id": prop_id})
    return {"status": "rejected", "id": prop_id}

# --- NEW USER MANAGEMENT ENDPOINTS ---

@router.get("/users", summary="List all system users")
async def list_users(
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store),
):
    cypher = "MATCH (u:User) RETURN u.username as username, u.scopes as scopes, u.disabled as disabled"
    res = await store.execute_query(cypher)
    # Mock fallback if user node isn't implemented exactly this way
    if not res:
        res = [
            {"username": "admin", "scopes": ["read", "write", "admin"], "disabled": False},
            {"username": "analyst1", "scopes": ["read", "write"], "disabled": False},
            {"username": "guest", "scopes": ["read"], "disabled": False}
        ]
    return {"users": res}

@router.put("/users/{username}/role", summary="Update user role/scopes")
async def update_user_role(
    username: str, 
    payload: dict, 
    admin_user: User = Depends(check_admin_scope),
    store: Neo4jStore = Depends(get_graph_store)
):
    scopes = payload.get("scopes", [])
    cypher = "MATCH (u:User {username: $username}) SET u.scopes = $scopes RETURN u"
    await store.execute_query(cypher, {"username": username, "scopes": scopes})
    return {"status": "success", "username": username, "new_scopes": scopes}

