"""
GraphMemoryUpdater — MiroFish Point 1: Writable Live Graph
Accepts raw text snippets and merges new entities/relationships into the live
Neo4j graph without a full document re-ingest cycle.

Inspired by MiroFish's zep_graph_memory_updater.py which dynamically updates
the knowledge graph whenever a simulation agent takes an action.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import LLMFactory
from ..core.models import Chunk, OntologySchema
from ..ingestion.extractor import KnowledgeExtractor
from ..config import settings


class GraphUpdateResult(BaseModel):
    """Result from a live graph update operation"""
    entities_added: int = 0
    relationships_added: int = 0
    entities_merged: int = 0
    source_label: str = "api_push"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    message: str = ""


class GraphMemoryUpdater:
    """
    Turns the static knowledge graph into a living, writable store.

    Usage:
        updater = GraphMemoryUpdater(graph_store, llm_provider)
        result = await updater.update_from_text("Tesla acquired SolarCity in 2016")
    """

    def __init__(
        self,
        graph_store: Neo4jStore,
        llm_provider: Optional[str] = None,
    ) -> None:
        self.store = graph_store
        self.llm = LLMFactory.create(provider=llm_provider)
        self._extractor: Optional[KnowledgeExtractor] = None

    # ── Public API ─────────────────────────────────────────────────────────

    async def update_from_text(
        self,
        text: str,
        source_label: str = "api_push",
        valid_from: Optional[datetime] = None,
        tenant_id: Optional[str] = None,
    ) -> GraphUpdateResult:
        """
        Extract entities/relationships from text and MERGE them into Neo4j.

        All writes use MERGE so the operation is idempotent — calling it
        multiple times with the same text will not create duplicate nodes.
        New properties (source_label, update_count) track provenance.

        Args:
            text:         Raw text to extract knowledge from
            source_label: Traceability tag  e.g. "chat:conv_123", "api_push"
            valid_from:   Timestamp for temporal graph edges (default: now)
            tenant_id:    Tenant namespace override

        Returns:
            GraphUpdateResult with entity/relationship counts
        """
        if not text or not text.strip():
            return GraphUpdateResult(message="Empty text — nothing to update")

        valid_from = valid_from or datetime.utcnow()
        tenant_id = tenant_id or settings.default_tenant_id

        # Load ontology (needed by extractor for entity type validation)
        ontology = await self.store.load_ontology()
        if not ontology:
            # If no ontology yet, use a permissive fallback
            ontology = OntologySchema(
                version="live_update",
                entity_types=["Entity", "Person", "Organization", "Location",
                               "Concept", "Event", "Product", "Technology"],
                relationship_types=["RELATED_TO", "PART_OF", "WORKS_WITH",
                                    "BELONGS_TO", "CREATED_BY", "LOCATED_IN",
                                    "ACQUIRED", "FOUNDED_BY", "CEO_OF",
                                    "PARTNERED_WITH", "COMPETES_WITH"],
                approved=True,
            )

        # Build a single pseudo-chunk from the text
        chunk = Chunk(
            id=str(uuid.uuid4()),
            text=text,
            document_id=f"live_update:{source_label}",
            chunk_index=0,
        )

        # Extract entities and relationships
        extractor = self._get_extractor()
        try:
            extraction = await extractor.extract_from_chunk(chunk, ontology)
        except Exception as exc:
            return GraphUpdateResult(
                message=f"Extraction failed: {exc}",
                source_label=source_label,
            )

        entities_added = 0
        entities_merged = 0
        relationships_added = 0

        # Merge entities
        for entity in extraction.entities:
            entity.valid_from = valid_from
            entity.tenant_id = tenant_id
            try:
                await self.store.create_node(entity)
                # Tag node with source provenance
                await self.store.execute_query(
                    """
                    MATCH (e:Entity {name: $name})
                    SET e.source_label = $label,
                        e.update_count = coalesce(e.update_count, 0) + 1,
                        e.last_updated = datetime()
                    """,
                    {"name": entity.name, "label": source_label},
                )
                entities_added += 1
            except Exception:
                entities_merged += 1  # MERGE hit an existing node

        # Merge relationships
        for rel in extraction.relationships:
            rel.valid_from = valid_from
            rel.tenant_id = tenant_id
            rel.source_document_id = f"live_update:{source_label}"
            try:
                await self.store.create_relationship(rel)
                relationships_added += 1
            except Exception:
                pass  # relationship already exists or source/target missing

        return GraphUpdateResult(
            entities_added=entities_added,
            entities_merged=entities_merged,
            relationships_added=relationships_added,
            source_label=source_label,
            message=(
                f"Merged {entities_added} entities, "
                f"{relationships_added} relationships from '{source_label}'"
            ),
        )

    async def is_fact_assertion(self, text: str) -> bool:
        """
        Quick LLM classifier: does this text assert a new fact?
        Used to decide whether to auto-update the graph from chat messages.
        """
        prompt = (
            f"Does the following text make a clear factual assertion "
            f"(not a question, greeting, or opinion)?\n\n"
            f'Text: "{text[:300]}"\n\n'
            f"Answer with only: yes / no"
        )
        try:
            answer = await self.llm.complete(prompt, temperature=0.0)
            return answer.strip().lower().startswith("yes")
        except Exception:
            return False

    # ── Helpers ────────────────────────────────────────────────────────────

    def _get_extractor(self) -> KnowledgeExtractor:
        if self._extractor is None:
            self._extractor = KnowledgeExtractor(llm_provider=None)
        return self._extractor
