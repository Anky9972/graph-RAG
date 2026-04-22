"""
Agentic retrieval system with LangGraph orchestration
Gap #1:  Hybrid BM25+Vector search as default tool
Gap #3:  DRIFT-style iterative query expansion
Gap #4:  LLM-as-a-Judge real confidence scoring
Gap #6:  Graph-of-Thought parallel exploration
Gap #8 (cache): Semantic query cache via Redis
"""

from typing import List, Dict, Any, Optional, AsyncGenerator
from typing_extensions import TypedDict
import asyncio
import time
import json
import hashlib

from langgraph.graph import StateGraph, END

from .tools import (
    HybridSearchTool,
    VectorSearchTool,
    GraphTraversalTool,
    CypherGenerationTool,
    MetadataFilterTool,
    CommunitySummaryTool,
    LLMJudge,
    EntitySummarySearchTool,
)
from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider
from ..core.models import QueryResult, OntologySchema, ConfidenceJudgment
from ..config import settings


class AgentRetrievalSystem:
    """
    Agentic retrieval system that:
    1. Checks semantic cache (Gap #8)
    2. Decomposes complex queries
    3. Routes to hybrid / graph / cypher / filter / community tools
    4. Applies DRIFT iterative expansion when confidence is low (Gap #3)
    5. Optional GoT parallel exploration (Gap #6)
    6. Synthesizes responses with real LLM-Judge confidence (Gap #4)
    7. Supports streaming via astream()
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

        # Tools
        self.hybrid_tool = HybridSearchTool(self.store, self.llm)      # Gap #1
        self.vector_tool = VectorSearchTool(self.store, self.llm)
        self.graph_tool = GraphTraversalTool(self.store, self.llm)
        self.cypher_tool = CypherGenerationTool(self.store, self.llm, ontology)
        self.filter_tool = MetadataFilterTool(self.store)
        self.community_tool = CommunitySummaryTool(self.store, self.llm)  # Gap #2
        self.entity_summary_tool = EntitySummarySearchTool(self.store, self.llm)  # MiroFish
        self.judge = LLMJudge(self.llm)                                  # Gap #4

        # Redis for semantic cache (Gap #8)
        self._redis = None

        self.graph = self._build_graph()

    # ── Redis cache helpers (Gap #8) ──────────────────────────────────────────

    async def _get_redis(self):
        """Lazily initialize Redis connection"""
        if self._redis is None and settings.enable_semantic_cache:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(settings.redis_url)
            except Exception:
                self._redis = None
        return self._redis

    async def _cache_get(self, query: str) -> Optional[Dict[str, Any]]:
        """Check semantic cache for a query result"""
        if not settings.enable_semantic_cache:
            return None
        redis = await self._get_redis()
        if not redis:
            return None
        try:
            cache_key = f"query_cache:{hashlib.sha256(query.lower().strip().encode()).hexdigest()}"
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached.decode("utf-8"))
        except Exception:
            pass
        return None

    async def _cache_set(self, query: str, result: Dict[str, Any]) -> None:
        """Store query result in semantic cache"""
        if not settings.enable_semantic_cache:
            return
        redis = await self._get_redis()
        if not redis:
            return
        try:
            cache_key = f"query_cache:{hashlib.sha256(query.lower().strip().encode()).hexdigest()}"
            await redis.setex(
                cache_key,
                settings.cache_ttl_seconds,
                json.dumps(result, default=str).encode("utf-8")
            )
        except Exception:
            pass

    # ── LangGraph workflow ────────────────────────────────────────────────────

    def _build_graph(self) -> StateGraph:
        """Build LangGraph workflow with all new nodes"""

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
            drift_expanded: bool    # Gap #3
            use_got: bool           # Gap #6

        workflow = StateGraph(State)

        workflow.add_node("decompose", self._decompose_query)
        workflow.add_node("route", self._route_query)
        workflow.add_node("hybrid_search", self._hybrid_search)          # Gap #1
        workflow.add_node("graph_traversal", self._graph_traversal)
        workflow.add_node("cypher_query", self._cypher_query)
        workflow.add_node("metadata_filter", self._metadata_filter)
        workflow.add_node("community_search", self._community_search)   # Gap #2
        workflow.add_node("entity_summary", self._entity_summary_search) # MiroFish
        workflow.add_node("drift_expand", self._drift_expand)            # Gap #3
        workflow.add_node("got_explore", self._got_explore)              # Gap #6
        workflow.add_node("synthesize", self._synthesize_response)

        workflow.set_entry_point("decompose")
        workflow.add_edge("decompose", "route")
        workflow.add_conditional_edges(
            "route",
            self._should_continue,
            {
                "hybrid": "hybrid_search",
                "vector": "hybrid_search",     # vector routes to hybrid for quality
                "graph": "graph_traversal",
                "cypher": "cypher_query",
                "filter": "metadata_filter",
                "community": "community_search",
                "entity_summary": "entity_summary",  # MiroFish entity profiles
                "got": "got_explore",
                "drift": "drift_expand",
                "synthesize": "synthesize",
            }
        )
        workflow.add_edge("hybrid_search", "route")
        workflow.add_edge("graph_traversal", "route")
        workflow.add_edge("cypher_query", "route")
        workflow.add_edge("metadata_filter", "route")
        workflow.add_edge("community_search", "route")
        workflow.add_edge("entity_summary", "route")
        workflow.add_edge("got_explore", "route")
        workflow.add_edge("drift_expand", "route")
        workflow.add_edge("synthesize", END)

        return workflow.compile()

    # ── Public API ────────────────────────────────────────────────────────────

    async def query(
        self,
        query: str,
        top_k: int = None,
        document_id: Optional[str] = None,
        streaming: bool = False,
        use_got: bool = False,
    ) -> QueryResult:
        start_time = time.time()
        top_k = top_k or settings.default_top_k

        # Gap #8: Check semantic cache first
        cached = await self._cache_get(query)
        if cached:
            cached["reasoning_chain"] = ["[CACHE HIT] Retrieved from semantic cache"] + \
                                         cached.get("reasoning_chain", [])
            processing_time = time.time() - start_time
            return QueryResult(
                answer=cached.get("answer", ""),
                sources=cached.get("sources", []),
                reasoning_chain=cached.get("reasoning_chain", []),
                confidence=cached.get("confidence", 0.8),
                confidence_judgment=None,
                retrieval_method="semantic_cache",
                processing_time_seconds=processing_time,
                drift_expanded=False,
                total_sub_queries=1
            )

        initial_state = self._make_initial_state(query, document_id, use_got=use_got)

        try:
            result = await asyncio.wait_for(
                self.graph.ainvoke(initial_state),
                timeout=settings.agent_timeout_seconds
            )
        except asyncio.TimeoutError:
            result = await self._fallback_search(query, top_k, document_id)

        processing_time = time.time() - start_time

        # Gap #4: LLM-as-a-Judge real confidence score
        judgment = None
        if settings.enable_llm_judge and result.get("answer") and result.get("contexts"):
            judge_data = await self.judge.score(
                query=query,
                answer=result["answer"],
                contexts=result["contexts"]
            )
            judgment = ConfidenceJudgment(
                score=judge_data["score"],
                reasoning=judge_data["reasoning"],
                grounded_claims=judge_data["grounded_claims"],
                ungrounded_claims=judge_data["ungrounded_claims"],
                hallucination_risk=judge_data["hallucination_risk"]
            )

        # Use judge score, fall back to heuristic
        final_confidence = judgment.score if judgment else result.get("confidence", 0.5)

        query_result = QueryResult(
            answer=result.get("answer", "I couldn't find a satisfactory answer."),
            sources=result.get("contexts", []),
            reasoning_chain=result.get("reasoning_steps", []),
            confidence=final_confidence,
            confidence_judgment=judgment,
            retrieval_method="agentic_hybrid",
            processing_time_seconds=processing_time,
            drift_expanded=result.get("drift_expanded", False),
            total_sub_queries=len(result.get("decomposed_queries", [query]))
        )

        # Gap #8: Store result in semantic cache
        await self._cache_set(query, {
            "answer": query_result.answer,
            "sources": query_result.sources[:5],  # limit cached sources
            "reasoning_chain": query_result.reasoning_chain,
            "confidence": query_result.confidence,
        })

        return query_result

    async def astream(
        self,
        query: str,
        top_k: int = None,
        document_id: Optional[str] = None,
        use_got: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream partial states after each graph node for SSE."""
        initial_state = self._make_initial_state(query, document_id, use_got=use_got)

        try:
            async for partial_state in self.graph.astream(initial_state):
                for node_name, state in partial_state.items():
                    yield state
        except asyncio.TimeoutError:
            result = await self._fallback_search(query, top_k or settings.default_top_k, document_id)
            yield result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_initial_state(
        self,
        query: str,
        document_id: Optional[str],
        use_got: bool = False
    ) -> Dict[str, Any]:
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
            "routing_decision": "hybrid",
            "drift_expanded": False,
            "use_got": use_got,
        }

    # ── Graph nodes ───────────────────────────────────────────────────────────

    async def _decompose_query(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["query"]

        prompt = f"""
Analyze this query and break it down into simpler sub-queries if needed.

Query: "{query}"

Rules:
- If simple and factual → return it as-is in a single-item list
- If complex or multi-hop → decompose into 2-4 sub-queries
- If thematic/summary question (words like "overall", "themes", "summarize") → tag as [COMMUNITY]

Return only a JSON list: ["sub-query 1", "sub-query 2", ...]
"""
        response = await self.llm.complete(prompt, temperature=0.2)

        try:
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

        # Gap #2: detect community/thematic queries
        community_keywords = ["overall", "summarize", "themes", "landscape", "across all",
                              "big picture", "main topics", "overview", "what is the"]
        if any(kw in current_query.lower() for kw in community_keywords):
            state["routing_decision"] = "community"
            state["reasoning_steps"].append(
                f"Sub-query {iteration+1}: \"{current_query}\" → community_summary"
            )
            return state

        # Gap #6: GoT for complex multi-hop queries
        if state.get("use_got"):
            state["routing_decision"] = "got"
            state["reasoning_steps"].append(
                f"Sub-query {iteration+1}: \"{current_query}\" → graph_of_thought"
            )
            return state

        # MiroFish: detect entity-profile queries
        entity_keywords = ["who is", "what is", "tell me about", "describe", "profile of",
                           "background on", "what does", "about the entity"]
        if any(kw in current_query.lower() for kw in entity_keywords):
            state["routing_decision"] = "entity_summary"
            state["reasoning_steps"].append(
                f"Sub-query {iteration+1}: \"{current_query}\" → entity_summary"
            )
            return state

        # Normal routing
        prompt = f"""
Choose the best retrieval method for this query:

Query: "{current_query}"

Methods:
- hybrid        : semantic + keyword search — best for most factual questions
- graph         : relationship queries, "how are X and Y connected", "path between"
- cypher        : complex structured queries needing precise graph pattern matching
- filter        : attribute filtering (by date, type, document name, etc.)
- community     : thematic/summary queries needing big-picture view
- entity_summary: questions about a specific named entity — "who is X?", "describe Y"

Return ONLY one word: hybrid | graph | cypher | filter | community | entity_summary
"""
        response = await self.llm.complete(prompt, temperature=0.0)
        method = response.strip().lower().split()[0]

        if method not in ("hybrid", "graph", "cypher", "filter", "community", "entity_summary"):
            method = "hybrid"

        state["routing_decision"] = method
        state["reasoning_steps"].append(
            f"Sub-query {iteration+1}: \"{current_query}\" → {method}"
        )
        return state

    def _should_continue(self, state: Dict[str, Any]) -> str:
        iteration = state.get("iteration", 0)
        sub_queries = state.get("decomposed_queries", [])

        if iteration >= len(sub_queries) or iteration >= settings.max_agent_iterations:
            # Gap #3: DRIFT expansion — if low confidence, try expanding
            if (settings.enable_drift_expansion
                    and not state.get("drift_expanded")
                    and state.get("contexts")
                    and len(state.get("contexts", [])) < 3):
                return "drift"
            return "synthesize"

        return state.get("routing_decision", "hybrid")

    # ── Tool execution nodes ──────────────────────────────────────────────────

    async def _hybrid_search(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Gap #1 — Hybrid BM25+Vector with RRF"""
        iteration = state["iteration"]
        query = state["decomposed_queries"][iteration]
        document_id = state.get("document_id")

        results = await self.hybrid_tool.run(
            query=query,
            k=settings.default_top_k,
            document_id=document_id
        )

        state["contexts"].extend(results)
        state["iteration"] += 1
        state["reasoning_steps"].append(f"Hybrid search: {len(results)} results")
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
            cleaned = response.strip()
            for marker in ("```json", "```"):
                if marker in cleaned:
                    cleaned = cleaned.split(marker)[1].split("```")[0]
            filters = json.loads(cleaned.strip())
        except Exception:
            filters = {}

        if document_id and "document_id" not in filters:
            filters["document_id"] = document_id

        results = await self.filter_tool.run(filters) if filters else []

        state["contexts"].extend(results)
        state["iteration"] += 1
        state["reasoning_steps"].append(f"Metadata filter {filters}: {len(results)} results")
        return state

    async def _community_search(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Gap #2 — LazyGraphRAG community summary search"""
        iteration = state["iteration"]
        query = state["decomposed_queries"][iteration]

        results = await self.community_tool.run(query)

        state["contexts"].extend(results)
        state["iteration"] += 1
        state["reasoning_steps"].append(f"Community search: {len(results)} community summaries")
        return state

    async def _entity_summary_search(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """MiroFish — Entity profile summary search via EntitySummarySearchTool"""
        iteration = state["iteration"]
        query = state["decomposed_queries"][iteration]

        results = await self.entity_summary_tool.run(query, k=settings.default_top_k)

        state["contexts"].extend(results)
        state["iteration"] += 1
        state["reasoning_steps"].append(
            f"Entity summary search: {len(results)} entity profiles retrieved"
        )
        return state

    async def _drift_expand(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gap #3 — DRIFT iterative expansion.
        Generates follow-up queries based on what was retrieved so far.
        """
        if not state.get("contexts"):
            state["drift_expanded"] = True
            return state

        found_text = "\n".join([
            ctx.get("text", "")[:200]
            for ctx in state["contexts"][:3]
        ])

        prompt = f"""
Original question: {state["query"]}

Information found so far:
{found_text}

What 1-2 follow-up questions would help complete a better answer?
These should fill gaps or clarify ambiguities in the retrieved information.
Return JSON list: ["follow-up 1", "follow-up 2"]
"""
        try:
            response = await self.llm.complete(prompt, temperature=0.2)
            cleaned = response.strip()
            for marker in ("```json", "```"):
                if marker in cleaned:
                    cleaned = cleaned.split(marker)[1].split("```")[0]
            follow_ups = json.loads(cleaned.strip())
            if isinstance(follow_ups, list) and follow_ups:
                state["decomposed_queries"].extend(
                    follow_ups[:settings.max_drift_expansions]
                )
                state["reasoning_steps"].append(
                    f"DRIFT expanded with {len(follow_ups)} follow-up queries"
                )
        except Exception as e:
            print(f"DRIFT expansion error: {e}")

        state["drift_expanded"] = True
        return state

    async def _got_explore(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gap #6 — Graph-of-Thought: run all retrieval strategies in parallel,
        score results, merge the top-2 strategies.
        """
        iteration = state["iteration"]
        query = state["decomposed_queries"][iteration]
        document_id = state.get("document_id")

        tasks = [
            self.hybrid_tool.run(query=query, k=settings.default_top_k, document_id=document_id),
            self.graph_tool.run(query),
            self.cypher_tool.run(query),
            self.community_tool.run(query),
        ]

        tool_names = ["hybrid", "graph", "cypher", "community"]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        scored: List[tuple] = []
        for name, result in zip(tool_names, all_results):
            if isinstance(result, Exception) or not result:
                continue
            score = await self._score_tool_results(query, result)
            scored.append((score, name, result))

        # Sort by score, pick top-2 strategies
        scored.sort(key=lambda x: x[0], reverse=True)
        merged = []
        strategies_used = []
        for score, name, result in scored[:2]:
            merged.extend(result)
            strategies_used.append(f"{name}({score:.2f})")

        state["contexts"].extend(merged)
        state["iteration"] += 1
        state["reasoning_steps"].append(
            f"GoT parallel: {', '.join(strategies_used)} → {len(merged)} merged results"
        )
        return state

    async def _score_tool_results(
        self,
        query: str,
        results: List[Dict[str, Any]]
    ) -> float:
        """Quick scoring of how relevant tool results are for a query"""
        if not results:
            return 0.0

        sample_text = " ".join([r.get("text", "")[:100] for r in results[:3]])
        if not sample_text.strip():
            return 0.3  # graph results may not have text

        prompt = f"""
Query: {query}
Sample retrieved text: {sample_text[:300]}

Score relevance from 0.0 to 1.0. Return ONLY a float.
"""
        try:
            resp = await self.llm.complete(prompt, temperature=0.0)
            return float(resp.strip().split()[0])
        except Exception:
            return 0.5

    async def _synthesize_response(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state["query"]
        contexts = state["contexts"]

        if not contexts:
            state["answer"] = "I couldn't find relevant information to answer your question."
            state["confidence"] = 0.0
            return state

        context_text = "\n\n".join([
            f"Context {i+1} [{ctx.get('retrieval_method', 'unknown')}]:\n{self._format_context(ctx)}"
            for i, ctx in enumerate(contexts[:10])
        ])

        prompt = f"""Answer the question based only on the retrieved contexts below.

Question: {query}

Retrieved Contexts:
{context_text}

Instructions:
- Answer using ONLY information from the contexts
- Cite which context numbers support each claim
- If contexts are insufficient, say so clearly
- Do not hallucinate or infer beyond what is in the contexts"""

        answer = await self.llm.complete(
            prompt,
            system_prompt="You answer questions accurately using only provided context. Never hallucinate.",
            temperature=0.3
        )

        state["answer"] = answer
        # Heuristic confidence (will be overridden by LLM Judge)
        state["confidence"] = min(1.0, len(contexts) / max(settings.default_top_k, 1))
        state["reasoning_steps"].append("Synthesized final answer")
        return state

    def _format_context(self, context: Dict[str, Any]) -> str:
        if "text" in context:
            page = f" [page {context['page_number']}]" if context.get("page_number") else ""
            return f"{context['text']}{page}"
        if "nodes" in context:
            nodes = context.get("nodes", [])
            return "Path: " + " → ".join([n.get("name", str(n)) for n in nodes])
        if "summary" in context:
            return context["summary"]
        return str(context)

    async def _fallback_search(
        self,
        query: str,
        k: int,
        document_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fallback on timeout — use hybrid search directly"""
        results = await self.hybrid_tool.run(query=query, k=k, document_id=document_id)

        if results:
            context_text = "\n\n".join([r.get("text", str(r)) for r in results[:3]])
            prompt = f"Answer briefly: {query}\n\nContext:\n{context_text}"
            answer = await self.llm.complete(prompt, temperature=0.3)
        else:
            answer = "I couldn't find relevant information."

        return {
            "answer": answer,
            "contexts": results,
            "reasoning_steps": ["Timeout — used fallback hybrid search"],
            "confidence": 0.5,
        }
