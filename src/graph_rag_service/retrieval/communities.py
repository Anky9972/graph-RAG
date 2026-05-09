import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import json

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider

logger = logging.getLogger(__name__)

class CommunityReport(BaseModel):
    community_id: str
    level: int
    title: str
    summary: str
    findings: List[str]
    entities: List[str]
    tenant_id: Optional[str] = None

class CommunityBuilder:
    """
    Implements Hierarchical Leiden Community Detection and Report Generation
    for production-grade GraphRAG.
    """

    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider):
        self.store = store
        self.llm = llm

    async def run_leiden(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Runs the Hierarchical Leiden algorithm using Neo4j GDS.
        """
        # Create an in-memory graph projection for the tenant
        graph_name = f"graph_leiden_{tenant_id}" if tenant_id else "graph_leiden_global"
        
        # Drop projection if exists
        try:
            await self.store.execute_query(
                "CALL gds.graph.drop($graph_name, false)",
                {"graph_name": graph_name}
            )
        except Exception as e:
            logger.debug(f"GDS drop failed (expected if missing): {e}")

        # Node and Relationship queries with tenant filtering
        node_query = f"""
            MATCH (n:Entity)
            {f"WHERE n.tenant_id = '{tenant_id}'" if tenant_id else ""}
            RETURN id(n) AS id
        """
        
        rel_query = f"""
            MATCH (s:Entity)-[r]->(t:Entity)
            {f"WHERE s.tenant_id = '{tenant_id}' AND t.tenant_id = '{tenant_id}'" if tenant_id else ""}
            RETURN id(s) AS source, id(t) AS target
        """

        # Project the graph
        project_query = """
        CALL gds.graph.project.cypher(
            $graph_name,
            $node_query,
            $rel_query
        )
        YIELD graphName, nodeCount, relationshipCount
        """
        
        try:
            await self.store.execute_query(project_query, {
                "graph_name": graph_name,
                "node_query": node_query,
                "rel_query": rel_query
            })

            # Run Leiden to write community IDs to the nodes
            leiden_query = """
            CALL gds.leiden.write(
                $graph_name,
                {
                    writeProperty: 'leiden_community',
                    includeIntermediateCommunities: true
                }
            )
            YIELD createMillis, computeMillis, writeMillis, nodePropertiesWritten, modularity, modularities
            RETURN createMillis, computeMillis, writeMillis, nodePropertiesWritten, modularity, modularities
            """
            
            result = await self.store.execute_query(leiden_query, {"graph_name": graph_name})
            
            # Clean up projection
            await self.store.execute_query("CALL gds.graph.drop($graph_name, false)", {"graph_name": graph_name})
            
            if not result:
                return {"status": "error", "message": "Leiden execution returned no result"}
            
            stats = result[0]
            logger.info(f"Leiden completed for tenant {tenant_id}: {stats}")
            return {
                "status": "success",
                "modularity": stats.get("modularity"),
                "nodes_written": stats.get("nodePropertiesWritten")
            }
            
        except Exception as e:
            logger.error(f"Leiden community detection failed: {e}")
            return {"status": "error", "message": str(e)}

    async def create_community_nodes(self, tenant_id: Optional[str] = None):
        """
        Creates (Community) nodes in Neo4j based on the 'leiden_community' properties.
        """
        # In a true hierarchical setup, Leiden with includeIntermediateCommunities writes arrays.
        # For simplicity, we'll group by the assigned primary community.
        
        tenant_filter = "n.tenant_id = $tenant_id AND" if tenant_id else ""
        
        query = f"""
        MATCH (n:Entity)
        WHERE {tenant_filter} n.leiden_community IS NOT NULL
        WITH n.leiden_community AS comm_id, collect(n) AS members
        MERGE (c:Community {{id: toString(comm_id)}})
        SET c.level = 0,
            c.tenant_id = $tenant_id
        WITH c, members
        UNWIND members AS m
        MERGE (m)-[:IN_COMMUNITY]->(c)
        """
        
        await self.store.execute_query(query, {"tenant_id": tenant_id})
        logger.info(f"Community nodes and IN_COMMUNITY relationships created for tenant {tenant_id}")

    async def collect_evidence(self, community_id: str, tenant_id: Optional[str] = None) -> List[str]:
        """
        Collects chunks related to the entities in a community.
        """
        tenant_filter = "WHERE c.tenant_id = $tenant_id" if tenant_id else ""
        
        query = f"""
        MATCH (comm:Community {{id: $community_id}})<-[:IN_COMMUNITY]-(e:Entity)
        MATCH (e)-[:MENTIONS|RELATED_TO]-(c:Chunk)
        {tenant_filter}
        RETURN DISTINCT c.text AS text
        LIMIT 50
        """
        
        results = await self.store.execute_query(query, {
            "community_id": community_id,
            "tenant_id": tenant_id
        })
        
        return [r["text"] for r in results]

    async def generate_report(self, community_id: str, tenant_id: Optional[str] = None) -> Optional[CommunityReport]:
        """
        Generates an LLM-backed community report.
        """
        # Get entities
        tenant_filter = "AND e.tenant_id = $tenant_id" if tenant_id else ""
        entity_query = f"""
        MATCH (comm:Community {{id: $community_id}})<-[:IN_COMMUNITY]-(e:Entity)
        WHERE 1=1 {tenant_filter}
        RETURN e.name AS name, e.type AS type
        LIMIT 100
        """
        entities_res = await self.store.execute_query(entity_query, {
            "community_id": community_id,
            "tenant_id": tenant_id
        })
        
        entities = [f"{r['name']} ({r['type']})" for r in entities_res]
        if not entities:
            return None
            
        evidence = await self.collect_evidence(community_id, tenant_id)
        
        prompt = f"""
        You are an expert analyst generating a Community Report for a knowledge graph.
        
        Entities in this community:
        {", ".join(entities[:20])}
        
        Evidence chunks:
        {"\n---\n".join(evidence[:10])}
        
        Please provide a report with:
        - A concise, descriptive title
        - A summary of what this community represents
        - 3-5 key findings or themes
        
        Output as JSON matching this schema:
        {{
            "title": "Community Title",
            "summary": "Detailed summary...",
            "findings": ["Finding 1", "Finding 2", ...]
        }}
        """
        
        response = await self.llm.complete(prompt, temperature=0.2)
        try:
            cleaned = response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0]
                
            data = json.loads(cleaned.strip())
            
            report = CommunityReport(
                community_id=community_id,
                level=0,
                title=data.get("title", f"Community {community_id}"),
                summary=data.get("summary", ""),
                findings=data.get("findings", []),
                entities=entities,
                tenant_id=tenant_id
            )
            
            # Store report in graph
            await self.store.execute_query(f"""
                MATCH (c:Community {{id: $community_id}})
                {f"WHERE c.tenant_id = $tenant_id" if tenant_id else ""}
                SET c.title = $title,
                    c.summary = $summary,
                    c.findings = $findings,
                    c.report_generated = true
            """, {
                "community_id": community_id,
                "tenant_id": tenant_id,
                "title": report.title,
                "summary": report.summary,
                "findings": report.findings
            })
            
            # Embed report for global community search
            await self.embed_report(report)
            
            return report
        except Exception as e:
            logger.error(f"Failed to generate report for community {community_id}: {e}")
            return None

    async def embed_report(self, report: CommunityReport):
        """
        Embeds the community report summary to allow semantic search over communities.
        """
        text_to_embed = f"Title: {report.title}\nSummary: {report.summary}\nFindings: {'; '.join(report.findings)}"
        embedding = await self.llm.embed(text_to_embed)
        
        if embedding:
            await self.store.execute_query(f"""
                MATCH (c:Community {{id: $community_id}})
                {f"WHERE c.tenant_id = $tenant_id" if report.tenant_id else ""}
                CALL db.create.setNodeVectorProperty(c, 'embedding', $embedding)
            """, {
                "community_id": report.community_id,
                "tenant_id": report.tenant_id,
                "embedding": embedding
            })
