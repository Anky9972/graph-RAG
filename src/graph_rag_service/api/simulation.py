from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from pydantic import BaseModel

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider

router = APIRouter(prefix="/api/v1/simulation", tags=["Simulation Interaction"])

def get_global_store():
    # Lazy import to avoid circular dependency with server.py
    from .server import graph_store
    if graph_store is None:
        raise HTTPException(status_code=500, detail="Neo4j connection not initialized.")
    return graph_store

def get_global_llm():
    return UnifiedLLMProvider()

class InterviewRequest(BaseModel):
    agent_id: str
    user_query: str


@router.post("/interview", response_model=Dict[str, Any])
async def live_interview_agent(
    request: InterviewRequest,
    store: Neo4jStore = Depends(get_global_store),
    llm: UnifiedLLMProvider = Depends(get_global_llm)
):
    """
    MiroFish Point 5: 'Live Interviews' with Simulated Personas.
    Allows users to chat with a graph entity in character, 
    injecting their exact Neo4j memory into the system prompt.
    """
    # 1. Fetch Agent Persona
    query_agent = """
    MATCH (a:Entity {id: $agent_id})
    RETURN a.name as name, a.persona as persona
    """
    results = await store.execute_query(query_agent, {"agent_id": request.agent_id})
    if not results:
        raise HTTPException(status_code=404, detail="Agent persona not found.")
        
    agent = results[0]
    
    # 2. Fetch Agent's 'Memory' (Recent relationships and properties)
    query_memory = """
    MATCH (a:Entity {id: $agent_id})-[r]->(t:Entity)
    WITH t.name as target, type(r) as relation, coalesce(r.content, r.properties) as details, r.valid_from as timestamp
    ORDER BY timestamp DESC
    LIMIT 5
    RETURN relation, target, details
    """
    memories = await store.execute_query(query_memory, {"agent_id": request.agent_id})
    
    memory_string = "Your recent memories/actions in the simulation sandbox:\n"
    for m in memories:
        memory_string += f"- You {m['relation']} ({m['target']}): {m['details']}\n"

    # 3. Construct System Persona Prompt
    system_prompt = (
        f"You are engaging in a live roleplay interview.\n"
        f"Your Name: {agent['name']}\n"
        f"Your Psychological Profile & Background:\n{agent['persona']}\n\n"
        f"{memory_string if memories else 'You have no recent memories recorded.'}\n\n"
        f"Answer the user's question completely in character based ONLY on your profile and memories."
    )
    
    # 4. Send to Local LLM
    try:
        response_text = await llm.complete(
            prompt=request.user_query,
            system_prompt=system_prompt,
            temperature=0.8  # slightly higher for creative roleplay
        )
        return {
            "agent_id": request.agent_id,
            "agent_name": agent['name'],
            "response": response_text
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM Interaction Failed: {str(e)}")


from ..retrieval.report_agent import ReportAgent

@router.get('/report', response_model=Dict[str, Any])
async def get_sandbox_report(
    store: Neo4jStore = Depends(get_global_store),
    llm: UnifiedLLMProvider = Depends(get_global_llm)
):
    '''
    MiroFish Point 3: Dedicated ReAct Reporting Agent & Tooling.
    Triggers the analytical engine to build a report off the recent sandbox events.
    '''
    try:
        agent = ReportAgent(store, llm)
        report = await agent.generate_sandbox_report()
        return report.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Report generation failed: {str(e)}')


from ..workers.celery_worker import celery_app

@router.post('/generate_personas')
async def start_persona_generation():
    '''Trigger background Celery task to generate personas.'''
    task = celery_app.send_task('generate_personas')
    return {'status': 'accepted', 'task_id': task.id}

@router.post('/tick')
async def start_simulation_tick():
    '''Trigger background Celery task to run a simulation loop tick.'''
    task = celery_app.send_task('run_simulation_tick')
    return {'status': 'accepted', 'task_id': task.id}

