FROM ubuntu:22.04

# Avoid tzdata interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
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

# Download and extract Neo4j
RUN wget -q https://neo4j.com/artifact.php?name=neo4j-community-5.18.0-unix.tar.gz -O neo4j.tar.gz \
    && tar -xf neo4j.tar.gz \
    && mv neo4j-community-5.18.0 neo4j \
    && rm neo4j.tar.gz

# Configure Neo4j for demo mode (disable auth, limit memory)
RUN echo "dbms.security.auth_enabled=false" >> neo4j/conf/neo4j.conf \
    && echo "server.memory.heap.initial_size=512m" >> neo4j/conf/neo4j.conf \
    && echo "server.memory.heap.max_size=1G" >> neo4j/conf/neo4j.conf \
    && echo "server.memory.pagecache.size=1G" >> neo4j/conf/neo4j.conf

# Copy project files
COPY . .

# Build frontend
WORKDIR /app/frontend-react
RUN npm install
RUN npm run build

# Setup Python backend
WORKDIR /app
RUN python3.11 -m venv .venv
ENV PATH="/app/.venv/bin:$PATH"
RUN pip install --upgrade pip
RUN pip install -r requirements.txt || true # If requirements.txt doesn't exist, we'll install from pyproject.toml
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
# Install APOC plugin (if needed for GDS/Leiden)\n\
# For simplicity, we just use the built-in algos if possible or assume they are configured.\n\
\n\
# Set environment variables for Demo Mode\n\
export NEO4J_URI=bolt://localhost:7687\n\
export NEO4J_USER=neo4j\n\
export NEO4J_PASSWORD=dummy\n\
export REDIS_URL=redis://localhost:6379\n\
export DEMO_MODE=true\n\
export ENVIRONMENT=production\n\
\n\
# Start FastAPI and serve static files (frontend)\n\
uvicorn src.graph_rag_service.api.server:app --host 0.0.0.0 --port 7860\n\
' > start.sh && chmod +x start.sh

# HF Spaces requires serving on 7860
EXPOSE 7860

CMD ["./start.sh"]
