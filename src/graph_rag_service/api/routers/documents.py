from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, UploadFile, File, Form, Query
from fastapi import status
from pathlib import Path
from typing import List, Dict, Any, Optional

from ...core.neo4j_store import Neo4jStore
from ...retrieval.agent import AgentRetrievalSystem
from ...ingestion.pipeline import IngestionPipeline
from ...config import settings
from ...api.models import *
from ...api.auth import get_current_user, User
from ...workers.celery_worker import ingest_document_task, celery_app
from celery.result import AsyncResult
import redis
from ..dependencies import get_graph_store, get_retrieval_agent, get_ingestion_pipeline, get_redis_client

router = APIRouter()

from ...core.storage import get_storage
storage = get_storage()

@router.post("/api/documents/upload", response_model=DocumentUploadResponse, tags=["Documents"])
async def upload_document(request: Request, 
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """
    Upload document for ingestion
    Returns task ID for tracking ingestion progress
    """
    
    # Validate file type
    file_extension = Path(file.filename).suffix.lower()
    if file_extension not in settings.allowed_file_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file_extension} not allowed. Allowed types: {settings.allowed_file_types}"
        )

    # Validate MIME type using python-magic
    import magic
    file_header = await file.read(2048)
    await file.seek(0)
    mime_type = magic.from_buffer(file_header, mime=True)
    
    # Basic mapping of extension to MIME types for allowed_file_types
    allowed_mimes = {
        ".pdf": ["application/pdf"],
        ".txt": ["text/plain"],
        ".md": ["text/plain", "text/markdown"],
        ".csv": ["text/csv", "text/plain"],
        ".xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
        ".pptx": ["application/vnd.openxmlformats-officedocument.presentationml.presentation"]
    }
    
    if file_extension in allowed_mimes and mime_type not in allowed_mimes[file_extension]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File content ({mime_type}) does not match extension {file_extension}"
        )

    # SECURITY: sanitize filename to prevent path traversal (e.g. "../../../etc/passwd")
    import re as _re
    safe_stem = _re.sub(r"[^\w\-]", "_", Path(file.filename).stem)[:100]
    safe_name = f"{safe_stem}{file_extension}"
    file_path = settings.upload_dir / safe_name
    # Ensure the resolved path is still inside upload_dir
    try:
        file_path.resolve().relative_to(settings.upload_dir.resolve())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )

    import aiofiles
    async with aiofiles.open(file_path, "wb") as buffer:
        while chunk := await file.read(8192):
            await buffer.write(chunk)
    
    file_size = file_path.stat().st_size
    import hashlib
    hasher = hashlib.sha256()
    hasher.update(str(file_path).encode())
    hasher.update(str(file_path.stat().st_mtime).encode())
    doc_id = hasher.hexdigest()[:16]
    
    # Validate file size
    if file_size > settings.max_upload_size_mb * 1024 * 1024:
        file_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {settings.max_upload_size_mb}MB"
        )
    
    # Queue ingestion task
    task = ingest_document_task.delay(
        str(file_path),
        ontology_dict=None,
        tenant_id=current_user.tenant_id
    )
    
    return DocumentUploadResponse(
        document_id=doc_id,
        filename=file.filename,
        size_bytes=file_size,
        task_id=task.id,
        message="Document uploaded successfully. Ingestion in progress."
    )



@router.post("/api/documents/scrape", response_model=DocumentUploadResponse, tags=["Documents"])
async def scrape_url(
    request: ScrapeRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Scrape URL content into text and ingest it.
    """
    import httpx
    from bs4 import BeautifulSoup
    import markdownify
    import re
    from ...ingestion.web_crawler import WebCrawler

    try:
        import sys
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')

        # We will attempt to use the powerful AsyncWebCrawler which runs Playwright headless and naturally bypasses 403 blocks.
        crawler = WebCrawler(max_depth=0, max_pages=1)
        results = await crawler.crawl(request.url)
        
        if not results or not results[0].get("markdown"):
            raise ValueError("No content was returned by the crawler.")
            
        text = results[0]["markdown"]
        title = results[0].get("title", "scraped_page")
        if not title:
            title = "scraped_page"
            
        safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', title)
        filename = f"{safe_title}.md"
        
        # Save to disk
        file_path = settings.upload_dir / filename
        
        import aiofiles
        async with aiofiles.open(file_path, "w", encoding="utf-8") as buffer:
            await buffer.write(text)
            
        file_size = file_path.stat().st_size
        import hashlib
        hasher = hashlib.sha256()
        hasher.update(str(file_path).encode())
        hasher.update(str(file_path.stat().st_mtime).encode())
        doc_id = hasher.hexdigest()[:16]
        
        # Queue ingestion
        task = ingest_document_task.delay(
            str(file_path),
            ontology_dict=None,
            tenant_id=current_user.tenant_id
        )
        
        return DocumentUploadResponse(
            document_id=doc_id,
            filename=filename,
            size_bytes=file_size,
            task_id=task.id,
            message="URL scraped and ingestion initiated successfully."
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scrape URL: {str(e)}"
        )



@router.post("/api/documents/crawl", tags=["Documents"])
async def crawl_urls(
    request: CrawlRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Advanced async Web Crawling using locally-hosted Crawl4AI (Playwright).
    This extracts clean Markdown format and queues items into Celery for Graph ingestion.
    """
    from ...ingestion.web_crawler import WebCrawler
    import re
    import hashlib
    
    crawler = WebCrawler(max_depth=request.max_depth, max_pages=request.max_pages)
    
    async def run_crawl_and_ingest():
        try:
            results = await crawler.crawl(request.url)
            for page in results:
                if not page.get("markdown"):
                    continue
                    
                # Create a safe filename
                safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', page.get("title", "page_") or "page_")
                url_hash = hashlib.md5(page['url'].encode()).hexdigest()[:6]
                filename = f"crawled_{safe_title}_{url_hash}.txt"
                
                file_content = f"# Source Metadata\n- URL: {page['url']}\n- Title: {page['title']}\n\n"
                file_content += page["markdown"]
                
                storage.save_file(filename, file_content.encode("utf-8"))
                    
                # Queue parsing
                ingest_document_task.delay(filename, ontology_dict=None)
                
        except Exception as e:
            import logging
            logging.error(f"Crawling pipeline failed for {request.url}: {e}")
            
    background_tasks.add_task(run_crawl_and_ingest)
    
    return {
        "message": f"Crawler started asynchronously for {request.url} (up to {request.max_pages} pages)",
        "status": "processing"
    }



@router.get("/api/documents", response_model=DocumentListResponse, tags=["Documents"])
async def list_documents(request: Request, current_user: User = Depends(get_current_user)):
    """List all ingested documents for the current tenant"""
    tenant_id = current_user.tenant_id
    if tenant_id:
        query = """
        MATCH (d:Document {tenant_id: $tenant_id})
        RETURN d.id as id, d.filename as filename, d.file_type as file_type,
               d.size_bytes as size_bytes, toString(d.upload_date) as upload_date
        ORDER BY d.upload_date DESC
        """
        results = await request.app.state.graph_store.execute_query(query, {"tenant_id": tenant_id})
    else:
        query = """
        MATCH (d:Document)
        RETURN d.id as id, d.filename as filename, d.file_type as file_type,
               d.size_bytes as size_bytes, toString(d.upload_date) as upload_date
        ORDER BY d.upload_date DESC
        """
        results = await request.app.state.graph_store.execute_query(query)
    docs = [
        DocumentInfo(
            id=r["id"] or "",
            filename=r["filename"] or "",
            file_type=r["file_type"] or "",
            size_bytes=r["size_bytes"] or 0,
            upload_date=str(r["upload_date"] or "")[:19]
        )
        for r in results
    ]
    return DocumentListResponse(documents=docs, total=len(docs))



@router.delete("/api/documents/{document_id}", tags=["Documents"])
async def delete_document(request: Request, 
    document_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete a document and all its chunks and entity links from the graph.
    
    P0 security fix: enforces tenant_id ownership — a user can only delete
    documents that belong to their own tenant.
    """
    tenant_id = current_user.tenant_id

    # Verify ownership: fetch filename only if tenant matches
    query = """
    MATCH (d:Document {id: $doc_id, tenant_id: $tenant_id})
    RETURN d.filename as filename
    """
    results = await request.app.state.graph_store.execute_query(
        query, {"doc_id": document_id, "tenant_id": tenant_id}
    )
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied."
        )
    filename_to_delete = results[0].get("filename")

    delete_query = """
    MATCH (d:Document {id: $doc_id, tenant_id: $tenant_id})
    OPTIONAL MATCH (d)-[:CONTAINS]->(c:Chunk)
    DETACH DELETE c, d
    """
    await request.app.state.graph_store.execute_query(
        delete_query, {"doc_id": document_id, "tenant_id": tenant_id}
    )

    # Remove uploaded file from storage
    if filename_to_delete:
        try:
            storage.delete_file(filename_to_delete)
        except Exception:
            pass

    return {"status": "deleted", "document_id": document_id}


@router.get("/api/documents/{document_id}/download", tags=["Documents"])
async def download_document(request: Request, 
    document_id: str,
    current_user: User = Depends(get_current_user)
):
    """Download an uploaded document.
    
    P0 security fix: enforces tenant_id ownership so only the owning tenant
    can download the file.
    """
    from fastapi.responses import FileResponse
    tenant_id = current_user.tenant_id
    
    # 1. Verify ownership and fetch filename in a single tenant-scoped query
    query = """
    MATCH (d:Document {id: $doc_id, tenant_id: $tenant_id})
    RETURN d.filename as filename
    """
    results = await request.app.state.graph_store.execute_query(
        query, {"doc_id": document_id, "tenant_id": tenant_id}
    )
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied."
        )
    filename_target = results[0].get("filename")
    
    if filename_target:
        possible_path = settings.upload_dir / filename_target
        if possible_path.exists():
            return FileResponse(
                path=possible_path,
                filename=filename_target,
                content_disposition_type="inline"
            )
            
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Document file '{filename_target}' not found on disk"
    )




@router.get("/api/documents/{document_id}/preview", tags=["Documents"])
async def preview_document(request: Request, 
    document_id: str,
    current_user: User = Depends(get_current_user)
):
    """Return raw text content of a document for in-app preview (works for .txt, .md scraped files).
    
    P0 security fix: enforces tenant_id ownership — cross-tenant document
    IDs are rejected with 404.
    """
    from fastapi.responses import JSONResponse
    tenant_id = current_user.tenant_id

    query = """
    MATCH (d:Document {id: $doc_id, tenant_id: $tenant_id})
    RETURN d.filename as filename, d.file_type as file_type
    """
    results = await request.app.state.graph_store.execute_query(
        query, {"doc_id": document_id, "tenant_id": tenant_id}
    )

    if not results or not results[0].get("filename"):
        raise HTTPException(status_code=404, detail="Document not found in graph")

    filename = results[0]["filename"]
    file_type = results[0]["file_type"] or ""
    file_path = settings.upload_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found on disk")

    if file_type.lower() not in (".txt", ".md", ""):
        raise HTTPException(status_code=415, detail="Preview only supported for text files. Use download for PDFs.")

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        word_count = len(content.split())
        char_count = len(content)
        return JSONResponse({
            "filename": filename,
            "file_type": file_type,
            "word_count": word_count,
            "char_count": char_count,
            "content": content
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")



@router.get("/api/documents/status/{task_id}", response_model=IngestionStatusResponse, tags=["Documents"])
async def get_ingestion_status(request: Request, 
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get ingestion task status"""
    
    task = AsyncResult(task_id, app=celery_app)
    
    if task.state == 'PENDING':
        response = {
            "task_id": task_id,
            "status": "pending",
            "progress": None,
            "result": None
        }
    elif task.state == 'PROCESSING':
        response = {
            "task_id": task_id,
            "status": "processing",
            "progress": task.info,
            "result": None
        }
    elif task.state == 'SUCCESS':
        response = {
            "task_id": task_id,
            "status": "completed",
            "progress": None,
            "result": task.info
        }
    else:
        response = {
            "task_id": task_id,
            "status": task.state.lower(),
            "progress": None,
            "result": str(task.info) if task.info else None
        }
    
    return IngestionStatusResponse(**response)


# Conversations / Memory Endpoints


