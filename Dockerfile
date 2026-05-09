FROM ubuntu:22.04

# Avoid tzdata interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies and Python 3.12
RUN apt-get update && apt-get install -y software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python3-pip \
    curl \
    wget \
    git \
    redis-server \
    openjdk-17-jdk \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for frontend build
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

# Create app directory
WORKDIR /app

# Download and extract Neo4j and GDS plugin
RUN wget -q https://neo4j.com/artifact.php?name=neo4j-community-5.18.0-unix.tar.gz -O neo4j.tar.gz \
    && tar -xf neo4j.tar.gz \
    && mv neo4j-community-5.18.0 neo4j \
    && rm neo4j.tar.gz \
    && wget -q https://github.com/neo4j/graph-data-science/releases/download/2.6.4/neo4j-graph-data-science-2.6.4.jar -O neo4j/plugins/neo4j-graph-data-science.jar

# Configure Neo4j for demo mode (disable auth, limit memory, enable GDS)
RUN echo "dbms.security.auth_enabled=false" >> neo4j/conf/neo4j.conf \
    && echo "server.memory.heap.initial_size=512m" >> neo4j/conf/neo4j.conf \
    && echo "server.memory.heap.max_size=1G" >> neo4j/conf/neo4j.conf \
    && echo "server.memory.pagecache.size=1G" >> neo4j/conf/neo4j.conf \
    && echo "dbms.security.procedures.unrestricted=gds.*" >> neo4j/conf/neo4j.conf

# Copy project files
COPY . .

# Build frontend
WORKDIR /app/frontend-react
RUN npm install
RUN npm run build

# Setup Python backend
WORKDIR /app
RUN python3.12 -m venv .venv
ENV PATH="/app/.venv/bin:$PATH"
RUN pip install --upgrade pip
RUN pip install -e .

# Create start script
RUN echo '#!/bin/bash\n\
\n\
# Start Redis\n\
redis-server --daemonize yes\n\
\n\
# Start Neo4j in background\n\
/app/neo4j/bin/neo4j start\n\
\n\
# Wait for Neo4j to be ready\n\
echo "Waiting for Neo4j to start..."\n\
while ! curl -s http://localhost:7474 > /dev/null; do\n\
    sleep 2\n\
done\n\
echo "Neo4j is up!"\n\
\n\
# Set environment variables for Demo Mode\n\
export NEO4J_URI=bolt://localhost:7687\n\
export NEO4J_USER=neo4j\n\
export NEO4J_PASSWORD=dummy\n\
export REDIS_HOST=localhost\n\
export REDIS_PORT=6379\n\
export REDIS_DB=0\n\
export DEMO_MODE=true\n\
export ENVIRONMENT=production\n\
export SECRET_KEY=demo-secret-key-1234567890\n\
\n\
if [ -z "$GEMINI_API_KEY" ]; then\n\
    export DEFAULT_LLM_PROVIDER=ollama\n\
else\n\
    export DEFAULT_LLM_PROVIDER=gemini\n\
fi\n\
\n\
# Create default admin user\n\
python -c "\n\
from src.graph_rag_service.api.auth import get_password_hash\n\
import redis\n\
r = redis.Redis(host='\''localhost'\'', port=6379, db=0)\n\
user_data = {'\''username'\'': '\''admin'\'', '\''password_hash'\'': get_password_hash('\''admin'\''), '\''tenant_id'\'': '\''demo_tenant'\''}\n\
import json\n\
r.set('\''user:admin'\'', json.dumps(user_data))\n\
print('\''Admin user created'\'')\n\
"\n\
\n\
# Start FastAPI and serve static files (frontend)\n\
uvicorn src.graph_rag_service.api.server:app --host 0.0.0.0 --port 7860\n\
' > start.sh && chmod +x start.sh

# HF Spaces requires serving on 7860
EXPOSE 7860

CMD ["./start.sh"]
