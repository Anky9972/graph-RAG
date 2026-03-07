"""
Ontology generation and evolution
LLM-powered automatic ontology discovery with versioning
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import json

from ..core.models import OntologySchema, Chunk
from ..core.llm_factory import LLMFactory
from ..config import settings


class OntologyGenerator:
    """
    Generate and refine ontologies from documents
    Supports versioning and evolution
    """
    
    def __init__(self, llm_provider: Optional[str] = None):
        self.llm = LLMFactory.create(provider=llm_provider)
        self.current_schema: Optional[OntologySchema] = None
    
    async def generate_initial_ontology(
        self,
        sample_chunks: List[Chunk],
        domain: Optional[str] = None
    ) -> OntologySchema:
        """
        Generate initial ontology from sample chunks
        
        Args:
            sample_chunks: Sample chunks to analyze
            domain: Optional domain hint (e.g., "healthcare", "finance")
            
        Returns:
            Proposed ontology schema
        """
        
        # Combine sample chunks
        sample_text = "\n\n".join([chunk.text for chunk in sample_chunks[:10]])
        
        # Create prompt for ontology generation
        prompt = f"""
Analyze the following text and identify:
1. Key entity types (e.g., Person, Organization, Location, Concept)
2. Relationship types that connect these entities (e.g., WORKS_FOR, LOCATED_IN, RELATED_TO)
3. Important properties for each entity type

Text:
{sample_text}

{f"Domain: {domain}" if domain else ""}

Provide a comprehensive ontology that captures the semantic structure of this domain.
Return your response as a JSON object with this structure:
{{
    "entity_types": ["EntityType1", "EntityType2", ...],
    "relationship_types": ["RELATIONSHIP_TYPE_1", "RELATIONSHIP_TYPE_2", ...],
    "properties": {{
        "EntityType1": ["property1", "property2"],
        "EntityType2": ["property1", "property2"]
    }}
}}
"""
        
        system_prompt = """You are an expert knowledge engineer specializing in ontology design.
Your task is to identify entity types, relationships, and properties that best represent the domain.
Focus on:
- Common, reusable entity types
- Clear, semantic relationship names (use UPPERCASE_WITH_UNDERSCORES)
- Relevant properties that add value
Keep it simple but comprehensive."""
        
        response = await self.llm.complete(prompt, system_prompt=system_prompt, temperature=0.3)
        
        # Parse response
        try:
            # Clean JSON from response
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            ontology_data = json.loads(cleaned)
            
            schema = OntologySchema(
                version="v1.0",
                entity_types=ontology_data.get("entity_types", []),
                relationship_types=ontology_data.get("relationship_types", []),
                properties=ontology_data.get("properties", {}),
                created_at=datetime.utcnow(),
                approved=False
            )
            
            self.current_schema = schema
            return schema
            
        except Exception as e:
            # Fallback to basic ontology
            return OntologySchema(
                version="v1.0",
                entity_types=["Entity", "Concept", "Person", "Organization"],
                relationship_types=["RELATED_TO", "MENTIONS", "PART_OF"],
                properties={},
                created_at=datetime.utcnow(),
                approved=False
            )
    
    async def refine_ontology(
        self,
        current_schema: OntologySchema,
        new_chunks: List[Chunk],
        feedback: Optional[str] = None
    ) -> OntologySchema:
        """
        Refine ontology based on new data or human feedback
        
        Args:
            current_schema: Current ontology schema
            new_chunks: New chunks that might suggest schema evolution
            feedback: Optional human feedback for refinement
            
        Returns:
            Refined ontology schema with incremented version
        """
        
        sample_text = "\n\n".join([chunk.text for chunk in new_chunks[:5]])
        
        prompt = f"""
Current Ontology:
- Entity Types: {', '.join(current_schema.entity_types)}
- Relationship Types: {', '.join(current_schema.relationship_types)}

New Text Sample:
{sample_text}

{f"Human Feedback: {feedback}" if feedback else ""}

Review the current ontology and the new text. Suggest refinements:
1. New entity types to add (if any)
2. New relationship types to add (if any)
3. Properties to add or modify
4. Deprecated items to remove (if any)

Return a JSON object with the refined ontology:
{{
    "entity_types": [...],
    "relationship_types": [...],
    "properties": {{}},
    "changes": "Brief description of what changed"
}}
"""
        
        system_prompt = """You are refining an existing ontology.
Be conservative - only suggest changes that are clearly beneficial.
Maintain backward compatibility when possible."""
        
        response = await self.llm.complete(prompt, system_prompt=system_prompt, temperature=0.2)
        
        try:
            cleaned = response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0]
            cleaned = cleaned.strip()
            
            refined_data = json.loads(cleaned)
            
            # Increment version
            version_number = float(current_schema.version.replace('v', ''))
            new_version = f"v{version_number + 0.1:.1f}"
            
            refined_schema = OntologySchema(
                version=new_version,
                entity_types=refined_data.get("entity_types", current_schema.entity_types),
                relationship_types=refined_data.get("relationship_types", current_schema.relationship_types),
                properties=refined_data.get("properties", current_schema.properties),
                created_at=datetime.utcnow(),
                approved=False
            )
            
            return refined_schema
            
        except Exception as e:
            # Return current schema if refinement fails
            return current_schema
    
    def get_extraction_prompt(
        self,
        text: str,
        schema: Optional[OntologySchema] = None
    ) -> str:
        """
        Generate extraction prompt based on ontology schema
        
        Args:
            text: Text to extract from
            schema: Ontology schema to use (uses current if None)
            
        Returns:
            Formatted extraction prompt
        """
        
        schema = schema or self.current_schema
        if not schema:
            raise ValueError("No ontology schema available")
        
        prompt = f"""
Extract entities and relationships from the following text based on the ontology.

Ontology:
- Entity Types: {', '.join(schema.entity_types)}
- Relationship Types: {', '.join(schema.relationship_types)}

Text:
{text}

Extract:
1. All entities with their type and properties
2. All relationships between entities

Return as JSON:
{{
    "entities": [
        {{"name": "...", "type": "...", "properties": {{}}}},
        ...
    ],
    "relationships": [
        {{"source": "...", "target": "...", "type": "..."}},
        ...
    ]
}}

Only use entity types and relationship types from the ontology.
Be precise and only extract explicitly mentioned information.
"""
        
        return prompt
