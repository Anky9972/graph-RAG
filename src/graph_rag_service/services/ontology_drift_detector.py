"""
OntologyDriftDetector — MiroFish Point 4 analogue: Schema Evolution
Periodically re-samples chunks from Neo4j, proposes a fresh ontology,
diffs it against the current live schema, and surfaces drift alerts.

Activates the existing `enable_ontology_evolution` config flag that was
previously defined but never wired to actual logic.
"""

from __future__ import annotations

import uuid
import json
from datetime import datetime, timezone
from typing import List, Optional, Literal

from pydantic import BaseModel, Field

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import LLMFactory
from ..core.models import OntologySchema
from ..ingestion.ontology_generator import OntologyGenerator
from ..config import settings


class DriftReport(BaseModel):
    """Schema drift report surfaced by the OntologyDriftDetector"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    new_entity_types: List[str] = Field(default_factory=list)
    new_relationship_types: List[str] = Field(default_factory=list)
    removed_entity_types: List[str] = Field(default_factory=list)
    removed_relationship_types: List[str] = Field(default_factory=list)
    sample_size: int = 0
    drift_score: float = 0.0          # 0.0 = no drift, 1.0 = completely new schema
    status: Literal["pending", "approved", "rejected"] = "pending"
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class OntologyDriftDetector:
    """
    Detects when the graph's implicit schema has drifted away from the
    currently approved ontology by re-sampling random chunks and proposing
    a fresh ontology, then computing a diff.
    """

    def __init__(
        self,
        graph_store: Neo4jStore,
        llm_provider: Optional[str] = None,
    ) -> None:
        self.store = graph_store
        self.llm = LLMFactory.create(provider=llm_provider)
        self.generator = OntologyGenerator(llm_provider)

    # ── Public API ─────────────────────────────────────────────────────────

    async def detect_drift(
        self, sample_size: int = 10
    ) -> Optional[DriftReport]:
        """
        Run a drift detection cycle:
        1. Pull random chunks
        2. Generate proposed ontology (same algorithm as initial ingestion)
        3. Diff against stored ontology
        4. Persist and return DriftReport

        Returns None if there is no stored ontology yet.
        """
        current = await self.store.load_ontology()
        if not current:
            return None

        chunks = await self._get_random_chunks(sample_size)
        if not chunks:
            return None

        proposed = await self.generator.generate_initial_ontology(chunks)
        report = await self._compute_diff(current, proposed, sample_size)

        # Persist to Neo4j
        await self._save_drift_report(report)
        return report

    async def apply_drift_report(
        self,
        report_id: str,
        approved_by: str = "admin",
    ) -> bool:
        """
        Merge the new types from an approved drift report into the live ontology.
        Returns True if succeeded.
        """
        report = await self._load_drift_report(report_id)
        if not report:
            return False

        current = await self.store.load_ontology()
        if not current:
            return False

        # Merge new types
        updated_entities = list(
            set(current.entity_types) | set(report.new_entity_types)
        )
        updated_rels = list(
            set(current.relationship_types) | set(report.new_relationship_types)
        )

        bump = self._bump_version(current.version, report.drift_score)
        new_ontology = OntologySchema(
            version=bump,
            entity_types=sorted(updated_entities),
            relationship_types=sorted(updated_rels),
            properties=current.properties,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            approved=True,
        )

        await self.store.save_ontology(new_ontology)

        # Mark report as approved
        await self.store.execute_query(
            """
            MATCH (d:DriftReport {id: $id})
            SET d.status = 'approved',
                d.approved_by = $approved_by,
                d.approved_at = datetime()
            """,
            {"id": report_id, "approved_by": approved_by},
        )
        return True

    async def reject_drift_report(self, report_id: str) -> bool:
        """Mark a drift report as rejected."""
        result = await self.store.execute_query(
            """
            MATCH (d:DriftReport {id: $id})
            SET d.status = 'rejected'
            RETURN d.id as id
            """,
            {"id": report_id},
        )
        return bool(result)

    async def list_drift_reports(
        self,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[DriftReport]:
        """Retrieve drift reports from Neo4j, optionally filtered by status."""
        where = "WHERE d.status = $status" if status else ""
        params: dict = {"limit": limit}
        if status:
            params["status"] = status

        rows = await self.store.execute_query(
            f"""
            MATCH (d:DriftReport)
            {where}
            RETURN d.id as id, d.detected_at as detected_at,
                   d.new_entity_types as new_entity_types,
                   d.new_relationship_types as new_relationship_types,
                   d.removed_entity_types as removed_entity_types,
                   d.removed_relationship_types as removed_relationship_types,
                   d.sample_size as sample_size,
                   d.drift_score as drift_score,
                   d.status as status,
                   d.approved_by as approved_by,
                   d.approved_at as approved_at
            ORDER BY d.detected_at DESC
            LIMIT $limit
            """,
            params,
        )
        return [self._row_to_report(r) for r in rows]

    async def get_drift_report(self, report_id: str) -> Optional[DriftReport]:
        """Fetch a single drift report by ID."""
        return await self._load_drift_report(report_id)

    # ── Internal ────────────────────────────────────────────────────────────

    async def _get_random_chunks(self, limit: int):
        """Pull random chunk texts from Neo4j for re-sampling."""
        from ..core.models import Chunk

        rows = await self.store.execute_query(
            """
            MATCH (c:Chunk)
            RETURN c.text as text, c.id as id, c.document_id as doc_id
            ORDER BY rand()
            LIMIT $limit
            """,
            {"limit": limit},
        )
        chunks = []
        for i, r in enumerate(rows):
            chunks.append(
                Chunk(
                    id=r.get("id", str(uuid.uuid4())),
                    text=r.get("text", ""),
                    document_id=r.get("doc_id", "sampled"),
                    chunk_index=i,
                )
            )
        return chunks

    async def _compute_diff(
        self,
        current: OntologySchema,
        proposed: OntologySchema,
        sample_size: int,
    ) -> DriftReport:
        import difflib

        current_e = set(current.entity_types)
        current_r = set(current.relationship_types)
        proposed_e = set(proposed.entity_types)
        proposed_r = set(proposed.relationship_types)

        # Fuzzy match function to detect pure semantic overlaps
        def get_unmatched(source_set, target_set, threshold=0.8):
            unmatched = set(source_set)
            for s_item in source_set:
                for t_item in target_set:
                    # Check semantic string similarity
                    ratio = difflib.SequenceMatcher(None, s_item.lower(), t_item.lower()).ratio()
                    if ratio >= threshold:
                        if s_item in unmatched:
                            unmatched.remove(s_item)
                        break
            return list(unmatched)

        # Use fuzzy matching instead of strict exact set difference
        new_e = get_unmatched(proposed_e, current_e)
        new_r = get_unmatched(proposed_r, current_r)
        
        # Check what we truly removed (it's not in the new proposed set)
        removed_e = get_unmatched(current_e, proposed_e)
        removed_r = get_unmatched(current_r, proposed_r)

        # 1 point for minor fuzzy changes, but use LLM semantic metric ideally
        # Weighted drift formula that is not diluted completely by large ontology sizes:
        # A new concept should always represent a tangible static drift.
        drift_raw_score = (len(new_e) * 1.0) + (len(new_r) * 1.5) + (len(removed_e) * 0.5)
        # Bounded log-like scale (so score represents an absolute conceptual drift, maxing at 1.0)
        import math
        drift_score = min(1.0, round(float(math.log1p(drift_raw_score) / 4.0), 2))

        return DriftReport(
            new_entity_types=new_e,
            new_relationship_types=new_r,
            removed_entity_types=removed_e,
            removed_relationship_types=removed_r,
            sample_size=sample_size,
            drift_score=drift_score,
            status="pending",
        )

    async def _save_drift_report(self, report: DriftReport) -> None:
        await self.store.execute_query(
            """
            CREATE (d:DriftReport {
                id: $id,
                detected_at: $detected_at,
                new_entity_types: $new_entity_types,
                new_relationship_types: $new_relationship_types,
                removed_entity_types: $removed_entity_types,
                removed_relationship_types: $removed_relationship_types,
                sample_size: $sample_size,
                drift_score: $drift_score,
                status: $status
            })
            """,
            {
                "id": report.id,
                "detected_at": report.detected_at.isoformat(),
                "new_entity_types": report.new_entity_types,
                "new_relationship_types": report.new_relationship_types,
                "removed_entity_types": report.removed_entity_types,
                "removed_relationship_types": report.removed_relationship_types,
                "sample_size": report.sample_size,
                "drift_score": report.drift_score,
                "status": report.status,
            },
        )

    async def _load_drift_report(self, report_id: str) -> Optional[DriftReport]:
        rows = await self.store.execute_query(
            """
            MATCH (d:DriftReport {id: $id})
            RETURN d.id as id, d.detected_at as detected_at,
                   d.new_entity_types as new_entity_types,
                   d.new_relationship_types as new_relationship_types,
                   d.removed_entity_types as removed_entity_types,
                   d.removed_relationship_types as removed_relationship_types,
                   d.sample_size as sample_size,
                   d.drift_score as drift_score,
                   d.status as status,
                   d.approved_by as approved_by,
                   d.approved_at as approved_at
            """,
            {"id": report_id},
        )
        if not rows:
            return None
        return self._row_to_report(rows[0])

    @staticmethod
    def _row_to_report(r: dict) -> DriftReport:
        detected_at = r.get("detected_at")
        if isinstance(detected_at, str):
            try:
                detected_at = datetime.fromisoformat(detected_at)
            except Exception:
                detected_at = datetime.now(timezone.utc).replace(tzinfo=None)

        approved_at = r.get("approved_at")
        if isinstance(approved_at, str):
            try:
                approved_at = datetime.fromisoformat(approved_at)
            except Exception:
                approved_at = None

        return DriftReport(
            id=r.get("id", str(uuid.uuid4())),
            detected_at=detected_at or datetime.now(timezone.utc).replace(tzinfo=None),
            new_entity_types=r.get("new_entity_types") or [],
            new_relationship_types=r.get("new_relationship_types") or [],
            removed_entity_types=r.get("removed_entity_types") or [],
            removed_relationship_types=r.get("removed_relationship_types") or [],
            sample_size=r.get("sample_size") or 0,
            drift_score=r.get("drift_score") or 0.0,
            status=r.get("status") or "pending",
            approved_by=r.get("approved_by"),
            approved_at=approved_at,
        )

    @staticmethod
    def _bump_version(version: str, drift_score: float) -> str:
        """Increment the semantic version based on drift score."""
        try:
            prefix, nums = version.split("v", 1)
            parts = nums.split(".")
            
            # Make sure it corresponds to MAJOR.MINOR.PATCH
            while len(parts) < 3:
                parts.append("0")
                
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
            
            # Use semantic thresholds to decide version jump
            if drift_score >= 0.7:  # Severe semantic shift
                major += 1
                minor = 0
                patch = 0
            elif drift_score >= 0.3:  # Notible structural additions
                minor += 1
                patch = 0
            else:  # Minor patches
                patch += 1
                
            return f"v{major}.{minor}.{patch}"
        except Exception:
            return version + ".1"
