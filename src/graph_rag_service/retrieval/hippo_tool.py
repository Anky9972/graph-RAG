import logging
from typing import List, Dict, Any, Optional

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider

logger = logging.getLogger(__name__)

class HippoRAGTool:
    """
    Implements HippoRAG-style Personalized PageRank (PPR) retrieval.
    Propagates activation from query entities through the knowledge graph
    to find highly relevant chunks that might be multiple hops away.
    """
    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider):
        self.store = store
        self.llm = llm

    async def run(self, query: str, k: int = 5, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        # Extract entities from query
        prompt = f"Extract key entities from this query as a comma-separated list: '{query}'. Return ONLY the list, nothing else."
        response = await self.llm.complete(prompt, temperature=0.0)
        entities = [e.strip() for e in response.split(",") if e.strip()]
        
        if not entities:
            from .tools import HybridSearchTool
            hybrid = HybridSearchTool(self.store, self.llm)
            return await hybrid.run(query, k=k, tenant_id=tenant_id)

        # Find seed nodes in Neo4j
        seeds = []
        for e in entities:
            # Case-insensitive contains search
            res = await self.store.execute_query(
                "MATCH (n:Entity) WHERE toLower(n.name) CONTAINS toLower($name) " + 
                ("AND n.tenant_id = $tenant_id " if tenant_id else "") +
                "RETURN id(n) as id LIMIT 3",
                {"name": e, "tenant_id": tenant_id}
            )
            for row in res:
                seeds.append(row["id"])
        
        if not seeds:
            from .tools import HybridSearchTool
            hybrid = HybridSearchTool(self.store, self.llm)
            return await hybrid.run(query, k=k, tenant_id=tenant_id)

        # Run PPR using Neo4j GDS
        graph_name = f"hippo_graph_{tenant_id}" if tenant_id else "hippo_graph_global"
        
        try:
            # Clean up previous projection if it exists
            try:
                await self.store.execute_query("CALL gds.graph.drop($graph_name, false)", {"graph_name": graph_name})
            except Exception:
                pass
            
            node_query = f"MATCH (n) WHERE (n:Entity OR n:Chunk) {'AND n.tenant_id = $tenant_id' if tenant_id else ''} RETURN id(n) AS id"
            rel_query = f"MATCH (s)-[r]->(t) WHERE (s:Entity OR s:Chunk) AND (t:Entity OR t:Chunk) {'AND s.tenant_id = $tenant_id AND t.tenant_id = $tenant_id' if tenant_id else ''} RETURN id(s) AS source, id(t) AS target"
            
            await self.store.execute_query(f"""
                CALL gds.graph.project.cypher(
                    $graph_name,
                    $node_query,
                    $rel_query,
                    {{parameters: {{tenant_id: $tenant_id}}}}
                )
            """, {
                "graph_name": graph_name,
                "node_query": node_query,
                "rel_query": rel_query,
                "tenant_id": tenant_id
            })
            
            ppr_query = """
            CALL gds.pageRank.stream($graph_name, {
                maxIterations: 20,
                dampingFactor: 0.85,
                sourceNodes: $seeds
            })
            YIELD nodeId, score
            MATCH (n) WHERE id(n) = nodeId AND n:Chunk
            RETURN n.text AS text, n.document_id AS document_id, score
            ORDER BY score DESC
            LIMIT $k
            """
            
            results = await self.store.execute_query(ppr_query, {
                "graph_name": graph_name,
                "seeds": seeds,
                "k": k
            })
            
            await self.store.execute_query("CALL gds.graph.drop($graph_name, false)", {"graph_name": graph_name})
            
            contexts = []
            for r in results:
                contexts.append({
                    "text": r["text"],
                    "score": r["score"],
                    "document_id": r["document_id"],
                    "retrieval_method": "hippo_ppr"
                })
            
            return contexts
            
        except Exception as e:
            logger.error(f"HippoRAG PPR failed: {e}")
            from .tools import HybridSearchTool
            hybrid = HybridSearchTool(self.store, self.llm)
            return await hybrid.run(query, k=k, tenant_id=tenant_id)
