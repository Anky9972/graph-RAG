import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import json

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider

logger = logging.getLogger(__name__)

class CommunityFinding(BaseModel):
    text: str
    supporting_chunk_ids: List[str] = []
    confidence: float = 0.0

class CommunityReport(BaseModel):
    community_id: str
    level: int
    title: str
    summary: str
    findings: List[CommunityFinding]
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
            {f"WHERE n.tenant_id = $tenant_id" if tenant_id else ""}
            RETURN id(n) AS id
        """
        
        rel_query = f"""
            MATCH (s:Entity)-[r]->(t:Entity)
            {f"WHERE s.tenant_id = $tenant_id AND t.tenant_id = $tenant_id" if tenant_id else ""}
            RETURN id(s) AS source, id(t) AS target
        """

        # Project the graph
        project_query = """
        CALL gds.graph.project.cypher(
            $graph_name,
            $node_query,
            $rel_query,
            {parameters: {tenant_id: $tenant_id}}
        )
        YIELD graphName, nodeCount, relationshipCount
        """
        
        try:
            await self.store.execute_query(project_query, {
                "graph_name": graph_name,
                "node_query": node_query,
                "rel_query": rel_query,
                "tenant_id": tenant_id
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
        tenant_filter = "n.tenant_id = $tenant_id AND" if tenant_id else ""
        
        # 1. Fetch communities and normalize to lists
        fetch_query = f"""
        MATCH (n:Entity)
        WHERE {tenant_filter} n.leiden_community IS NOT NULL
        RETURN id(n) AS node_id, n.leiden_community AS comm
        """
        rows = await self.store.execute_query(fetch_query, {"tenant_id": tenant_id})
        
        batch_data = []
        for row in rows:
            comm = row["comm"]
            comms = comm if isinstance(comm, list) else [comm]
            batch_data.append({"node_id": row["node_id"], "comms": comms})
            
        if not batch_data:
            return

        # 2. Write communities with parameterized UNWIND — NO string interpolation
        write_query = """
        UNWIND $batch AS item
        MATCH (n:Entity) WHERE id(n) = item.node_id

        MERGE (c0:Community {id: "0:" + toString(item.comms[0])})
        SET c0.level = 0,
            c0.tenant_id = $tenant_id
        MERGE (n)-[:IN_COMMUNITY]->(c0)

        WITH item, item.comms AS comms
        WHERE size(comms) > 1
        UNWIND range(0, size(comms)-2) AS level
        MERGE (c1:Community {id: toString(level) + ":" + toString(comms[level])})
        SET c1.level = level,
            c1.tenant_id = $tenant_id
        MERGE (c2:Community {id: toString(level+1) + ":" + toString(comms[level+1])})
        SET c2.level = level+1,
            c2.tenant_id = $tenant_id
        MERGE (c1)-[:PARENT]->(c2)
        """

        await self.store.execute_query(write_query, {"batch": batch_data, "tenant_id": tenant_id})
        logger.info(f"Community nodes and IN_COMMUNITY relationships created for tenant {tenant_id}")

    async def collect_evidence(self, community_id: str, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Collects chunks related to the entities in a community.
        """
        tenant_filter = "WHERE c.tenant_id = $tenant_id" if tenant_id else ""
        
        query = f"""
        MATCH (comm:Community {{id: $community_id}})<-[:IN_COMMUNITY]-(e:Entity)
        MATCH (c:Chunk)-[:MENTIONS]->(e)
        {tenant_filter}
        RETURN DISTINCT c.id AS chunk_id, c.text AS text, c.document_id AS document_id
        LIMIT 50
        """
        
        results = await self.store.execute_query(query, {
            "community_id": community_id,
            "tenant_id": tenant_id
        })
        
        return [{"chunk_id": r.get('chunk_id'), "text": r.get('text'), "document_id": r.get('document_id')} for r in results]

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
        
        evidence_texts = [f"Chunk {e['chunk_id']}: {e['text']}" for e in evidence[:10]]
        prompt = f"""
        You are an expert analyst generating a Community Report for a knowledge graph.
        
        Entities in this community:
        {", ".join(entities[:20])}
        
        Evidence chunks:
        {"\n---\n".join(evidence_texts)}
        
        Please provide a report with:
        - A concise, descriptive title
        - A summary of what this community represents
        - 3-5 key findings or themes, with chunk_id citations and confidence scores.
        
        Output as JSON matching this schema:
        {{
            "title": "Community Title",
            "summary": "Detailed summary...",
            "findings": [
              {{
                "text": "Finding description...",
                "supporting_chunk_ids": ["chunk_id_1", "chunk_id_2"],
                "confidence": 0.85
              }}
            ]
        }}
        """
        
        response = await self.llm.complete(prompt, temperature=0.2)

        # Fetch actual community level from graph node (before parsing so we always have it)
        level_res = await self.store.execute_query(
            "MATCH (c:Community {id: $community_id}) RETURN coalesce(c.level, 0) AS level",
            {"community_id": community_id}
        )
        community_level = level_res[0]["level"] if level_res else 0

        # Build valid chunk ID set for citation validation
        valid_chunk_ids = {e["chunk_id"] for e in evidence}

        try:
            cleaned = response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0]

            data = json.loads(cleaned.strip())

            report = CommunityReport(
                community_id=community_id,
                level=community_level,
                title=data.get("title", f"Community {community_id}"),
                summary=data.get("summary", ""),
                findings=data.get("findings", []),
                entities=entities,
                tenant_id=tenant_id
            )

            # Validate chunk citations against real evidence; extract used IDs
            used_chunk_ids = []
            for finding in report.findings:
                finding.supporting_chunk_ids = [
                    cid for cid in finding.supporting_chunk_ids if cid in valid_chunk_ids
                ]
                used_chunk_ids.extend(finding.supporting_chunk_ids)
            used_chunk_ids = list(set(used_chunk_ids))

            # Store report in graph
            await self.store.execute_query(f"""
                MATCH (c:Community {{id: $community_id}})
                {f"WHERE c.tenant_id = $tenant_id" if tenant_id else ""}
                SET c.title = $title,
                    c.summary = $summary,
                    c.report_json = $report_json,
                    c.evidence_chunk_ids = $evidence_chunk_ids,
                    c.report_generated = true
            """, {
                "community_id": community_id,
                "tenant_id": tenant_id,
                "title": report.title,
                "summary": report.summary,
                "report_json": report.model_dump_json(),
                "evidence_chunk_ids": used_chunk_ids
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
        findings_text = "; ".join(f.text if isinstance(f, CommunityFinding) else str(f) for f in report.findings)
        text_to_embed = f"Title: {report.title}\nSummary: {report.summary}\nFindings: {findings_text}"
        embedding = await self.llm.embed(text_to_embed)
        
        if embedding:
            params = {
                "community_id": report.community_id,
                "embedding": embedding
            }
            if report.tenant_id:
                params["tenant_id"] = report.tenant_id
                
            await self.store.execute_query(f"""
                MATCH (c:Community {{id: $community_id}})
                {f"WHERE c.tenant_id = $tenant_id" if report.tenant_id else ""}
                CALL db.create.setNodeVectorProperty(c, 'embedding', $embedding)
            """, params)

    async def generate_all_reports(self, tenant_id: Optional[str] = None) -> List[CommunityReport]:
        """Generate reports for all communities."""
        tenant_filter = "WHERE c.tenant_id = $tenant_id" if tenant_id else ""
        query = f"MATCH (c:Community) {tenant_filter} RETURN c.id AS id"
        results = await self.store.execute_query(query, {"tenant_id": tenant_id})
        reports = []
        for r in results:
            report = await self.generate_report(r["id"], tenant_id)
            if report:
                reports.append(report)
        return reports
