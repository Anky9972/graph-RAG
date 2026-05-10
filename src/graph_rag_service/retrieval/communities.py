import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import json

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider

logger = logging.getLogger(__name__)

class CommunityFinding(BaseModel):
    text: str
    supporting_chunk_ids: List[str] = Field(default_factory=list)
    confidence: float = 0.0

class CommunityReport(BaseModel):
    community_id: str
    level: int
    title: str
    summary: str
    findings: List[CommunityFinding] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
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

        P0 fix: entities are now linked via IN_COMMUNITY to EVERY level of their
        community hierarchy, not just level 0.  This ensures generate_report()
        can retrieve entities for parent communities.
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

        # 2. Write community nodes and PARENT edges (same as before)
        tid_prefix = (tenant_id + ":") if tenant_id else ""
        write_query = """
        UNWIND $batch AS item
        MATCH (n:Entity) WHERE id(n) = item.node_id

        MERGE (c0:Community {id: $tid_prefix + "0:" + toString(item.comms[0])})
        SET c0.level = 0,
            c0.tenant_id = $tenant_id,
            c0.local_id = "0:" + toString(item.comms[0])
        MERGE (n)-[:IN_COMMUNITY]->(c0)

        WITH item, item.comms AS comms
        WHERE size(comms) > 1
        UNWIND range(0, size(comms)-2) AS level
        MERGE (c1:Community {id: $tid_prefix + toString(level) + ":" + toString(comms[level])})
        SET c1.level = level,
            c1.tenant_id = $tenant_id,
            c1.local_id = toString(level) + ":" + toString(comms[level])
        MERGE (c2:Community {id: $tid_prefix + toString(level+1) + ":" + toString(comms[level+1])})
        SET c2.level = level+1,
            c2.tenant_id = $tenant_id,
            c2.local_id = toString(level+1) + ":" + toString(comms[level+1])
        MERGE (c1)-[:PARENT]->(c2)
        """

        await self.store.execute_query(write_query, {
            "batch": batch_data,
            "tenant_id": tenant_id,
            "tid_prefix": tid_prefix
        })

        # 3. P0 fix: propagate IN_COMMUNITY edges from each entity to EVERY
        #    ancestor level so that parent communities can find their entities.
        propagate_query = """
        UNWIND $batch AS item
        MATCH (n:Entity) WHERE id(n) = item.node_id
        UNWIND range(0, size(item.comms)-1) AS level
        MERGE (c:Community {id: $tid_prefix + toString(level) + ":" + toString(item.comms[level])})
        MERGE (n)-[:IN_COMMUNITY {level: level}]->(c)
        """
        await self.store.execute_query(propagate_query, {
            "batch": batch_data,
            "tenant_id": tenant_id,
            "tid_prefix": tid_prefix
        })
        logger.info(f"Community nodes, PARENT edges, and multi-level IN_COMMUNITY relationships created for tenant {tenant_id}")

    async def collect_evidence(self, community_id: str, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Collects chunks related to the entities in a community, fully tenant-scoped.
        """
        comm_filter = "AND comm.tenant_id = $tenant_id" if tenant_id else ""
        entity_filter = "AND e.tenant_id = $tenant_id" if tenant_id else ""
        chunk_filter = "AND c.tenant_id = $tenant_id" if tenant_id else ""

        query = f"""
        MATCH (comm:Community {{id: $community_id}})<-[:IN_COMMUNITY]-(e:Entity)
        WHERE 1=1 {comm_filter} {entity_filter}
        MATCH (c:Chunk)-[:MENTIONS]->(e)
        WHERE 1=1 {chunk_filter}
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

        For leaf communities (level 0) entities are fetched directly via
        IN_COMMUNITY edges.  For parent communities the entity list may be
        supplemented by rolling up child community reports so the report
        remains meaningful even when entities are not directly linked.
        """
        # Get entities (works for all levels due to multi-level IN_COMMUNITY propagation)
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

        # P0 fix: if no direct entities (parent community), roll up child community reports
        child_summaries: List[str] = []
        if not entities:
            child_report_filter = "AND child.tenant_id = $tenant_id" if tenant_id else ""
            child_query = f"""
            MATCH (child:Community)-[:PARENT]->(parent:Community {{id: $community_id}})
            WHERE child.report_generated = true {child_report_filter}
            RETURN child.id AS child_id, child.title AS title, child.summary AS summary
            LIMIT 20
            """
            child_res = await self.store.execute_query(child_query, {
                "community_id": community_id,
                "tenant_id": tenant_id
            })
            child_summaries = [
                f"Child community '{r['title']}': {r['summary']}"
                for r in child_res if r.get("title")
            ]
            if not child_summaries:
                # Nothing at all — skip
                return None
            # Use child community names as placeholder entities for the prompt
            entities = [r.get("title", r["child_id"]) for r in child_res if r.get("title")]
            
        evidence = await self.collect_evidence(community_id, tenant_id)
        
        evidence_texts = [f"Chunk {e['chunk_id']}: {e['text']}" for e in evidence[:10]]

        # Build prompt — include child summaries when available for parent communities
        child_context = ""
        if child_summaries:
            child_context = f"""
        Child community summaries (for parent report synthesis):
        {'\n'.join(child_summaries[:10])}
"""
        prompt = f"""
        You are an expert analyst generating a Community Report for a knowledge graph.
        
        Entities in this community:
        {", ".join(entities[:20])}
        {child_context}
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

        # Fetch actual community level from graph node — tenant-scoped
        level_match = "MATCH (c:Community {id: $community_id, tenant_id: $tenant_id})" if tenant_id else "MATCH (c:Community {id: $community_id})"
        level_res = await self.store.execute_query(
            f"{level_match} RETURN coalesce(c.level, 0) AS level",
            {"community_id": community_id, "tenant_id": tenant_id}
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
        """
        Generate reports for all communities.

        P0 fix: communities are processed in ascending level order so that
        child reports always exist before parent report generation, enabling
        parents to summarise child summaries.
        """
        tenant_filter = "WHERE c.tenant_id = $tenant_id" if tenant_id else ""
        query = f"""
        MATCH (c:Community) {tenant_filter}
        RETURN c.id AS id, coalesce(c.level, 0) AS level
        ORDER BY level ASC
        """
        results = await self.store.execute_query(query, {"tenant_id": tenant_id})
        reports = []
        for r in results:
            report = await self.generate_report(r["id"], tenant_id)
            if report:
                reports.append(report)
        return reports
