"""
Agentic retrieval system with LangGraph orchestration
Dynamic tool selection with multi-step reasoning
"""

from typing import List, Dict, Any, Optional, AsyncGenerator
from typing_extensions import TypedDict
import asyncio
import time

from langgraph.graph import StateGraph, END

from .tools import VectorSearchTool, GraphTraversalTool, CypherGenerationTool, MetadataFilterTool
from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider
from ..core.models import QueryResult, OntologySchema
from ..config import settings


class AgentRetrievalSystem:
    """
    Agentic retrieval system that:
    1. Decomposes complex queries
    2. Routes to vector / graph / cypher / filter tools
    3. Synthesizes responses with reasoning chains
    4. Supports streaming via astream()
    """

    def __init__(
        self,
        graph_store: Neo4jStore,
        llm_provider: Optional[str] = None,
        ontology: Optional[OntologySchema] = None
    ):
        self.store = graph_store
        self.llm = UnifiedLLMProvider(provider=llm_provider)
        self.ontology = ontology

        self.vector_tool = VectorSearchTool(self.store, self.llm)
        self.graph_tool = GraphTraversalTool(self.store, self.llm)
        self.cypher_tool = CypherGenerationTool(self.store, self.llm, ontology)
        self.filter_tool = MetadataFilterTool(self.store)

        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build LangGraph workflow"""

        class State(TypedDict):
            query: str
            document_id: Optional[str]
            decomposed_queries: List[str]
            contexts: List[Dict[str, Any]]
            reasoning_steps: List[str]
            answer: Optional[str]
            iteration: int
            confidence: float
            tool_results: Dict[str, Any]
            routing_decision: str

        workflow = StateGraph(State)

        workflow.add_node("decompose", self._decompose_query)
        workflow.add_node("route", self._route_query)
        workflow.add_node("vector_search", self._vector_search)
        workflow.add_node("graph_traversal", self._graph_traversal)
        workflow.add_node("cypher_query", self._cypher_query)
        workflow.add_node("metadata_filter", self._metadata_filter)
        workflow.add_node("synthesize", self._synthesize_response)

        workflow.set_entry_point("decompose")
        workflow.add_edge("decompose", "route")
        workflow.add_conditional_edges(
            "route",
            self._should_continue,
            {
                "vector": "vector_search",
                "graph": "graph_traversal",
                "cypher": "cypher_query",
                "filter": "metadata_filter",
                "synthesize": "synthesize",
            }
        )
        workflow.add_edge("vector_search", "route")
        workflow.add_edge("graph_traversal", "route")
        workflow.add_edge("cypher_query", "route")
        workflow.add_edge("metadata_filter", "route")
        workflow.add_edge("synthesize", END)

        return workflow.compile()

    # ── Public API ────────────────────────────────────────────────────────────

    async def query(
        self,
        query: str,
        top_k: int = None,
        document_id: Optional[str] = None,
        streaming: bool = False,
    ) -> QueryResult:
        start_time = time.time()
        top_k = top_k or settings.default_top_k

        initial_state = self._make_initial_state(query, document_id)

        try:
            result = await asyncio.wait_for(
                self.graph.ainvoke(initial_state),
                timeout=settings.agent_timeout_seconds
            )
        except asyncio.TimeoutError:
            result = await self._fallback_search(query, top_k, document_id)

        processing_time = time.time() - start_time

        return QueryResult(
            answer=result.get("answer", "I couldn't find a satisfactory answer."),
            sources=result.get("contexts", []),
            reasoning_chain=result.get("reasoning_steps", []),
            confidence=result.get("confidence", 0.5),
            retrieval_method="agentic",
            processing_time_seconds=processing_time
        )

    async def astream(
        self,
        query: str,
        top_k: int = None,
        document_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream partial states after each graph node for SSE."""
        initial_state = self._make_initial_state(query, document_id)

        try:
            async for partial_state in self.graph.astream(initial_state):
                # astream yields {node_name: state_dict} for each completed node
                for node_name, state in partial_state.items():
                    yield state
        except asyncio.TimeoutError:
            result = await self._fallback_search(query, top_k or settings.default_top_k, document_id)
            yield result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_initial_state(self, query: str, document_id: Optional[str]) -> Dict[str, Any]:
        return {
            "query": query,
            "document_id": document_id,
            "decomposed_queries": [],
            "contexts": [],
            "reasoning_steps": [],
            "answer": None,
            "iteration": 0,
            "confidence": 0.0,
            "tool_results": {},
            "routing_decision": "vector",
        }

    # ── Graph nodes ───────────────────────────────────────────────────────────

    async def _decompose_query(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["query"]

        prompt = f"""
Analyze this query and break it down into simpler sub-queries if needed:

Query: "{query}"

Rules:
- If simple → return it as-is in a list
- If complex → decompose into 2-4 sub-queries

Return only a JSON list: ["sub-query 1", "sub-query 2", ...]
"""
        response = await self.llm.complete(prompt, temperature=0.2)

        try:
            import json
            cleaned = response.strip()
            for marker in ("```json", "```"):
                if marker in cleaned:
                    cleaned = cleaned.split(marker)[1].split("```")[0]
            sub_queries = json.loads(cleaned.strip())
            if not isinstance(sub_queries, list):
                sub_queries = [query]
        except Exception:
            sub_queries = [query]

        state["decomposed_queries"] = sub_queries
        state["reasoning_steps"].append(f"Decomposed into {len(sub_queries)} sub-queries")
        return state

    async def _route_query(self, state: Dict[str, Any]) -> Dict[str, Any]:
        iteration = state.get("iteration", 0)
        sub_queries = state.get("decomposed_queries", [])

        if iteration >= len(sub_queries) or iteration >= settings.max_agent_iterations:
            return state

        current_query = sub_queries[iteration]

        prompt = f"""
Choose the best retrieval method for this query:

Query: "{current_query}"

Methods:
- vector   : semantic similarity / general content questions
- graph    : relationship queries, "how are X and Y connected", "what does X know"
- cypher   : complex structured queries that need precise graph pattern matching
- filter   : attribute filtering (by date, type, document name, etc.)

Return ONLY one word: vector | graph | cypher | filter
"""
        response = await self.llm.complete(prompt, temperature=0.0)
        method = response.strip().lower().split()[0]

        if method not in ("vector", "graph", "cypher", "filter"):
            method = "vector"

        state["routing_decision"] = method
        state["reasoning_steps"].append(
            f"Sub-query {iteration + 1}: \"{current_query}\" → {method}"
        )
        return state

    def _should_continue(self, state: Dict[str, Any]) -> str:
        iteration = state.get("iteration", 0)
        sub_queries = state.get("decomposed_queries", [])

        if iteration >= len(sub_queries) or iteration >= settings.max_agent_iterations:
            return "synthesize"

        return state.get("routing_decision", "vector")

    async def _vector_search(self, state: Dict[str, Any]) -> Dict[str, Any]:
        iteration = state["iteration"]
        query = state["decomposed_queries"][iteration]
        document_id = state.get("document_id")

        filter_dict = {"document_id": document_id} if document_id else None
        results = await self.vector_tool.run(query, k=settings.default_top_k, filter=filter_dict)

        state["contexts"].extend(results)
        state["iteration"] += 1
        state["reasoning_steps"].append(f"Vector search: {len(results)} results")
        return state

    async def _graph_traversal(self, state: Dict[str, Any]) -> Dict[str, Any]:
        iteration = state["iteration"]
        query = state["decomposed_queries"][iteration]

        results = await self.graph_tool.run(query)

        state["contexts"].extend(results)
        state["iteration"] += 1
        state["reasoning_steps"].append(f"Graph traversal: {len(results)} results")
        return state

    async def _cypher_query(self, state: Dict[str, Any]) -> Dict[str, Any]:
        iteration = state["iteration"]
        query = state["decomposed_queries"][iteration]

        results = await self.cypher_tool.run(query)

        state["contexts"].extend(results)
        state["iteration"] += 1
        state["reasoning_steps"].append(f"Cypher query: {len(results)} results")
        return state

    async def _metadata_filter(self, state: Dict[str, Any]) -> Dict[str, Any]:
        iteration = state["iteration"]
        query = state["decomposed_queries"][iteration]
        document_id = state.get("document_id")

        # Extract filter conditions from query with LLM
        prompt = f"""
Extract metadata filter conditions from this query as a JSON object.
Supported keys: document_id, file_type, chunk_index.

Query: "{query}"
{f'Known document_id: "{document_id}"' if document_id else ""}

Return only JSON: {{"key": "value", ...}}
If no filters are extractable, return {{}}
"""
        response = await self.llm.complete(prompt, temperature=0.0)
        try:
            import json as _json
            cleaned = response.strip()
            for marker in ("```json", "```"):
                if marker in cleaned:
                    cleaned = cleaned.split(marker)[1].split("```")[0]
            filters = _json.loads(cleaned.strip())
        except Exception:
            filters = {}

        if document_id and "document_id" not in filters:
            filters["document_id"] = document_id

        results = await self.filter_tool.run(filters) if filters else []

        state["contexts"].extend(results)
        state["iteration"] += 1
        state["reasoning_steps"].append(f"Metadata filter {filters}: {len(results)} results")
        return state

    async def _synthesize_response(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["query"]
        contexts = state["contexts"]

        if not contexts:
            state["answer"] = "I couldn't find relevant information to answer your question."
            state["confidence"] = 0.0
            return state

        context_text = "\n\n".join([
            f"Context {i + 1}:\n{self._format_context(ctx)}"
            for i, ctx in enumerate(contexts[:10])
        ])

        prompt = f"""Answer the question based on the retrieved contexts.

Question: {query}

Contexts:
{context_text}

Provide a comprehensive, accurate answer. Cite which contexts you used."""

        answer = await self.llm.complete(
            prompt,
            system_prompt="You answer questions from retrieved context accurately and concisely.",
            temperature=0.3
        )

        state["answer"] = answer
        state["confidence"] = min(1.0, len(contexts) / max(settings.default_top_k, 1))
        state["reasoning_steps"].append("Synthesized final answer")
        return state

    def _format_context(self, context: Dict[str, Any]) -> str:
        if "text" in context:
            return context["text"]
        if "nodes" in context:
            nodes = context.get("nodes", [])
            return "Path: " + " → ".join([n.get("name", str(n)) for n in nodes])
        return str(context)

    async def _fallback_search(
        self,
        query: str,
        k: int,
        document_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        filter_dict = {"document_id": document_id} if document_id else None
        results = await self.vector_tool.run(query, k=k, filter=filter_dict)

        if results:
            context_text = "\n\n".join([r.get("text", str(r)) for r in results[:3]])
            prompt = f"Answer briefly: {query}\n\nContext:\n{context_text}"
            answer = await self.llm.complete(prompt, temperature=0.3)
        else:
            answer = "I couldn't find relevant information."

        return {
            "answer": answer,
            "contexts": results,
            "reasoning_steps": ["Timeout — used fallback vector search"],
            "confidence": 0.6,
        }
