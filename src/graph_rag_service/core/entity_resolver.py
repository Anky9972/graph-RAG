"""
Entity resolution and deduplication
Uses multi-stage blocking and semantic similarity
"""

import asyncio
from typing import List, Dict, Any
from difflib import SequenceMatcher
import numpy as np

from .abstractions import EntityResolver, LLMProvider
from .models import Entity
from ..config import settings


class SemanticEntityResolver(EntityResolver):
    """
    Production-grade entity resolution with:
    1. Blocking by label and phonetic similarity
    2. Semantic embedding comparison
    3. Configurable threshold matching
    """
    
    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider
        self.embedding_cache: Dict[str, List[float]] = {}
    
    async def resolve(
        self,
        entities: List[Entity],
        threshold: float = None
    ) -> Dict[str, List[Entity]]:
        """
        Resolve and deduplicate entities
        
        Returns:
            Dictionary mapping canonical entity ID to list of duplicates
        """
        threshold = threshold or settings.entity_resolution_threshold
        
        # Group by entity type for blocking
        type_groups = {}
        for entity in entities:
            if entity.type not in type_groups:
                type_groups[entity.type] = []
            type_groups[entity.type].append(entity)
        
        # Resolve within each type group
        resolved = {}
        for entity_type, group in type_groups.items():
            if len(group) <= 1:
                continue
            
            # Find duplicates
            duplicates = await self._find_duplicates(group, threshold)
            resolved.update(duplicates)
        
        return resolved
    
    async def _find_duplicates(
        self,
        entities: List[Entity],
        threshold: float
    ) -> Dict[str, List[Entity]]:
        """Find duplicate entities within a group"""
        
        duplicates = {}
        processed = set()
        
        for i, entity1 in enumerate(entities):
            if entity1.id in processed:
                continue
            
            matches = [entity1]
            
            for j, entity2 in enumerate(entities[i+1:], start=i+1):
                if entity2.id in processed:
                    continue
                
                # Quick name similarity check
                name_sim = self._string_similarity(entity1.name, entity2.name)
                if name_sim < 0.7:  # Fast reject
                    continue
                
                # Semantic similarity check
                similarity = await self.compute_similarity(entity1, entity2)
                
                if similarity >= threshold:
                    matches.append(entity2)
                    processed.add(entity2.id)
            
            if len(matches) > 1:
                # First entity is canonical
                canonical_id = entity1.id
                duplicates[canonical_id] = matches[1:]
                processed.add(canonical_id)
        
        return duplicates
    
    async def compute_similarity(self, entity1: Entity, entity2: Entity) -> float:
        """
        Compute similarity between two entities
        
        Combines:
        - Name similarity (string matching)
        - Property overlap
        - Embedding similarity (semantic)
        """
        
        # Name similarity (30% weight)
        name_sim = self._string_similarity(entity1.name, entity2.name)
        
        # Property overlap (20% weight)
        prop_sim = self._property_similarity(entity1.properties, entity2.properties)
        
        # Embedding similarity (50% weight)
        embed_sim = await self._embedding_similarity(entity1, entity2)
        
        # Weighted combination
        total_sim = (0.3 * name_sim) + (0.2 * prop_sim) + (0.5 * embed_sim)
        
        return total_sim
    
    def _string_similarity(self, s1: str, s2: str) -> float:
        """Compute string similarity using SequenceMatcher"""
        return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()
    
    def _property_similarity(self, props1: Dict, props2: Dict) -> float:
        """Compute property overlap similarity"""
        if not props1 or not props2:
            return 0.0
        
        keys1 = set(props1.keys())
        keys2 = set(props2.keys())
        
        if not keys1 or not keys2:
            return 0.0
        
        # Jaccard similarity of property keys
        intersection = len(keys1.intersection(keys2))
        union = len(keys1.union(keys2))
        
        if union == 0:
            return 0.0
        
        key_sim = intersection / union
        
        # Value similarity for common keys
        common_keys = keys1.intersection(keys2)
        value_matches = 0
        
        for key in common_keys:
            v1 = str(props1[key]).lower()
            v2 = str(props2[key]).lower()
            if v1 == v2:
                value_matches += 1
        
        value_sim = value_matches / len(common_keys) if common_keys else 0.0
        
        # Combine key and value similarity
        return (key_sim + value_sim) / 2
    
    async def _embedding_similarity(self, entity1: Entity, entity2: Entity) -> float:
        """Compute cosine similarity between entity embeddings"""
        
        # Get or compute embeddings
        emb1 = await self._get_entity_embedding(entity1)
        emb2 = await self._get_entity_embedding(entity2)
        
        # Cosine similarity
        dot_product = np.dot(emb1, emb2)
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        similarity = dot_product / (norm1 * norm2)
        
        # Normalize to 0-1 range
        return (similarity + 1) / 2
    
    async def _get_entity_embedding(self, entity: Entity) -> List[float]:
        """Get or compute entity embedding with caching"""
        
        cache_key = f"{entity.name}:{entity.type}"
        
        if cache_key in self.embedding_cache:
            return self.embedding_cache[cache_key]
        
        # Create text representation of entity
        text = f"{entity.type}: {entity.name}"
        if entity.properties:
            prop_text = ", ".join([f"{k}={v}" for k, v in entity.properties.items()])
            text += f" ({prop_text})"
        
        # Compute embedding
        embedding = await self.llm.embed(text)
        
        # Cache it
        self.embedding_cache[cache_key] = embedding
        
        return embedding
