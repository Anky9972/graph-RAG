# Quick Start Guide

Get the Graph RAG Service up and running in 10 minutes!

## Prerequisites

Before starting, make sure you have:
- Python 3.12 or higher
- Neo4j database (running locally or remotely)
- Redis server (running locally or remotely)
- UV package manager (will be installed if missing)

## Step 1: Clone and Setup

```bash
cd graph-RAG

# Install UV if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync
```

## Step 2: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings
# Configure NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
# Configure REDIS_URL
```

## Step 3: Ensure Backend Services Are Running

Make sure Neo4j and Redis are running and accessible:
- Neo4j should be available at the URI specified in your .env file (default: bolt://localhost:7687)
- Redis should be available at the URL specified in your .env file (default: redis://localhost:6379)

## Step 4: Start the API Server

### On Windows:
```bash
start-server.bat
```

### On Mac/Linux:
```bash
chmod +x start-server.sh
./start-server.sh
```

### Or directly (any OS):
```bash
uv run python main.py
```

The API server will start on `http://localhost:8000`

## Step 5: Start Celery Worker

For asynchronous document ingestion, start a worker in a **new terminal**:

### On Windows:
```bash
start-worker.bat
```

### On Mac/Linux:
```bash
chmod +x start-worker.sh
./start-worker.sh
```

### Or directly:
```bash
uv run celery -A src.graph_rag_service.workers.celery_worker worker --loglevel=info
```

## Step 6: Start the Streamlit Frontend

In a **new terminal**:

```bash
cd frontend
uv run streamlit run app.py
```

The Streamlit UI will open at `http://localhost:8501`

Login with: **username** `admin` / **password** `admin`

## Step 7: Test the API

### Using cURL

1. **Get Access Token**
```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "demo", "password": "demo"}'
```

Save the `access_token` from the response.

2. **Upload a Document**
```bash
curl -X POST "http://localhost:8000/api/documents/upload" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "file=@sample.pdf"
```

3. **Query the Knowledge Base**
```bash
curl -X POST "http://localhost:8000/api/query" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is this document about?",
    "top_k": 5
  }'
```

### Using the Interactive Docs

Open your browser and go to:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

Click "Authorize" and enter your access token to test endpoints interactively.

## Step 8: Setup Ollama (Optional)

If you want to use local LLMs instead of OpenAI/Anthropic:

```bash
# Install Ollama (https://ollama.ai)
# Then pull models:
ollama pull llama3.2
ollama pull bge-m3
```

Update `.env`:
```
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
OLLAMA_EMBEDDING_MODEL=bge-m3
```

## Common Commands

### Check System Health
```bash
curl http://localhost:8000/api/system/health
```

### Get System Stats
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/system/stats
```

### View Ontology
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/ontology
```

### Visualize Graph
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/graph/visualization?limit=50"
```

## Troubleshooting

### Neo4j Connection Error
```bash
# Verify credentials in .env
# Check Neo4j is accessible

# Access Neo4j browser
open http://localhost:7474

# Try connecting with cypher-shell
cypher-shell -u neo4j -p password
```

### Redis Connection Error
```bash
# Check Redis is running
redis-cli ping

# Test Redis connection
redis-cli -h localhost -p 6379 ping
```

### Worker Not Processing
```bash
# Check worker logs
# If running locally:
celery -A src.graph_rag_service.workers.celery_worker inspect active
```

### API Server Won't Start
```bash
# Check for port conflicts
lsof -i :8000  # On Mac/Linux
netstat -ano | findstr :8000  # On Windows

# View detailed logs
uv run python main.py
```

## Next Steps

- Read the [README.md](README.md) for comprehensive documentation
- Check [ARCHITECTURE.md](ARCHITECTURE.md) for system design details
- Explore the API docs at `http://localhost:8000/docs`

## Using with Different LLM Providers

### OpenAI
```bash
# In .env:
DEFAULT_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
```

### Anthropic
```bash
# In .env:
DEFAULT_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### Google Gemini
```bash
# In .env:
DEFAULT_LLM_PROVIDER=gemini
GOOGLE_API_KEY=your-key-here
```

Services will be available at:
- API: `http://localhost:8000`
- Neo4j Browser: `http://localhost:7474`

## Need Help?

- Check the troubleshooting section above
- Read the full [README.md](README.md)
- Open an issue on GitHub

Happy building! 🚀
