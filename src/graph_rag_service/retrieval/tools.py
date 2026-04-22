"""
Retrieval tools for the agentic system
Gap #1: HybridSearchTool — BM25 + Vector with RRF fusion
Gap #2: CommunitySummaryTool — LazyGraphRAG community summaries
Gap #6: Scoring utilities for Graph-of-Thought parallel exploration
"""

from typing import List, Dict, Any, Optional
import json
import asyncio
import hashlib

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider
from ..core.models import OntologySchema
from ..config import settings


# ── Gap #1: Hybrid Search Tool (BM25 + Vector + RRF) ───────────────────────

class HybridSearchTool:
    """
    Combines dense (vector) and sparse (BM25) retrieval via
    Reciprocal Rank Fusion (RRF) — the 2025 production standard.
    """

    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider):
        self.store = store
        self.llm = llm
        self.name = "hybrid_search"
        self.description = (
            "Hybrid BM25 + vector search with RRF fusion. "
            "Best for most queries — handles both semantic and keyword matching."
        )

    async def run(
        self,
        query: str,
        k: int = None,
        filter: Optional[Dict] = None,
        document_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Run both BM25 and vector search in parallel, then fuse with RRF.

        Args:
            query: Natural language query
            k: Final number of results after fusion
            filter: Optional metadata filters
            document_id: Optional document scope

        Returns:
            RRF-fused results, highest-scored first
        """
        k = k or settings.default_top_k
        search_k = k * 3  # over-fetch for fusion

        # Run both searches in parallel
        query_embedding = await self.llm.embed(query)

        bm25_task = self.store.bm25_search(query, k=search_k, document_id=document_id)
        vector_task = self.store.search(
            query_vector=query_embedding,
            k=search_k,
            filter=filter or ({"document_id": document_id} if document_id else None)
        )

        bm25_results, vector_results = await asyncio.gather(
            bm25_task, vector_task, return_exceptions=True
        )

        if isinstance(bm25_results, Exception):
            bm25_results = []
        if isinstance(vector_results, Exception):
            vector_results = []

        # RRF Fusion
        fused = self._rrf_fuse(
            list_a=vector_results,
            list_b=bm25_results,
            rrf_k=settings.rrf_k
        )

        # Build final result list (top k)
        doc_lookup: Dict[str, Dict] = {}
        for r in vector_results + bm25_results:
            if r.get("id") and r["id"] not in doc_lookup:
                doc_lookup[r["id"]] = r

        final = []
        for chunk_id, score in fused[:k]:
            doc = doc_lookup.get(chunk_id, {})
            doc["hybrid_score"] = score
            doc["retrieval_method"] = "hybrid_rrf"
            final.append(doc)

        return final

    def _rrf_fuse(
        self,
        list_a: List[Dict],
        list_b: List[Dict],
        rrf_k: int = 60
    ) -> List[tuple]:
        """
        Reciprocal Rank Fusion.
        Returns sorted list of (id, score) tuples.
        Non-parametric — no tuning needed.
        """
        scores: Dict[str, float] = {}

        for rank, doc in enumerate(list_a):
            doc_id = doc.get("id", "")
            if doc_id:
                scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank + 1)

        for rank, doc in enumerate(list_b):
            doc_id = doc.get("id", "")
            if doc_id:
                scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank + 1)

        return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ── Legacy vector-only tool (kept for fallback/GoT) ─────────────────────────

class VectorSearchTool:
    """Vector similarity search tool — pure dense retrieval"""

    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider):
        self.store = store
        self.llm = llm
        self.name = "vector_search"
        self.description = "Semantic similarity search. Good for conceptual/thematic queries."

    async def run(
        self,
        query: str,
        k: int = None,
        filter: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        k = k or settings.default_top_k
        query_embedding = await self.llm.embed(query)
        results = await self.store.search(
            query_vector=query_embedding,
            k=k,
            filter=filter
        )
        for r in results:
            r["retrieval_method"] = "vector"
        return results


# ── Gap #2: Community Summary Tool (LazyGraphRAG) ───────────────────────────

class CommunitySummaryTool:
    """
    LazyGraphRAG-style community summarization.
    Detects entity clusters, generates LLM summaries at query time.
    Results are cached in Redis with configurable TTL.
    """

    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider):
        self.store = store
        self.llm = llm
        self.name = "community_search"
        self.description = (
            "High-level thematic search using entity communities. "
            "Best for: 'What are the main themes?', 'Summarize the landscape', "
            "'What is the overall picture?'"
        )
        self._redis = None

    async def _get_redis(self):
        """Lazily initialize Redis connection for caching"""
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(settings.redis_url)
            except Exception:
                self._redis = None
        return self._redis

    async def run(
        self,
        query: str,
        k: int = None
    ) -> List[Dict[str, Any]]:
        """
        1. Find relevant entities via hybrid search
        2. Group by community_id
        3. Generate LLM summary for top communities (cached)
        4. Return community summaries as context chunks

        Args:
            query: Natural language query (holistic/thematic)
            k: Number of community summaries to return

        Returns:
            List of community summaries as context dicts
        """
        k = k or 3  # Top-3 communities

        # Step 1: Find relevant entities
        entity_names = await self._find_relevant_entities(query, limit=20)
        if not entity_names:
            return []

        # Step 2: Get community groupings
        communities = await self.store.get_communities(entity_names)
        if not communities:
            return []

        # Step 3: Generate summaries for top communities
        results = []
        for community_id, entities in list(communities.items())[:k]:
            summary = await self._get_community_summary(community_id, entities, query)
            if summary:
                results.append({
                    "id": f"community_{community_id}",
                    "text": summary,
                    "community_id": community_id,
                    "entity_count": len(entities),
                    "retrieval_method": "community_summary",
                    "score": 0.85  # Community scores are high-confidence thematic results
                })

        return results

    async def _find_relevant_entities(self, query: str, limit: int = 20) -> List[str]:
        """Find entity names most relevant to the query via BM25"""
        try:
            cypher = """
            CALL db.index.fulltext.queryNodes('chunk_text_index', $query)
            YIELD node, score
            MATCH (node)-[:MENTIONS]->(e:Entity)
            RETURN DISTINCT e.name as name
            LIMIT $limit
            """
            rows = await self.store.execute_query(cypher, {"query": query, "limit": limit})
            return [r["name"] for r in rows if r.get("name")]
        except Exception:
            return []

    async def _get_community_summary(
        self,
        community_id: int,
        entities: List[Dict],
        query: str
    ) -> Optional[str]:
        """Generate or fetch cached LLM summary for a community"""
        # Build cache key from community entities
        entity_names = sorted([e.get("name", "") for e in entities])
        cache_key = f"community_summary:{hashlib.md5(':'.join(entity_names).encode()).hexdigest()}"

        # Check Redis cache
        redis = await self._get_redis()
        if redis:
            try:
                cached = await redis.get(cache_key)
                if cached:
                    return cached.decode("utf-8")
            except Exception:
                pass

        # Generate summary with LLM
        entity_descriptions = []
        for e in entities[:settings.max_community_entities]:
            desc = f"- {e.get('name', 'Unknown')} ({e.get('type', 'Entity')})"
            entity_descriptions.append(desc)

        prompt = f"""
You are analyzing a community of interconnected entities from a knowledge graph.

Community #{community_id} contains {len(entities)} entities:
{chr(10).join(entity_descriptions)}

User's question: "{query}"

Generate a focused 2-3 sentence summary of what this community represents and
how it relates to the question. Focus on themes, patterns, and key relationships.
Be specific and factual. Do not hallucinate relationships not implied by the entity names.
"""
        try:
            summary = await self.llm.complete(prompt, temperature=0.2)
            summary = summary.strip()

            # Cache the result
            if redis and summary:
                try:
                    await redis.setex(
                        cache_key,
                        settings.community_summary_cache_ttl,
                        summary.encode("utf-8")
                    )
                except Exception:
                    pass

            return summary
        except Exception as e:
            print(f"Community summary generation error: {e}")
            return None


# ── Graph Traversal Tool ─────────────────────────────────────────────────────

class GraphTraversalTool:
    """Graph traversal and path finding tool"""

    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider):
        self.store = store
        self.llm = llm
        self.name = "graph_traversal"
        self.description = "Traverse knowledge graph to find relationships and paths between entities"

    async def run(
        self,
        query: str,
        source_entity: Optional[str] = None,
        target_entity: Optional[str] = None,
        depth: int = None
    ) -> List[Dict[str, Any]]:
        depth = depth or settings.graph_max_depth

        if not source_entity or not target_entity:
            entities = await self._extract_entities_from_query(query)
            if len(entities) >= 2:
                source_entity = source_entity or entities[0]
                target_entity = target_entity or entities[1]
            elif len(entities) == 1:
                source_entity = source_entity or entities[0]

        if source_entity and target_entity:
            results = await self.store.find_path(source_entity, target_entity, depth)
        elif source_entity:
            results = await self.store.get_neighbors(source_entity, depth)
        else:
            results = []

        for r in results:
            r["retrieval_method"] = "graph_traversal"
        return results

    async def _extract_entities_from_query(self, query: str) -> List[str]:
        """Extract entity names from natural language query"""
        prompt = f"""
Extract entity names from this query:
"{query}"

Return only a JSON list of entity names: ["Entity1", "Entity2", ...]
"""
        response = await self.llm.complete(prompt, temperature=0.1)
        try:
            cleaned = response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0]
            cleaned = cleaned.strip()
            entities = json.loads(cleaned)
            return entities if isinstance(entities, list) else []
        except Exception:
            return []


# ── Cypher Generation Tool ───────────────────────────────────────────────────

class CypherGenerationTool:
    """
    Text-to-Cypher tool with hallucination guards.
    Generates Cypher queries from natural language.
    """

    def __init__(
        self,
        store: Neo4jStore,
        llm: UnifiedLLMProvider,
        ontology: Optional[OntologySchema] = None
    ):
        self.store = store
        self.llm = llm
        self.ontology = ontology
        self.name = "cypher_query"
        self.description = "Generate and execute Cypher queries for complex structured graph queries"

    async def run(self, query: str) -> List[Dict[str, Any]]:
        cypher = await self._generate_cypher(query)
        if not cypher:
            return []

        if not self._validate_cypher(cypher):
            cypher = await self._correct_cypher(cypher, query)
            if not self._validate_cypher(cypher):
                return []

        try:
            results = await self.store.execute_query(cypher)
            for r in results:
                r["retrieval_method"] = "cypher"
            return results
        except Exception as e:
            print(f"Cypher execution error: {e}")
            cypher = await self._correct_cypher_with_error(cypher, query, str(e))
            try:
                results = await self.store.execute_query(cypher)
                for r in results:
                    r["retrieval_method"] = "cypher"
                return results
            except Exception:
                return []

    async def _generate_cypher(self, query: str) -> str:
        schema_info = ""
        if self.ontology:
            schema_info = f"""
Graph Schema:
- Entity Types: {', '.join(self.ontology.entity_types)}
- Relationship Types: {', '.join(self.ontology.relationship_types)}
"""
        prompt = f"""
You are a Cypher query generator. Generate a Cypher query for Neo4j.

Question: {query}
{schema_info}

Rules:
1. Only use entity labels and relationship types from the schema
2. Use MATCH clauses to find patterns
3. Use WHERE clauses for filtering
4. Return relevant data with RETURN clause
5. Add LIMIT 20 to prevent excessive results
6. Do not use deprecated syntax

Return only the Cypher query, no explanation.
"""
        response = await self.llm.complete(
            prompt,
            system_prompt="You generate syntactically correct Cypher queries for Neo4j.",
            temperature=0.1
        )
        cypher = response.strip()
        if "```cypher" in cypher:
            cypher = cypher.split("```cypher")[1].split("```")[0]
        elif "```" in cypher:
            cypher = cypher.split("```")[1].split("```")[0]
        return cypher.strip()

    def _validate_cypher(self, cypher: str) -> bool:
        if not cypher:
            return False
        cypher_upper = cypher.upper()
        if "MATCH" not in cypher_upper and "CALL" not in cypher_upper:
            return False
        dangerous_keywords = ["DELETE", "DETACH DELETE", "DROP", "REMOVE"]
        for keyword in dangerous_keywords:
            if keyword in cypher_upper:
                return False
        return True

    async def _correct_cypher(self, cypher: str, query: str) -> str:
        prompt = f"""
This Cypher query may have issues:
{cypher}

Original question: {query}
Fix any syntax errors or schema violations. Return only the corrected Cypher query.
"""
        response = await self.llm.complete(prompt, temperature=0.1)
        corrected = response.strip()
        if "```" in corrected:
            corrected = corrected.split("```")[1]
            if corrected.startswith("cypher"):
                corrected = corrected[6:]
            corrected = corrected.split("```")[0]
        return corrected.strip()

    async def _correct_cypher_with_error(self, cypher: str, query: str, error: str) -> str:
        prompt = f"""
This Cypher query failed with an error:

Query: {cypher}
Error: {error}

Original question: {query}
Fix the query to resolve the error. Return only the corrected Cypher.
"""
        response = await self.llm.complete(prompt, temperature=0.1)
        corrected = response.strip()
        if "```" in corrected:
            corrected = corrected.split("```")[1]
            if corrected.startswith("cypher"):
                corrected = corrected[6:]
            corrected = corrected.split("```")[0]
        return corrected.strip()


# ── Metadata Filter Tool ─────────────────────────────────────────────────────

class MetadataFilterTool:
    """Filter-based retrieval using metadata constraints"""

    def __init__(self, store: Neo4jStore):
        self.store = store
        self.name = "metadata_filter"
        self.description = "Filter entities or chunks by metadata attributes (date, type, source, etc.)"

    async def run(
        self,
        filters: Dict[str, Any],
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        where_clauses = []
        params: Dict[str, Any] = {}

        for i, (key, value) in enumerate(filters.items()):
            param_name = f"param_{i}"
            if isinstance(value, list):
                where_clauses.append(f"n.{key} IN ${param_name}")
            else:
                where_clauses.append(f"n.{key} = ${param_name}")
            params[param_name] = value

        where_clause = " AND ".join(where_clauses) if where_clauses else "true"

        query = f"""
        MATCH (n)
        WHERE {where_clause}
        RETURN n
        LIMIT $limit
        """
        params["limit"] = limit

        results = await self.store.execute_query(query, params)
        for r in results:
            r["retrieval_method"] = "metadata_filter"
        return results


# ── Gap #4: LLM-as-a-Judge Scorer ────────────────────────────────────────────

class LLMJudge:
    """
    LLM-as-a-Judge for real confidence scoring.
    Replaces the fake len(contexts)/top_k formula.
    """

    def __init__(self, llm: UnifiedLLMProvider):
        self.llm = llm

    async def score(
        self,
        query: str,
        answer: str,
        contexts: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Evaluate how well the answer is grounded in the retrieved contexts.

        Returns:
            {
                "score": float (0.0-1.0),
                "reasoning": str,
                "grounded_claims": int,
                "ungrounded_claims": int,
                "hallucination_risk": "low" | "medium" | "high"
            }
        """
        if not contexts or not answer:
            return {
                "score": 0.0,
                "reasoning": "No contexts or empty answer",
                "grounded_claims": 0,
                "ungrounded_claims": 0,
                "hallucination_risk": "high"
            }

        context_text = "\n\n".join([
            f"[Context {i+1}]: {ctx.get('text', str(ctx))[:400]}"
            for i, ctx in enumerate(contexts[:6])
        ])

        prompt = f"""You are an expert fact-checker evaluating whether an AI answer is grounded in source documents.

Question: {query}

AI Answer:
{answer[:600]}

Source Contexts:
{context_text}

Evaluate the answer. For each claim in the answer, check if it is directly supported by at least one context.

Rate the answer:
- 0.9-1.0: Every claim is clearly stated in the contexts (no hallucination)
- 0.7-0.9: Most claims supported, minor paraphrasing only
- 0.5-0.7: Some claims supported, some come from model training/inference
- 0.3-0.5: Many claims not traceable to contexts
- 0.0-0.3: Answer largely contradicts or ignores provided contexts

Return ONLY valid JSON (no markdown, no extra text):
{{"score": 0.85, "reasoning": "brief explanation", "grounded_claims": 4, "ungrounded_claims": 1}}"""

        try:
            response = await self.llm.complete(
                prompt,
                system_prompt="You are a strict factuality evaluator. Return only valid JSON.",
                temperature=settings.judge_temperature
            )
            cleaned = response.strip()
            # Strip any markdown code fences
            if "```" in cleaned:
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.split("```")[0]
            data = json.loads(cleaned.strip())

            score = float(data.get("score", 0.5))
            grounded = int(data.get("grounded_claims", 0))
            ungrounded = int(data.get("ungrounded_claims", 0))

            if score >= 0.75:
                risk = "low"
            elif score >= 0.5:
                risk = "medium"
            else:
                risk = "high"

            return {
                "score": score,
                "reasoning": data.get("reasoning", ""),
                "grounded_claims": grounded,
                "ungrounded_claims": ungrounded,
                "hallucination_risk": risk
            }
        except Exception as e:
            print(f"LLM Judge error: {e}")
            # Fallback: use a simple heuristic
            base_score = min(1.0, len(contexts) / max(settings.default_top_k, 1))
            return {
                "score": base_score,
                "reasoning": f"Heuristic score (judge unavailable: {e})",
                "grounded_claims": len(contexts),
                "ungrounded_claims": 0,
                "hallucination_risk": "medium" if base_score < 0.7 else "low"
            }


# ── Gap #8: RAG Evaluator ────────────────────────────────────────────────────

class RAGEvaluator:
    """
    RAGAS-style evaluation metrics for the quality dashboard.
    Computes faithfulness, answer_relevancy, context_precision.
    """

    def __init__(self, llm: UnifiedLLMProvider):
        self.llm = llm

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: List[str],
        ground_truth: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Run all evaluation metrics in parallel.
        Returns dict with metric scores.
        """
        tasks = [
            self._faithfulness(answer, contexts),
            self._answer_relevancy(question, answer),
            self._context_precision(question, contexts),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        faithfulness = results[0] if not isinstance(results[0], Exception) else 0.5
        relevancy = results[1] if not isinstance(results[1], Exception) else 0.5
        precision = results[2] if not isinstance(results[2], Exception) else 0.5

        overall = (faithfulness * 0.4 + relevancy * 0.35 + precision * 0.25)

        return {
            "faithfulness": faithfulness,
            "answer_relevancy": relevancy,
            "context_precision": precision,
            "overall_score": overall,
            "hallucination_detected": faithfulness < 0.5
        }

    async def _faithfulness(self, answer: str, contexts: List[str]) -> float:
        """
        Measure: Are all claims in the answer supported by the contexts?
        """
        ctx_text = "\n".join([f"- {c[:300]}" for c in contexts[:5]])
        prompt = f"""Given these source contexts:
{ctx_text}

And this answer:
{answer[:400]}

Score from 0.0 to 1.0 how faithfully the answer is grounded in the contexts.
1.0 = every statement is supported. 0.0 = answer contradicts or ignores contexts.
Return ONLY a float number like: 0.82"""
        try:
            resp = await self.llm.complete(prompt, temperature=0.0)
            return float(resp.strip().split()[0])
        except Exception:
            return 0.5

    async def _answer_relevancy(self, question: str, answer: str) -> float:
        """
        Measure: Does the answer actually address the question?
        """
        prompt = f"""Question: {question}
Answer: {answer[:400]}

Score from 0.0 to 1.0 how relevant and complete the answer is for the question.
1.0 = fully answers the question. 0.0 = completely off-topic.
Return ONLY a float number like: 0.91"""
        try:
            resp = await self.llm.complete(prompt, temperature=0.0)
            return float(resp.strip().split()[0])
        except Exception:
            return 0.5

    async def _context_precision(self, question: str, contexts: List[str]) -> float:
        """
        Measure: Are the retrieved contexts useful for answering the question?
        """
        if not contexts:
            return 0.0
        ctx_text = "\n".join([f"[{i+1}]: {c[:200]}" for i, c in enumerate(contexts[:5])])
        prompt = f"""Question: {question}

Retrieved contexts:
{ctx_text}

Score from 0.0 to 1.0 how relevant and useful these contexts are for answering the question.
1.0 = all contexts are highly relevant. 0.0 = all contexts are irrelevant.
Return ONLY a float number like: 0.75"""
        try:
            resp = await self.llm.complete(prompt, temperature=0.0)
            return float(resp.strip().split()[0])
        except Exception:
            return 0.5


# ── MiroFish EntityEnricher: Entity Summary Search Tool ─────────────────────

class EntitySummarySearchTool:
    """
    Searches entity-level LLM summaries (from EntityEnricher) as a second
    retrieval layer alongside chunk-level vector/BM25 search.

    When entity summaries exist (e.summary IS NOT NULL), this tool embeds
    the query and searches against them via BM25 text fallback or filters.
    Complements HybridSearchTool which searches raw chunk text.
    """

    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider) -> None:
        self.store = store
        self.llm = llm
        self.name = "entity_summary_search"
        self.description = (
            "Searches enriched entity profile summaries. "
            "Best for 'what is X?', 'tell me about Y', named-entity questions."
        )

    async def run(
        self,
        query: str,
        k: int = None,
        entity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find entities whose summaries are relevant to the query.

        Uses fulltext search on the chunk index to surface entity names,
        then fetches their summaries. Falls back to a simple CONTAINS match
        if fulltext gives no results.

        Args:
            query:       Natural language query
            k:           Max results (default from settings)
            entity_type: Optional filter by entity type

        Returns:
            List of context dicts with entity name, type, summary text
        """
        k = k or settings.default_top_k
        type_filter = "AND e.type = $entity_type" if entity_type else ""
        params: Dict[str, Any] = {"limit": k}
        if entity_type:
            params["entity_type"] = entity_type

        # Strategy 1: Use BM25 index to find relevant entities via chunk→entity links
        results: List[Dict[str, Any]] = []
        try:
            bm25_cypher = f"""
            CALL db.index.fulltext.queryNodes('chunk_text_index', $query)
            YIELD node, score
            MATCH (node)-[:MENTIONS]->(e:Entity)
            WHERE e.summary IS NOT NULL AND e.summary <> ''
            {type_filter}
            RETURN DISTINCT e.name as name, e.type as type, e.summary as summary,
                   score
            ORDER BY score DESC
            LIMIT $limit
            """
            params["query"] = query
            rows = await self.store.execute_query(bm25_cypher, params)
            for r in rows:
                results.append({
                    "id": f"entity_summary:{r['name']}",
                    "text": f"[Entity: {r['name']} ({r['type']})] {r['summary']}",
                    "entity_name": r["name"],
                    "entity_type": r.get("type", "Entity"),
                    "summary": r["summary"],
                    "score": r.get("score", 0.8),
                    "retrieval_method": "entity_summary",
                })
        except Exception as exc:
            print(f"[EntitySummarySearch BM25] {exc}")

        # Strategy 2: Fallback — keyword match on entity names in graph
        if not results:
            try:
                words = [w for w in query.split() if len(w) > 3][:5]
                if words:
                    conditions = " OR ".join(
                        f"toLower(e.name) CONTAINS toLower('{w}')" for w in words
                    )
                    fallback_cypher = f"""
                    MATCH (e:Entity)
                    WHERE ({conditions}) AND e.summary IS NOT NULL AND e.summary <> ''
                    {type_filter}
                    RETURN e.name as name, e.type as type, e.summary as summary
                    LIMIT $limit
                    """
                    rows = await self.store.execute_query(fallback_cypher, params)
                    for r in rows:
                        results.append({
                            "id": f"entity_summary:{r['name']}",
                            "text": f"[Entity: {r['name']} ({r['type']})] {r['summary']}",
                            "entity_name": r["name"],
                            "entity_type": r.get("type", "Entity"),
                            "summary": r["summary"],
                            "score": 0.6,
                            "retrieval_method": "entity_summary_fallback",
                        })
            except Exception as exc:
                print(f"[EntitySummarySearch fallback] {exc}")

        return results[:k]
