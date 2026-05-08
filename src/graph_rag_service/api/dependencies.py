from fastapi import Request
from ..core.neo4j_store import Neo4jStore
from ..retrieval.agent import AgentRetrievalSystem
from ..ingestion.pipeline import IngestionPipeline
import redis

def get_graph_store(request: Request) -> Neo4jStore:
    return request.app.state.graph_store

def get_retrieval_agent(request: Request) -> AgentRetrievalSystem:
    return request.app.state.retrieval_agent

def get_ingestion_pipeline(request: Request) -> IngestionPipeline:
    return request.app.state.ingestion_pipeline

def get_redis_client(request: Request) -> redis.Redis:
    return request.app.state.redis_client
