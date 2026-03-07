#!/bin/bash

# Start API Server
echo "Starting Graph RAG API Server..."

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Creating..."
    uv sync
fi

# Start the server
uv run python main.py
