"""
Entity and relationship extraction from text
Uses LLM with structured output and ontology constraints
"""

from typing import List, Dict, Any, Optional
import json
import asyncio

from ..core.models import Entity, Relationship, Chunk, ExtractionResult, OntologySchema
from ..core.llm_factory import LLMFactory
from ..core.entity_resolver import SemanticEntityResolver
from ..config import settings


class KnowledgeExtractor:
    """
    Extract entities and relationships from text chunks
    Includes hallucination guards and ontology validators
    """
    
    def __init__(
        self,
        llm_provider: Optional[str] = None,
        ontology: Optional[OntologySchema] = None
    ):
        self.llm = LLMFactory.create(provider=llm_provider)
        self.ontology = ontology
        self.resolver = SemanticEntityResolver(self.llm)
    
    async def extract_from_chunk(
        self,
        chunk: Chunk,
        ontology: Optional[OntologySchema] = None
    ) -> ExtractionResult:
        """
        Extract entities and relationships from a single chunk
        
        Args:
            chunk: Text chunk to process
            ontology: Ontology schema to use
            
        Returns:
            Extraction result with entities and relationships
        """
        
        import time
        start_time = time.time()
        
        ontology = ontology or self.ontology
        if not ontology:
            raise ValueError("No ontology schema provided")
        
        # Create extraction prompt
        prompt = self._create_extraction_prompt(chunk.text, ontology)
        
        system_prompt = """You are a precise knowledge extraction system.
Extract only information that is explicitly stated in the text.
Do not infer or hallucinate information.
Use only the entity types and relationship types provided in the ontology."""
        
        # Get extraction from LLM
        response = await self.llm.complete(
            prompt,
            system_prompt=system_prompt,
            temperature=0.1
        )
        
        # Parse extraction
        entities, relationships = self._parse_extraction(response, ontology)
        
        # Add chunk reference
        chunk_copy = chunk.model_copy()
        
        processing_time = time.time() - start_time
        
        return ExtractionResult(
            entities=entities,
            relationships=relationships,
            chunks=[chunk_copy],
            ontology_version=ontology.version,
            processing_time_seconds=processing_time
        )
    
    async def extract_from_chunks(
        self,
        chunks: List[Chunk],
        ontology: Optional[OntologySchema] = None,
        resolve_entities: bool = True
    ) -> ExtractionResult:
        """
        Extract from multiple chunks with entity resolution
        
        Args:
            chunks: List of chunks to process
            ontology: Ontology schema
            resolve_entities: Whether to resolve duplicate entities
            
        Returns:
            Combined extraction result
        """
        
        import time
        start_time = time.time()
        
        # Process chunks in parallel (with rate limiting)
        semaphore = asyncio.Semaphore(settings.max_concurrent_extractions)
        
        async def process_chunk(chunk: Chunk):
            async with semaphore:
                return await self.extract_from_chunk(chunk, ontology)
        
        results = await asyncio.gather(
            *[process_chunk(chunk) for chunk in chunks],
            return_exceptions=True
        )
        
        # Combine results
        all_entities = []
        all_relationships = []
        
        for result in results:
            if isinstance(result, Exception):
                print(f"Extraction error: {result}")
                continue
            all_entities.extend(result.entities)
            all_relationships.extend(result.relationships)
        
        # Resolve entities if requested
        if resolve_entities and all_entities:
            resolved = await self.resolver.resolve(all_entities)
            
            # Update entities - keep canonical versions
            entity_map = {}  # Maps old name to canonical entity
            final_entities = []
            
            for canonical_id, duplicates in resolved.items():
                # Find canonical entity
                canonical = next((e for e in all_entities if e.id == canonical_id), None)
                if canonical:
                    final_entities.append(canonical)
                    entity_map[canonical.name] = canonical.name
                    for dup in duplicates:
                        entity_map[dup.name] = canonical.name
            
            # Add non-duplicate entities
            resolved_ids = set()
            for entities in resolved.values():
                resolved_ids.update([e.id for e in entities])
            resolved_ids.update(resolved.keys())
            
            for entity in all_entities:
                if entity.id not in resolved_ids:
                    final_entities.append(entity)
                    entity_map[entity.name] = entity.name
            
            # Update relationships to use canonical names
            final_relationships = []
            for rel in all_relationships:
                updated_rel = rel.model_copy()
                updated_rel.source = entity_map.get(rel.source, rel.source)
                updated_rel.target = entity_map.get(rel.target, rel.target)
                final_relationships.append(updated_rel)
        else:
            final_entities = all_entities
            final_relationships = all_relationships
        
        processing_time = time.time() - start_time
        
        return ExtractionResult(
            entities=final_entities,
            relationships=final_relationships,
            chunks=chunks,
            ontology_version=ontology.version if ontology else "v1.0",
            processing_time_seconds=processing_time
        )
    
    def _create_extraction_prompt(
        self,
        text: str,
        ontology: OntologySchema
    ) -> str:
        """Create extraction prompt with ontology constraints"""
        
        prompt = f"""
Extract entities and relationships from the following text according to the ontology.

Ontology:
Entity Types: {', '.join(ontology.entity_types)}
Relationship Types: {', '.join(ontology.relationship_types)}

Text:
{text}

Extract all entities and relationships. Return as JSON:
{{
    "entities": [
        {{"name": "entity name", "type": "EntityType", "properties": {{"key": "value"}}}},
        ...
    ],
    "relationships": [
        {{"source": "entity1 name", "target": "entity2 name", "type": "RELATIONSHIP_TYPE"}},
        ...
    ]
}}

Rules:
- Only use entity types and relationship types from the ontology
- Extract only explicitly mentioned information
- Entity names should be normalized (e.g., "Apple Inc." not "Apple")
- Source and target in relationships must match entity names exactly
"""
        
        return prompt
    
    def _parse_extraction(
        self,
        response: str,
        ontology: OntologySchema
    ) -> tuple[List[Entity], List[Relationship]]:
        """Parse and validate extraction response"""
        
        try:
            # Clean response
            cleaned = response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0]
            cleaned = cleaned.strip()
            
            data = json.loads(cleaned)
            
            # Parse entities
            entities = []
            for e in data.get("entities", []):
                # Validate entity type
                if e.get("type") not in ontology.entity_types:
                    continue
                
                entity = Entity(
                    name=e.get("name", ""),
                    type=e.get("type", "Entity"),
                    properties=e.get("properties", {}),
                    ontology_version=ontology.version,
                    confidence=e.get("confidence", 0.9)
                )
                entities.append(entity)
            
            # Parse relationships
            relationships = []
            for r in data.get("relationships", []):
                # Validate relationship type
                if r.get("type") not in ontology.relationship_types:
                    continue
                
                relationship = Relationship(
                    source=r.get("source", ""),
                    target=r.get("target", ""),
                    type=r.get("type", "RELATED_TO"),
                    properties=r.get("properties", {}),
                    ontology_version=ontology.version,
                    confidence=r.get("confidence", 0.9)
                )
                relationships.append(relationship)
            
            return entities, relationships
            
        except Exception as e:
            print(f"Failed to parse extraction: {e}")
            return [], []
    
    async def generate_embeddings(
        self,
        chunks: List[Chunk]
    ) -> List[Chunk]:
        """
        Generate embeddings for chunks
        
        Args:
            chunks: Chunks to embed
            
        Returns:
            Chunks with embeddings
        """
        
        texts = [chunk.text for chunk in chunks]
        embeddings = await self.llm.embed_batch(texts)
        
        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding
        
        return chunks
