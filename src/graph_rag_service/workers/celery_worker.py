"""
Celery workers for async document ingestion
Decouples ingestion from the API request loop
"""

from celery import Celery
from celery.schedules import crontab
from pathlib import Path
import asyncio

from ..config import settings
from ..ingestion.pipeline import IngestionPipeline
from ..core.storage import get_storage
import tempfile
import io
from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider
from ..ingestion.persona_generator import PersonaGenerator
from .simulation_runner import SimulationManager

# Initialize Celery
celery_app = Celery(
    'graph_rag_workers',
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    task_soft_time_limit=3000,  # 50 minutes soft limit
)

celery_app.conf.beat_schedule = {
    'cleanup-orphan-nodes-daily': {
        'task': 'cleanup_orphan_nodes',
        'schedule': crontab(minute=0, hour=2),  # Run at 2 AM daily
    },
    'enrich-entities-daily': {
        'task': 'enrich_entities',
        'schedule': crontab(minute=30, hour=2),  # 2:30 AM daily (after cleanup)
    },
    'ontology-drift-check-daily': {
        'task': 'check_ontology_drift',
        'schedule': crontab(minute=0, hour=3),  # 3 AM daily
    },
}

def run_async(coro):
    """Helper to run async functions in Celery tasks"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name='ingest_document', bind=True)
def ingest_document_task(self, file_path: str, ontology_dict: dict = None):
    """
    Celery task for document ingestion
    
    Args:
        file_path: Path to document file
        ontology_dict: Optional ontology as dictionary
        
    Returns:
        Extraction result as dictionary
    """
    
    async def _ingest():
        # Initialize pipeline
        graph_store = Neo4jStore()
        pipeline = IngestionPipeline(graph_store=graph_store)
        
        def progress_cb(current, total):
            self.update_state(
                state='PROCESSING', 
                meta={'file': file_path, 'current_chunk': current, 'total_chunks': total}
            )
            
        try:
            await pipeline.initialize()
            
            # Convert ontology dict if provided
            ontology = None
            if ontology_dict:
                from ..core.models import OntologySchema
                ontology = OntologySchema(**ontology_dict)
            
            # Ingest document
            storage = get_storage()
            file_bytes = storage.read_file(file_path)
            
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir) / file_path
                temp_path.write_bytes(file_bytes)
                
                result = await pipeline.ingest_document(
                    temp_path,
                    ontology=ontology,
                    progress_callback=progress_cb
                )
            
            # Convert result to dict
            return {
                "entities_count": len(result.entities),
                "relationships_count": len(result.relationships),
                "chunks_count": len(result.chunks),
                "ontology_version": result.ontology_version,
                "processing_time_seconds": result.processing_time_seconds
            }
        finally:
            await pipeline.close()
    
    # Update task state
    self.update_state(state='PROCESSING', meta={'file': file_path})
    
    try:
        result = run_async(_ingest())
        return result
    except Exception as e:
        # Return error as a plain dict — never raise.
        # Raising any exception (even builtins) can crash the Celery worker
        # when the Redis backend holds a previously corrupt task result.
        error_msg = f"{type(e).__name__}: {e}"
        return {'status': 'error', 'error': error_msg}


@celery_app.task(name='ingest_documents_batch', bind=True)
def ingest_documents_batch_task(self, file_paths: list, ontology_dict: dict = None):
    """
    Celery task for batch document ingestion
    
    Args:
        file_paths: List of document file paths
        ontology_dict: Optional ontology as dictionary
        
    Returns:
        List of extraction results
    """
    
    async def _ingest_batch():
        graph_store = Neo4jStore()
        pipeline = IngestionPipeline(graph_store=graph_store)
        
        try:
            await pipeline.initialize()
            
            ontology = None
            if ontology_dict:
                from ..core.models import OntologySchema
                ontology = OntologySchema(**ontology_dict)
            
            results = await pipeline.ingest_documents(
                [Path(fp) for fp in file_paths],
                ontology=ontology
            )
            
            return [
                {
                    "entities_count": len(r.entities),
                    "relationships_count": len(r.relationships),
                    "chunks_count": len(r.chunks),
                    "ontology_version": r.ontology_version,
                    "processing_time_seconds": r.processing_time_seconds
                }
                for r in results
            ]
        finally:
            await pipeline.close()
    
    self.update_state(state='PROCESSING', meta={'files_count': len(file_paths)})
    
    try:
        results = run_async(_ingest_batch())
        return results
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        return {'status': 'error', 'error': error_msg}


@celery_app.task(name='cleanup_orphan_nodes')
def cleanup_orphan_nodes_task():
    """
    Background job to clean up disconnected or orphaned nodes in Neo4j.
    Scheduled via Celery Beat.
    """
    async def _clean():
        graph_store = Neo4jStore()
        await graph_store.connect()
        try:
            # Delete Entity nodes with 0 relationships
            query = """
            MATCH (n:Entity)
            WHERE COUNT { (n)--() } = 0
            DELETE n
            RETURN count(n) as deleted_count
            """
            result = await graph_store.execute_query(query)
            
            # Delete unlinked Chunks
            chunk_query = """
            MATCH (c:Chunk)
            WHERE NOT (c)<-[:CONTAINS]-(:Document) AND NOT (c)-[:MENTIONS]->(:Entity)
            DELETE c
            RETURN count(c) as deleted_chunks
            """
            chunk_res = await graph_store.execute_query(chunk_query)
            
            return {
                "status": "success", 
                "deleted_entities": result[0]["deleted_count"] if result else 0,
                "deleted_chunks": chunk_res[0]["deleted_chunks"] if chunk_res else 0
            }
        finally:
            await graph_store.disconnect()
            
    return run_async(_clean())


@celery_app.task(name='health_check')
def health_check():
    """Simple health check task"""
    return {"status": "ok", "message": "Worker is healthy"}


@celery_app.task(name='generate_personas')
def generate_personas_task(entity_type='Person'):
    '''Celery task to run the Ontology-to-Persona Pipeline asynchronously.'''
    async def async_run():
        store = Neo4jStore()
        await store.connect()
        llm = UnifiedLLMProvider()
        generator = PersonaGenerator(store, llm)
        count = await generator.generate_personas_for_type(entity_type)
        await store.disconnect()
        return {'status': 'success', 'personas_generated': count}
    return run_async(async_run())

@celery_app.task(name='run_simulation_tick')
def run_simulation_tick_task():
    '''Celery task to run a Multi-Agent Sandbox Simulation Tick (Point 4).'''
    async def async_run():
        store = Neo4jStore()
        await store.connect()
        llm = UnifiedLLMProvider()
        manager = SimulationManager(store, llm)
        actions_taken = await manager.run_simulation_tick()
        await store.disconnect()
        return {'status': 'success', 'actions_taken': actions_taken}
    return run_async(async_run())


@celery_app.task(name='enrich_entities', bind=True)
def enrich_entities_task(self, min_connections: int = 1, overwrite: bool = False):
    """
    Background task to run Entity Enricher: generate LLM profile summaries
    for all well-connected entities and persist them to Neo4j.
    Triggered automatically after ingestion and on daily schedule.
    """
    async def _run():
        from ..services.entity_enricher import EntityEnricher
        store = Neo4jStore()
        await store.connect()
        try:
            enricher = EntityEnricher(graph_store=store)
            result = await enricher.enrich_all_entities(
                min_connections=min_connections,
                overwrite=overwrite,
            )
            return {
                'status': 'success',
                'entities_enriched': result.entities_enriched,
                'entities_skipped': result.entities_skipped,
                'errors': result.errors,
                'duration_seconds': result.duration_seconds,
            }
        finally:
            await store.disconnect()

    try:
        return run_async(_run())
    except Exception as e:
        return {'status': 'error', 'error': f"{type(e).__name__}: {e}"}


@celery_app.task(name='check_ontology_drift', bind=True)
def check_ontology_drift_task(self, sample_size: int = 10):
    """
    Background task to check for ontology drift: re-samples random chunks,
    proposes a new ontology, diffs against current schema.
    Creates a pending DriftReport node in Neo4j for admin review.
    """
    async def _run():
        from ..services.ontology_drift_detector import OntologyDriftDetector
        store = Neo4jStore()
        await store.connect()
        try:
            detector = OntologyDriftDetector(graph_store=store)
            report = await detector.detect_drift(sample_size=sample_size)
            if report:
                return {
                    'status': 'success',
                    'report_id': report.id,
                    'drift_score': report.drift_score,
                    'new_entity_types': report.new_entity_types,
                    'new_relationship_types': report.new_relationship_types,
                }
            return {'status': 'no_ontology', 'message': 'No ontology found — nothing to diff against'}
        finally:
            await store.disconnect()

    try:
        return run_async(_run())
    except Exception as e:
        return {'status': 'error', 'error': f"{type(e).__name__}: {e}"}
