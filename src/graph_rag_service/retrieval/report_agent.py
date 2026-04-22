"""
ReportAgent — MiroFish Point 3: Full ReACT Analytical Agent
Replaces the 72-line stub with a complete ReACT (Reasoning + Acting) loop
powered by three specialized tools (InsightForge, PanoramaSearch, QuickSearch).

Architecture mirrors MiroFish's report_agent.py + zep_tools.py design:
- InsightForgeTool:   Hybrid broad-spectrum retriever (vector + graph + community)
- PanoramaSearchTool: Entity-type sweep for macro-level statistics
- QuickSearchTool:    Fast single-entity lookup with direct relationships
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider
from ..config import settings


# ── Result models ───────────────────────────────────────────────────────────

class ReportSection(BaseModel):
    title: str
    content: str


class ReportResult(BaseModel):
    topic: str
    executive_summary: str
    sections: Dict[str, str] = Field(default_factory=dict)
    key_entities: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    tool_calls_made: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    markdown: str = ""


# ── Specialized analytical tools ─────────────────────────────────────────────

class InsightForgeTool:
    """
    Broad-spectrum hybrid retriever: merges vector similarity + graph
    neighborhood + community summaries for cross-entity insights.
    Use for open-ended analytical questions.
    """
    name = "InsightForge"
    description = (
        "Hybrid broad-spectrum retriever combining vector similarity, graph "
        "neighborhood, and community summaries. Best for open-ended analysis."
    )

    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider) -> None:
        self.store = store
        self.llm = llm

    async def run(self, query: str, k: int = 8) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        # 1. Hybrid vector + BM25 chunk retrieval
        try:
            embedding = await self.llm.embed(query)
            bm25_task = self.store.bm25_search(query, k=k)
            vector_task = self.store.search(query_vector=embedding, k=k)
            bm25_r, vector_r = await asyncio.gather(
                bm25_task, vector_task, return_exceptions=True
            )
            for r in (bm25_r if not isinstance(bm25_r, Exception) else []):
                r["source"] = "bm25"
                results.append(r)
            for r in (vector_r if not isinstance(vector_r, Exception) else []):
                r["source"] = "vector"
                results.append(r)
        except Exception:
            pass

        # 2. Graph neighborhood of top chunk entities
        try:
            entity_query = """
            CALL db.index.fulltext.queryNodes('chunk_text_index', $q)
            YIELD node, score
            MATCH (node)-[:MENTIONS]->(e:Entity)
            RETURN DISTINCT e.name as name, e.summary as summary
            LIMIT 10
            """
            entity_rows = await self.store.execute_query(
                entity_query, {"q": query}
            )
            for row in entity_rows:
                if row.get("summary"):
                    results.append({
                        "text": f"[Entity Profile] {row['name']}: {row['summary']}",
                        "source": "entity_summary",
                        "retrieval_method": "insight_forge",
                    })
        except Exception:
            pass

        # 3. Community summaries
        try:
            community_query = """
            MATCH (e:Entity)
            WHERE e.community_id IS NOT NULL
            WITH e.community_id as cid, collect(e.name)[..5] as members
            RETURN cid, members
            ORDER BY size(members) DESC
            LIMIT 3
            """
            communities = await self.store.execute_query(community_query)
            for comm in communities:
                member_summary = ", ".join(comm.get("members", []))
                results.append({
                    "text": (
                        f"[Community {comm['cid']} — "
                        f"{len(comm.get('members', []))} entities]: "
                        f"{member_summary}"
                    ),
                    "source": "community",
                    "retrieval_method": "insight_forge",
                })
        except Exception:
            pass

        # Deduplicate by text
        seen: set = set()
        unique: List[Dict] = []
        for r in results:
            key = r.get("text", "")[:80]
            if key and key not in seen:
                seen.add(key)
                unique.append(r)

        return unique[:k]


class PanoramaSearchTool:
    """
    Macro-level entity sweep: returns all entities of a given type with
    statistics. Useful for 'How many X?', 'List all Y', 'What types of Z?'
    """
    name = "PanoramaSearch"
    description = (
        "Broad entity sweep returning all nodes of a specified type. "
        "Best for: counting, listing, macro-level statistics."
    )

    def __init__(self, store: Neo4jStore) -> None:
        self.store = store

    async def run(
        self, entity_type: str = "Entity", limit: int = 30
    ) -> List[Dict[str, Any]]:
        """Return entities of the given type with their summaries."""
        query = """
        MATCH (e:Entity)
        WHERE e.type = $type OR $type = 'Entity'
        RETURN e.name as name, e.type as type,
               e.summary as summary,
               COUNT { (e)--() } as degree
        ORDER BY degree DESC
        LIMIT $limit
        """
        try:
            rows = await self.store.execute_query(
                query, {"type": entity_type, "limit": limit}
            )
            results = []
            for r in rows:
                text = f"[{r.get('type', 'Entity')}] {r.get('name', '')}"
                if r.get("summary"):
                    text += f": {r['summary']}"
                results.append({
                    "text": text,
                    "name": r.get("name"),
                    "type": r.get("type"),
                    "degree": r.get("degree", 0),
                    "retrieval_method": "panorama_search",
                })
            return results
        except Exception as exc:
            print(f"[PanoramaSearch] Error: {exc}")
            return []


class QuickSearchTool:
    """
    Fast single-entity lookup by name with direct 1-hop relationships.
    Useful for 'Who is X?', 'What does Y do?', 'Tell me about Z'.
    """
    name = "QuickSearch"
    description = (
        "Fast entity lookup by name. Returns entity summary + direct "
        "relationships. Best for specific entity questions."
    )

    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider) -> None:
        self.store = store
        self.llm = llm

    async def run(self, entity_name: str) -> List[Dict[str, Any]]:
        """Look up an entity and return its profile + connections."""
        # Exact match first, then fuzzy BM25
        entity_query = """
        MATCH (e:Entity)
        WHERE e.name = $name OR toLower(e.name) CONTAINS toLower($name)
        RETURN e.name as name, e.type as type, e.summary as summary
        LIMIT 3
        """
        try:
            entities = await self.store.execute_query(
                entity_query, {"name": entity_name}
            )
        except Exception:
            entities = []

        results: List[Dict[str, Any]] = []
        for entity in entities:
            name = entity.get("name", entity_name)
            summary = entity.get("summary", "")
            entry: Dict[str, Any] = {
                "name": name,
                "type": entity.get("type", "Entity"),
                "retrieval_method": "quick_search",
            }

            # Get direct relationships
            rel_query = """
            MATCH (e:Entity {name: $name})-[r]-(other:Entity)
            RETURN type(r) as rel_type,
                   other.name as other_name,
                   other.type as other_type
            LIMIT 20
            """
            try:
                rels = await self.store.execute_query(
                    rel_query, {"name": name}
                )
                rel_lines = [
                    f"{r['rel_type']} → {r['other_name']} ({r['other_type']})"
                    for r in rels
                ]
                rel_text = "; ".join(rel_lines) if rel_lines else "no connections"
            except Exception:
                rel_text = "unavailable"

            text_parts = [f"[Entity] {name}"]
            if summary:
                text_parts.append(summary)
            text_parts.append(f"Connections: {rel_text}")
            entry["text"] = " | ".join(text_parts)
            results.append(entry)

        return results


# ── Main ReportAgent ──────────────────────────────────────────────────────────

class ReportAgent:
    """
    Full ReACT analytical reporting agent.

    Workflow:
      DECOMPOSE  → Break topic into 3-5 sub-questions
      REACT LOOP → For each sub-question:
                     THINK → pick best tool
                     ACT   → run InsightForge / PanoramaSearch / QuickSearch
                     OBS   → record retrieved context
                     WRITE → draft answer section
      COMPILE    → Assemble all sections into a structured markdown report
    """

    MAX_REACT_LOOPS = 6
    TOOLS_DESC = """
Available tools:
- InsightForge(query):           Hybrid broad-spectrum retriever. Best for analytical questions.
- PanoramaSearch(entity_type):   Sweep all entities of a type.  Best for counting/listing.
- QuickSearch(entity_name):      Fast entity lookup + connections. Best for "Who is X?" questions.
"""

    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider) -> None:
        self.store = store
        self.llm = llm
        self.insight_forge = InsightForgeTool(store, llm)
        self.panorama = PanoramaSearchTool(store)
        self.quick_search = QuickSearchTool(store, llm)
        self._tool_calls = 0

    # ── Public ─────────────────────────────────────────────────────────────

    async def generate_report(
        self,
        topic: str,
        report_type: Literal["executive", "detailed", "entity_focus"] = "detailed",
        target_entity: Optional[str] = None,
    ) -> ReportResult:
        """
        Generate an analytical report on the given topic.

        Args:
            topic:         High-level topic or question
            report_type:   "executive" (short), "detailed" (full), "entity_focus" (scoped)
            target_entity: For entity_focus — name of the entity to focus on

        Returns:
            ReportResult with sections, summary, and compiled markdown
        """
        self._tool_calls = 0

        # 1. Decompose topic into sub-questions
        sub_questions = await self._decompose_topic(
            topic, report_type, target_entity
        )

        # 2. ReACT loop for each sub-question
        sections: Dict[str, str] = {}
        all_contexts: List[str] = []
        key_entities: List[str] = []

        for question in sub_questions:
            section_content, contexts, entities = await self._react_loop(question)
            if section_content:
                sections[question] = section_content
            all_contexts.extend(contexts)
            key_entities.extend(entities)

        # 3. Executive summary
        exec_summary = await self._write_executive_summary(topic, sections)

        # 4. Key entities dedup
        key_entities = list(dict.fromkeys(key_entities))[:10]

        # 5. Confidence: proportion of sub-questions with substantive answers
        answered = sum(1 for v in sections.values() if len(v) > 50)
        confidence = round(answered / max(len(sub_questions), 1), 2)

        # 6. Compile markdown
        markdown = self._compile_markdown(
            topic, exec_summary, sections, key_entities
        )

        return ReportResult(
            topic=topic,
            executive_summary=exec_summary,
            sections=sections,
            key_entities=key_entities,
            confidence=confidence,
            tool_calls_made=self._tool_calls,
            markdown=markdown,
        )

    # ── Internal steps ─────────────────────────────────────────────────────

    async def _decompose_topic(
        self,
        topic: str,
        report_type: str,
        target_entity: Optional[str],
    ) -> List[str]:
        """Ask LLM to decompose the topic into sub-questions."""
        n = 3 if report_type == "executive" else 5
        focus = (
            f"Focus specifically on the entity '{target_entity}'."
            if target_entity
            else ""
        )
        prompt = f"""You are planning an analytical report about: "{topic}"
{focus}

Generate {n} specific sub-questions that would together create a complete report.
Each sub-question should be answerable from a knowledge graph.

Return ONLY a JSON list of strings:
["question 1", "question 2", ...]"""

        try:
            response = await self.llm.complete(prompt, temperature=0.3)
            cleaned = response.strip()
            for marker in ("```json", "```"):
                if marker in cleaned:
                    cleaned = cleaned.split(marker)[1].split("```")[0]
            questions = json.loads(cleaned.strip())
            if isinstance(questions, list) and questions:
                return [str(q) for q in questions[:n]]
        except Exception:
            pass
        # Fallback
        return [
            f"What are the main entities related to {topic}?",
            f"What are the key relationships in {topic}?",
            f"What are the most important findings about {topic}?",
        ]

    async def _react_loop(
        self, question: str
    ) -> tuple[str, List[str], List[str]]:
        """
        Run a ReACT iteration for one sub-question.
        Returns (section_content, context_texts, entity_names).
        """
        collected_contexts: List[str] = []
        entity_names: List[str] = []
        observations: List[str] = []

        for step in range(self.MAX_REACT_LOOPS):
            # THINK: which tool next?
            tool_name, tool_arg = await self._think(
                question, observations
            )

            if tool_name == "DONE":
                break

            # ACT: run the chosen tool
            tool_results = await self._act(tool_name, tool_arg)
            self._tool_calls += 1

            if tool_results:
                obs_texts = [r.get("text", str(r))[:300] for r in tool_results]
                obs_summary = "\n".join(f"• {t}" for t in obs_texts[:5])
                observations.append(f"[{tool_name}({tool_arg})]\n{obs_summary}")
                collected_contexts.extend(obs_texts)

                # Collect entity names
                for r in tool_results:
                    if r.get("name"):
                        entity_names.append(r["name"])
            else:
                observations.append(f"[{tool_name}({tool_arg})] No results.")
                break

        # WRITE: draft the section answer
        if collected_contexts:
            section = await self._write_section(question, collected_contexts)
        else:
            section = "Insufficient data found in the knowledge graph."

        return section, collected_contexts, entity_names

    async def _think(
        self, question: str, observations: List[str]
    ) -> tuple[str, str]:
        """Decide which tool to call next, or return DONE."""
        obs_text = "\n".join(observations[-3:]) if observations else "None yet."

        prompt = f"""You are choosing the next retrieval action to answer:
"{question}"

{self.TOOLS_DESC}
Observations so far:
{obs_text}

If you have enough information to write a good answer, respond with exactly: DONE
Otherwise respond with: TOOL_NAME(argument)
Examples:
  InsightForge(economic impact of climate policy)
  PanoramaSearch(Organization)
  QuickSearch(Tesla)
  DONE

Your response (one line only):"""

        try:
            response = await self.llm.complete(prompt, temperature=0.1)
            line = response.strip().split("\n")[0].strip()

            if line.upper() == "DONE" or not line:
                return "DONE", ""

            # Parse TOOL_NAME(argument)
            if "(" in line and line.endswith(")"):
                tool_raw = line[:line.index("(")].strip()
                arg = line[line.index("(") + 1 : -1].strip()
                # Normalize tool name
                tool_map = {
                    "insightforge": "InsightForge",
                    "panoramasearch": "PanoramaSearch",
                    "quicksearch": "QuickSearch",
                }
                tool_name = tool_map.get(tool_raw.lower(), "InsightForge")
                return tool_name, arg

            return "DONE", ""
        except Exception:
            return "DONE", ""

    async def _act(
        self, tool_name: str, tool_arg: str
    ) -> List[Dict[str, Any]]:
        """Dispatch tool call and return results."""
        try:
            if tool_name == "InsightForge":
                return await self.insight_forge.run(tool_arg)
            elif tool_name == "PanoramaSearch":
                return await self.panorama.run(tool_arg)
            elif tool_name == "QuickSearch":
                return await self.quick_search.run(tool_arg)
        except Exception as exc:
            print(f"[ReportAgent] Tool {tool_name} failed: {exc}")
        return []

    async def _write_section(
        self, question: str, contexts: List[str]
    ) -> str:
        """Generate a report section from retrieved contexts."""
        context_text = "\n\n".join(f"[Source {i+1}]: {c}" for i, c in enumerate(contexts[:8]))

        prompt = f"""Write a factual, well-structured paragraph answering:
"{question}"

Based ONLY on the following knowledge graph data:
{context_text}

Instructions:
- Be specific and cite entities by name
- Do not hallucinate or add information not in the sources
- 2-4 sentences is ideal
- If the data is insufficient, say so"""

        try:
            return await self.llm.complete(
                prompt,
                system_prompt="You are an analytical writer crafting a knowledge-graph report section.",
                temperature=0.3,
            )
        except Exception:
            return "Unable to generate section due to LLM error."

    async def _write_executive_summary(
        self, topic: str, sections: Dict[str, str]
    ) -> str:
        """Synthesize all sections into a 3-sentence executive summary."""
        section_text = "\n\n".join(
            f"## {q}\n{a}" for q, a in list(sections.items())[:5]
        )
        prompt = f"""Write a 2-3 sentence executive summary for a report on: "{topic}"

Report findings:
{section_text[:2000]}

Executive summary (concise, factual, highlight the most important finding):"""
        try:
            return await self.llm.complete(prompt, temperature=0.3)
        except Exception:
            return f"Analysis of {topic} based on knowledge graph data."

    def _compile_markdown(
        self,
        topic: str,
        exec_summary: str,
        sections: Dict[str, str],
        key_entities: List[str],
    ) -> str:
        lines = [
            f"# Report: {topic}",
            f"*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*\n",
            "## Executive Summary",
            exec_summary,
            "",
        ]
        for question, content in sections.items():
            lines.append(f"## {question}")
            lines.append(content)
            lines.append("")

        if key_entities:
            lines.append("## Key Entities Referenced")
            lines.append(", ".join(key_entities))

        return "\n".join(lines)
