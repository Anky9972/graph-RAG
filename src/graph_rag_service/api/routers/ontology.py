import os
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

@router.get("/api/ontology", response_model=OntologyResponse, tags=["Ontology"])
async def get_ontology(request: Request, current_user: User = Depends(get_current_user)):
    """Get current ontology schema"""
    
    ontology = request.app.state.ingestion_pipeline.get_ontology()
    
    # Fallback: load from Neo4j (ontology is generated in the Celery worker process,
    # not in this server process, so we persist/load it via the graph store)
    if not ontology:
        ontology = await request.app.state.graph_store.load_ontology()
        if ontology:
            request.app.state.ingestion_pipeline.set_ontology(ontology)
    
    if not ontology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ontology available. Ingest documents first to generate ontology."
        )
    
    return OntologyResponse(
        version=ontology.version,
        entity_types=ontology.entity_types,
        relationship_types=ontology.relationship_types,
        properties=ontology.properties,
        created_at=ontology.created_at,
        approved=ontology.approved
    )



@router.get("/api/ontology/stats", tags=["Ontology"])
async def get_ontology_stats(request: Request, 
    document_id: str = None,
    current_user: User = Depends(get_current_user)
):
    """Return entity type counts and relationship type counts, optionally filtered to a document."""
    from fastapi.responses import JSONResponse

    if document_id:
        entity_q = """
        MATCH (:Document {id: $doc_id})-[:CONTAINS]->(:Chunk)-[:MENTIONS]->(e:Entity)
        RETURN e.type as type, count(DISTINCT e) as count
        ORDER BY count DESC
        """
        rel_q = """
        MATCH (:Document {id: $doc_id})-[:CONTAINS]->(:Chunk)-[:MENTIONS]->(a:Entity)
        MATCH (a)-[r]->(b:Entity)<-[:MENTIONS]-(:Chunk)<-[:CONTAINS]-(:Document {id: $doc_id})
        RETURN type(r) as rel_type, count(r) as count
        ORDER BY count DESC
        """
        entity_rows = await request.app.state.graph_store.execute_query(entity_q, {"doc_id": document_id})
        rel_rows = await request.app.state.graph_store.execute_query(rel_q, {"doc_id": document_id})
    else:
        entity_q = """
        MATCH (e:Entity) RETURN e.type as type, count(e) as count ORDER BY count DESC
        """
        rel_q = """
        MATCH ()-[r]->() WHERE type(r) <> 'HAS_CONVERSATION' AND type(r) <> 'HAS_MESSAGE'
        AND type(r) <> 'CONTAINS' AND type(r) <> 'MENTIONS'
        RETURN type(r) as rel_type, count(r) as count ORDER BY count DESC LIMIT 20
        """
        entity_rows = await request.app.state.graph_store.execute_query(entity_q)
        rel_rows = await request.app.state.graph_store.execute_query(rel_q)

    entity_stats = [{"type": r["type"] or "Unknown", "count": r["count"]} for r in entity_rows if r.get("type")]
    rel_stats = [{"type": r["rel_type"] or "Unknown", "count": r["count"]} for r in rel_rows if r.get("rel_type")]

    return JSONResponse({
        "entity_stats": entity_stats,
        "relationship_stats": rel_stats,
        "total_entities": sum(s["count"] for s in entity_stats),
        "total_relationships": sum(s["count"] for s in rel_stats)
    })



@router.post("/api/ontology/refine", response_model=OntologyRefineResponse, tags=["Ontology"])
async def refine_ontology(
    request: OntologyRefineRequest,
    current_user: User = Depends(get_current_user)
):
    """Use LLM to suggest ontology improvements based on current graph data + optional feedback"""

    current_ontology = request.app.state.ingestion_pipeline.get_ontology()
    if not current_ontology:
        current_ontology = await request.app.state.graph_store.load_ontology()
    if not current_ontology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ontology available to refine."
        )

    # Pull a sample of chunk texts from Neo4j to give the LLM context
    if request.document_id:
        sample_query = "MATCH (d:Document {id: $doc_id})-[:CONTAINS]->(c:Chunk) RETURN c.text as text LIMIT 10"
        sample_rows = await request.app.state.graph_store.execute_query(sample_query, {"doc_id": request.document_id})
    else:
        sample_query = "MATCH (c:Chunk) RETURN c.text as text LIMIT 10"
        sample_rows = await request.app.state.graph_store.execute_query(sample_query)

    from ...core.models import Chunk as ChunkModel
    sample_chunks = [
        ChunkModel(text=r["text"] or "", document_id="sample", chunk_index=i)
        for i, r in enumerate(sample_rows) if r.get("text")
    ]

    ontology_gen = OntologyGenerator(llm_provider=settings.default_llm_provider)
    refined = await ontology_gen.refine_ontology(
        current_schema=current_ontology,
        new_chunks=sample_chunks,
        feedback=request.feedback
    )

    # Persist and update in-memory
    await request.app.state.graph_store.save_ontology(refined)
    request.app.state.ingestion_pipeline.set_ontology(refined)

    return OntologyRefineResponse(
        version=refined.version,
        entity_types=refined.entity_types,
        relationship_types=refined.relationship_types,
        properties=refined.properties,
        created_at=refined.created_at,
        approved=refined.approved,
        changes=f"Refined from {current_ontology.version} to {refined.version}"
    )



@router.put("/api/ontology", response_model=OntologyResponse, tags=["Ontology"])
async def update_ontology(
    request: OntologyUpdateRequest,
    current_user: User = Depends(get_current_user)
):
    """Update ontology schema (admin only)"""
    
    current_ontology = request.app.state.ingestion_pipeline.get_ontology()
    
    if not current_ontology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ontology to update"
        )
    
    # Update fields if provided
    if request.entity_types is not None:
        current_ontology.entity_types = request.entity_types
    if request.relationship_types is not None:
        current_ontology.relationship_types = request.relationship_types
    if request.properties is not None:
        current_ontology.properties = request.properties
    if request.approved is not None:
        current_ontology.approved = request.approved
    
    # Updated timestamp
    current_ontology.created_at = datetime.utcnow()
    
    request.app.state.ingestion_pipeline.set_ontology(current_ontology)
    
    return OntologyResponse(
        version=current_ontology.version,
        entity_types=current_ontology.entity_types,
        relationship_types=current_ontology.relationship_types,
        properties=current_ontology.properties,
        created_at=current_ontology.created_at,
        approved=current_ontology.approved
    )


# Graph Visualization Endpoints


@router.post("/api/ontology/drift/detect", response_model=DriftReportResponse, tags=["Ontology"])
async def trigger_drift_detection(request: Request, 
    sample_size: int = 10,
    current_user: User = Depends(get_current_user),
):
    """
    Manually trigger a drift detection cycle.
    Samples random chunks, proposes a new ontology, diffs against current.
    Returns a pending drift report for admin review.
    """
    detector = OntologyDriftDetector(
        graph_store=request.app.state.graph_store,
        llm_provider=settings.default_llm_provider,
    )
    report = await detector.detect_drift(sample_size=sample_size)
    if not report:
        raise HTTPException(
            status_code=404,
            detail="No ontology exists yet. Ingest documents first.",
        )
    return DriftReportResponse(
        id=report.id,
        detected_at=report.detected_at,
        new_entity_types=report.new_entity_types,
        new_relationship_types=report.new_relationship_types,
        removed_entity_types=report.removed_entity_types,
        removed_relationship_types=report.removed_relationship_types,
        sample_size=report.sample_size,
        drift_score=report.drift_score,
        status=report.status,
    )



@router.get("/api/ontology/drift", response_model=DriftListResponse, tags=["Ontology"])
async def list_drift_reports(request: Request, 
    status: Optional[str] = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
):
    """List all drift reports, optionally filtered by status (pending/approved/rejected)."""
    detector = OntologyDriftDetector(graph_store=request.app.state.graph_store)
    reports = await detector.list_drift_reports(status=status, limit=limit)
    report_responses = [
        DriftReportResponse(
            id=r.id,
            detected_at=r.detected_at,
            new_entity_types=r.new_entity_types,
            new_relationship_types=r.new_relationship_types,
            removed_entity_types=r.removed_entity_types,
            removed_relationship_types=r.removed_relationship_types,
            sample_size=r.sample_size,
            drift_score=r.drift_score,
            status=r.status,
            approved_by=r.approved_by,
            approved_at=r.approved_at,
        )
        for r in reports
    ]
    return DriftListResponse(reports=report_responses, total=len(report_responses))



@router.post("/api/ontology/drift/{report_id}/approve", tags=["Ontology"])
async def approve_drift_report(request: Request, 
    report_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Approve a drift report: merge the new entity/relationship types into
    the live ontology and bump the version number.
    """
    detector = OntologyDriftDetector(
        graph_store=request.app.state.graph_store,
        llm_provider=settings.default_llm_provider,
    )
    success = await detector.apply_drift_report(
        report_id=report_id,
        approved_by=current_user.username,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Drift report not found")
    return {"status": "approved", "report_id": report_id}



@router.post("/api/ontology/drift/{report_id}/reject", tags=["Ontology"])
async def reject_drift_report(request: Request, 
    report_id: str,
    current_user: User = Depends(get_current_user),
):
    """Reject a drift report without applying any ontology changes."""
    detector = OntologyDriftDetector(graph_store=request.app.state.graph_store)
    success = await detector.reject_drift_report(report_id)
    if not success:
        raise HTTPException(status_code=404, detail="Drift report not found")
    return {"status": "rejected", "report_id": report_id}


# ── Frontend Static Files Hosting ─────────────────────────────────────────────

FRONTEND_DIST = r"D:\Desktop_March_26\LYZR\graph-RAG\frontend-react\dist"

if False:
    pass
    # Mount frontend static assets if they exist (Vite uses /assets by default)
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.exists(assets_dir) and os.path.isdir(assets_dir):
        # app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    # Catch-all route for SPA routing (except for /api and /docs)
    @router.get("/{full_path:path}", tags=["Frontend SPA"])
    async def serve_frontend(full_path: str):
        # Exclude API and Swagger UI routes from SPA catch-all
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
            raise HTTPException(status_code=404, detail="API route not found")
            
        file_path = os.path.join(FRONTEND_DIST, full_path)
        # Serve literal requested file if it exists (e.g. vite.svg, favicon.ico)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
            
        # Fallback to index.html for client-side routing
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
            
        raise HTTPException(status_code=404, detail="Frontend path not found")
else:
    @router.get("/", tags=["Root"])
    async def root():
        """Root endpoint (fallback when frontend is not built)"""
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "status": "running",
            "docs": "/docs",
            "message": "Frontend build not mounted. Please build the React app or check FRONTEND_DIST path."
        }


