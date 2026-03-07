"""
Celery workers for async document ingestion
Decouples ingestion from the API request loop
"""

from celery import Celery
from pathlib import Path
import asyncio

from ..config import settings
from ..ingestion.pipeline import IngestionPipeline
from ..core.neo4j_store import Neo4jStore

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
        
        try:
            await pipeline.initialize()
            
            # Convert ontology dict if provided
            ontology = None
            if ontology_dict:
                from ..core.models import OntologySchema
                ontology = OntologySchema(**ontology_dict)
            
            # Ingest document
            result = await pipeline.ingest_document(
                Path(file_path),
                ontology=ontology
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


@celery_app.task(name='health_check')
def health_check():
    """Simple health check task"""
    return {"status": "ok", "message": "Worker is healthy"}
