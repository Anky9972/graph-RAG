"""
EntityEnricher — MiroFish Point 2: Entity Profile Summaries
Traverses each entity's graph neighborhood and generates an LLM-synthesized
summary stored as `e.summary` on the Neo4j node.

Inspired by MiroFish's oasis_profile_generator.py which builds rich
psychological + demographic profiles for simulation agents from graph data.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import LLMFactory
from ..config import settings


class EnrichmentResult(BaseModel):
    """Result from an entity enrichment operation"""
    entities_enriched: int = 0
    entities_skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    message: str = ""


class EntityEnricher:
    """
    Post-ingestion enrichment pass: synthesizes a human-readable profile
    summary for each entity based on its graph neighborhood.

    The summary is stored as `e.summary` on the Neo4j Entity node and
    indexed via a separate vector index so it can be retrieved directly.
    """

    def __init__(
        self,
        graph_store: Neo4jStore,
        llm_provider: Optional[str] = None,
        batch_size: int = 20,
    ) -> None:
        self.store = graph_store
        self.llm = LLMFactory.create(provider=llm_provider)
        self.batch_size = batch_size

    # ── Public API ─────────────────────────────────────────────────────────

    async def enrich_all_entities(
        self,
        min_connections: int = 1,
        overwrite: bool = False,
    ) -> EnrichmentResult:
        """
        Enrich all entities that:
        - Have >= min_connections relationships, AND
        - Do not yet have a summary (or overwrite=True)

        Args:
            min_connections: Minimum degree to qualify for enrichment
            overwrite:       Re-generate summaries for already-enriched nodes

        Returns:
            EnrichmentResult with counts
        """
        import time
        start = time.time()

        # Fetch qualifying entities
        where_clause = (
            "" if overwrite else "AND (e.summary IS NULL OR e.summary = '')"
        )
        query = f"""
        MATCH (e:Entity)
        WHERE COUNT { (e)--() } >= $min_connections
        {where_clause}
        RETURN e.name as name, e.type as type
        ORDER BY COUNT { (e)--() } DESC
        """
        try:
            rows = await self.store.execute_query(
                query, {"min_connections": min_connections}
            )
        except Exception as exc:
            return EnrichmentResult(message=f"Query failed: {exc}")

        enriched = 0
        skipped = 0
        errors = 0

        # Process in batches
        for i in range(0, len(rows), self.batch_size):
            batch = rows[i : i + self.batch_size]
            tasks = [
                self._enrich_single(row["name"], row.get("type", "Entity"))
                for row in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    errors += 1
                elif r:
                    enriched += 1
                else:
                    skipped += 1

        duration = time.time() - start
        return EnrichmentResult(
            entities_enriched=enriched,
            entities_skipped=skipped,
            errors=errors,
            duration_seconds=round(duration, 2),
            message=f"Enriched {enriched}/{len(rows)} entities in {duration:.1f}s",
        )

    async def enrich_entity(self, entity_name: str) -> Optional[str]:
        """
        Enrich a single entity by name. Returns the generated summary or None.
        """
        # Get entity type
        rows = await self.store.execute_query(
            "MATCH (e:Entity {name: $name}) RETURN e.type as type",
            {"name": entity_name},
        )
        entity_type = rows[0]["type"] if rows else "Entity"
        result = await self._enrich_single(entity_name, entity_type)
        if result:
            # Return the summary
            summary_rows = await self.store.execute_query(
                "MATCH (e:Entity {name: $name}) RETURN e.summary as summary",
                {"name": entity_name},
            )
            return summary_rows[0]["summary"] if summary_rows else None
        return None

    async def get_entity_summary(self, entity_name: str) -> Optional[str]:
        """Get the stored summary for an entity, or None if not enriched."""
        rows = await self.store.execute_query(
            "MATCH (e:Entity {name: $name}) RETURN e.summary as summary",
            {"name": entity_name},
        )
        if not rows:
            return None
        return rows[0].get("summary")

    # ── Internal ────────────────────────────────────────────────────────────

    async def _enrich_single(
        self, entity_name: str, entity_type: str
    ) -> bool:
        """Generate and persist a summary for one entity. Returns True on success."""
        try:
            # Get the 2-hop neighborhood
            neighbors = await self.store.get_neighbors(entity_name, depth=2)

            # Also get direct relationship types
            rel_query = """
            MATCH (e:Entity {name: $name})-[r]-(other:Entity)
            RETURN type(r) as rel_type, other.name as other_name,
                   other.type as other_type
            LIMIT 30
            """
            rels = await self.store.execute_query(
                rel_query, {"name": entity_name}
            )

            neighborhood_lines: List[str] = []
            for rel in rels:
                neighborhood_lines.append(
                    f"- {rel['rel_type']} → {rel['other_name']} ({rel['other_type']})"
                )

            if not neighborhood_lines and not neighbors:
                return False  # isolated node — skip

            neighborhood_text = "\n".join(neighborhood_lines[:40])

            prompt = f"""You are summarizing an entity from a knowledge graph.

Entity: {entity_name}
Type: {entity_type}

Direct relationships:
{neighborhood_text if neighborhood_text else "(no direct relationships found)"}

Write a concise 2-3 sentence factual profile of "{entity_name}" based ONLY
on the graph connections listed above. Be specific, avoid vague language,
and do not add information not implied by the relationships."""

            summary = await self.llm.complete(prompt, temperature=0.2)
            summary = summary.strip()

            if not summary:
                return False

            # Write summary back to Neo4j
            await self.store.execute_query(
                """
                MATCH (e:Entity {name: $name})
                SET e.summary = $summary,
                    e.summary_updated_at = datetime()
                """,
                {"name": entity_name, "summary": summary},
            )
            return True
        except Exception as exc:
            print(f"[EntityEnricher] Failed to enrich '{entity_name}': {exc}")
            return False
