"""
MiroFish-inspired services layer
- GraphMemoryUpdater: Writable live graph from text snippets
- EntityEnricher: Entity profile summaries via graph neighborhood traversal
- OntologyDriftDetector: Periodic schema drift detection
"""

from .graph_memory_updater import GraphMemoryUpdater, GraphUpdateResult
from .entity_enricher import EntityEnricher, EnrichmentResult
from .ontology_drift_detector import OntologyDriftDetector, DriftReport

__all__ = [
    "GraphMemoryUpdater",
    "GraphUpdateResult",
    "EntityEnricher",
    "EnrichmentResult",
    "OntologyDriftDetector",
    "DriftReport",
]
