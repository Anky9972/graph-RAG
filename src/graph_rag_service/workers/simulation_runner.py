"""
MiroFish Point 4: Continuous Multi-Agent Sandbox (Parallel Execution)
MiroFish Point 1: Dynamic Graph Evolution (Living Knowledge Graph)

Uses Celery for parallel execution to simulate agents interacting. 
Every action taken by the LLM is pushed immediately as a temporal edge back into Neo4j.
"""

from typing import List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
import asyncio

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider


class AgentAction(BaseModel):
    action_type: str = Field(description="The generic action type (e.g., 'DEBATED_WITH', 'AGREED_WITH', 'MENTIONED')")
    target_id: str = Field(description="The ID of the target agent to interact with.")
    content: str = Field(description="The textual interaction content (e.g., tweet or dialogue).")
    confidence: float = Field(description="0.0 to 1.0 confidence in taking this action.")


class SimulationManager:
    """Manages parallel multi-agent loops and pushes real-time actions to Neo4j."""

    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider):
        self.store = store
        self.llm = llm

    async def get_active_agents(self, limit: int = 20) -> List[Dict]:
        """Fetch agents with generated personas (from Point 2 PersonaGenerator)"""
        query = """
        MATCH (a:Entity {is_agent: true})
        WHERE a.persona IS NOT NULL
        RETURN a.id as id, a.name as name, a.persona as persona
        LIMIT $limit
        """
        return await self.store.execute_query(query, {"limit": limit})

    async def run_simulation_tick(self) -> int:
        """
        Runs one tick of the sandbox simulation:
        1. Selects active agents
        2. Retrieves their current graph environment ('memory')
        3. Uses the LLM to decide on an action
        4. Writes the action and content as a Temporal Edge into Neo4j
        """
        agents = await self.get_active_agents()
        if len(agents) < 2:
            return 0  # Not enough agents

        actions_taken = 0
        tasks = [self._process_agent_turn(agent, agents) for agent in agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results:
            if res and not isinstance(res, Exception):
                actions_taken += 1
                
        return actions_taken

    async def _process_agent_turn(self, agent: Dict, all_agents: List[Dict]) -> bool:
        """Process a single agent's turn asynchronously."""
        # Exclude self from targets
        potential_targets = [a for a in all_agents if a['id'] != agent['id']]
        if not potential_targets:
            return False
            
        target_summaries = "\n".join([f"- ID: {t['id']} | Name: {t['name']} | Persona: {t['persona']}" for t in potential_targets])
        
        # Get recent memories/interactions of this agent
        memory_query = """
        MATCH (a:Entity {id: $agent_id})-[r]->(t:Entity)
        WHERE r.valid_from IS NOT NULL
        RETURN type(r) as action, t.name as target, r.content as content
        ORDER BY r.valid_from DESC LIMIT 3
        """
        recent_memories = await self.store.execute_query(memory_query, {"agent_id": agent['id']})
        memory_string = "\n".join([f"I {m['action']} {m['target']}: '{m['content']}'" for m in recent_memories])

        prompt = (
            f"You are the simulation engine roleplaying as: {agent['name']}\n"
            f"Your Persona Profile: {agent['persona']}\n\n"
            f"Your Recent Memory/Actions:\n{memory_string if recent_memories else 'No recent memories.'}\n\n"
            f"Available Targets to interact with:\n{target_summaries}\n\n"
            f"Decide on ONE action to take towards ONE target. Return valid JSON."
        )

        try:
            # LLM Engine decides the action (Ollama by default)
            action: AgentAction = await self.llm.complete_structured(
                prompt=prompt,
                response_model=AgentAction,
                system_prompt="You are a strict simulator. Simulate the given character and dictate their next textual interaction."
            )

            # --- POINT 1: Dynamic Graph Evolution ---
            # Save the action back into our Neo4j Knowledge Graph as a temporal event edge
            timestamp = datetime.utcnow().isoformat()
            cypher_action = action.action_type.replace(" ", "_").upper()
            
            update_query = f"""
            MATCH (source:Entity {{id: $source_id}})
            MATCH (target:Entity {{id: $target_id}})
            CREATE (source)-[r:{cypher_action} {{
                content: $content, 
                confidence: $confidence,
                valid_from: $timestamp,
                is_simulation_event: true,
                ingested_at: datetime()
            }}]->(target)
            RETURN r
            """
            await self.store.execute_query(
                update_query, 
                params={
                    "source_id": agent['id'],
                    "target_id": action.target_id,
                    "content": action.content,
                    "confidence": action.confidence,
                    "timestamp": timestamp
                }
            )
            return True
            
        except Exception as e:
            print(f"Simulation failed for {agent['name']}: {e}")
            return False
