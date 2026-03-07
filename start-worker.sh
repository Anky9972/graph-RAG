#!/bin/bash

# Start Celery Worker
echo "Starting Celery Worker..."

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Creating..."
    uv sync
fi

# Start worker
uv run celery -A src.graph_rag_service.workers.celery_worker worker --loglevel=info --concurrency=4
