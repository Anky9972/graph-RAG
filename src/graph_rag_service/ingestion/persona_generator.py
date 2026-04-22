"""
MiroFish Point #2: The Ontology-to-Persona Pipeline
Takes generic entities from the Neo4j Graph (like 'Person' or 'Organization')
and uses local LLMs to generate deep psychological, demographic, and background profiles,
saving them back as 'Persona' extensions in the graph.
"""

from typing import List, Dict, Any
from pydantic import BaseModel, Field
import json

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider


class PersonaProfile(BaseModel):
    psychological_trait: str = Field(description="Primary psychological trait (e.g., 'Risk Taker', 'Paranoid')")
    background_summary: str = Field(description="A 2-sentence summary of the agent's background based on the graph.")
    communication_style: str = Field(description="How this entity communicates (e.g., 'Aggressive', 'Academic')")
    goals: List[str] = Field(description="List of 2-3 primary goals or motives for this entity.")


class PersonaGenerator:
    """
    Converts inert graph nodes into living Agent Personas.
    Runs locally against the selected LLM provider (Ollama by default).
    """
    
    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider):
        self.store = store
        self.llm = llm

    async def generate_personas_for_type(self, entity_type: str = "Person") -> int:
        """
        Finds all entities of a certain type that lack a persona,
        generates the persona, and updates the graph.
        """
        # Get entities without a persona profile
        query = f"""
        MATCH (e:Entity {{type: '{entity_type}'}})
        WHERE e.persona Is NULL
        RETURN e.id AS id, e.name AS name, e.properties AS properties
        """
        entities = await self.store.execute_query(query)
        count = 0
        
        for record in entities:
            # Build the context prompt
            prompt = (
                f"You are a psychological profile generator for an AI simulation sandbox.\n"
                f"Analyze the following entity and generate a deep simulation persona:\n"
                f"Name: {record['name']}\n"
                f"Properties: {record['properties']}\n\n"
                f"Deduce their psychological traits, background, communication style, and goals."
            )
            
            try:
                # Generate structured profile
                profile: PersonaProfile = await self.llm.complete_structured(
                    prompt=prompt,
                    response_model=PersonaProfile,
                    system_prompt="You are an expert behavioural analyst producing strict JSON profiles."
                )
                
                # Update the Neo4j Node with Persona data
                update_query = """
                MATCH (e:Entity {id: $id})
                SET e.persona = $persona_data, e.is_agent = true
                RETURN e.id
                """
                await self.store.execute_query(
                    update_query, 
                    params={"id": record['id'], "persona_data": profile.model_dump_json()}
                )
                count += 1
            except Exception as e:
                print(f"Failed to generate persona for {record['name']}: {e}")
                
        return count
