@echo off

REM Start API Server
echo Starting Graph RAG API Server...

REM Check if virtual environment exists
if not exist ".venv" (
    echo Virtual environment not found. Creating...
    uv sync
)

REM Start the server
uv run python main.py
