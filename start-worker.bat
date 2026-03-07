@echo off

REM Start Celery Worker
echo Starting Celery Worker...

REM Check if virtual environment exists
if not exist ".venv" (
    echo Virtual environment not found. Creating...
    uv sync
)

REM Start worker (using solo pool for Windows compatibility)
uv run celery -A src.graph_rag_service.workers.celery_worker worker --loglevel=info --pool=solo
