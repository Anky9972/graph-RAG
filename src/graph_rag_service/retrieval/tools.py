"""
Retrieval tools for the agentic system
Vector search, graph traversal, and filter-based retrieval
"""

from typing import List, Dict, Any, Optional
import json

from ..core.neo4j_store import Neo4jStore
from ..core.llm_factory import UnifiedLLMProvider
from ..core.models import OntologySchema
from ..config import settings


class VectorSearchTool:
    """Vector similarity search tool"""
    
    def __init__(self, store: Neo4jStore, llm: UnifiedLLMProvider):
        self.store = store
        self.llm = llm
        self.name = "vector_search"
        self.description = "Search for semantically similar content using vector embeddings"
    
    async def run(
        self,
        query: str,
        k: int = None,
        filter: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform vector similarity search
        
        Args:
            query: Search query
            k: Number of results
            filter: Optional metadata filters
            
        Returns:
            List of similar chunks with scores
        """
        
        k = k or settings.default_top_k
        
        # Generate query embedding
        query_embedding = await self.llm.embed(query)
        
        # Search vector store
        results = await self.store.search(
            query_vector=query_embedding,
            k=k,
            filter=filter
        )
        
        return results


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
        """
        Traverse graph based on query
        
        Args:
            query: Natural language query
            source_entity: Starting entity (extracted from query if None)
            target_entity: Target entity (extracted from query if None)
            depth: Traversal depth
            
        Returns:
            Graph traversal results
        """
        
        depth = depth or settings.graph_max_depth
        
        # Extract entities from query if not provided
        if not source_entity or not target_entity:
            entities = await self._extract_entities_from_query(query)
            if len(entities) >= 2:
                source_entity = source_entity or entities[0]
                target_entity = target_entity or entities[1]
            elif len(entities) == 1:
                source_entity = source_entity or entities[0]
        
        # Find paths or get neighbors
        if source_entity and target_entity:
            results = await self.store.find_path(source_entity, target_entity, depth)
        elif source_entity:
            results = await self.store.get_neighbors(source_entity, depth)
        else:
            results = []
        
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
        except:
            return []


class CypherGenerationTool:
    """
    Text-to-Cypher tool with hallucination guards
    Generates Cypher queries from natural language
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
        self.description = "Generate and execute Cypher queries for complex graph queries"
    
    async def run(self, query: str) -> List[Dict[str, Any]]:
        """
        Generate and execute Cypher query
        
        Args:
            query: Natural language query
            
        Returns:
            Query results
        """
        
        # Generate Cypher
        cypher = await self._generate_cypher(query)
        
        if not cypher:
            return []
        
        # Validate Cypher against schema
        if not self._validate_cypher(cypher):
            # Try self-correction
            cypher = await self._correct_cypher(cypher, query)
            if not self._validate_cypher(cypher):
                return []
        
        # Execute query
        try:
            results = await self.store.execute_query(cypher)
            return results
        except Exception as e:
            # Self-correcting Cypher on error
            print(f"Cypher execution error: {e}")
            cypher = await self._correct_cypher_with_error(cypher, query, str(e))
            try:
                results = await self.store.execute_query(cypher)
                return results
            except:
                return []
    
    async def _generate_cypher(self, query: str) -> str:
        """Generate Cypher query from natural language"""
        
        schema_info = ""
        if self.ontology:
            schema_info = f"""
Graph Schema:
- Entity Types: {', '.join(self.ontology.entity_types)}
- Relationship Types: {', '.join(self.ontology.relationship_types)}
"""
        
        prompt = f"""
You are a Cypher query generator. Generate a Cypher query for Neo4j that answers this question:

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
        
        system_prompt = "You generate syntactically correct Cypher queries for Neo4j."
        
        response = await self.llm.complete(prompt, system_prompt=system_prompt, temperature=0.1)
        
        # Extract Cypher from response
        cypher = response.strip()
        if "```cypher" in cypher:
            cypher = cypher.split("```cypher")[1].split("```")[0]
        elif "```" in cypher:
            cypher = cypher.split("```")[1].split("```")[0]
        
        return cypher.strip()
    
    def _validate_cypher(self, cypher: str) -> bool:
        """Validate Cypher syntax and schema compliance"""
        
        if not cypher:
            return False
        
        # Basic validation
        cypher_upper = cypher.upper()
        if "MATCH" not in cypher_upper and "CREATE" not in cypher_upper:
            return False
        
        # Don't allow dangerous operations in read queries
        dangerous_keywords = ["DELETE", "DETACH DELETE", "DROP", "REMOVE"]
        for keyword in dangerous_keywords:
            if keyword in cypher_upper:
                return False
        
        # Validate against ontology if available
        if self.ontology:
            # Check entity types
            for entity_type in self.ontology.entity_types:
                if f":{entity_type}" in cypher or f":{entity_type})" in cypher:
                    continue
            
            # Check relationship types
            for rel_type in self.ontology.relationship_types:
                if f":{rel_type}" in cypher or f"[:{rel_type}]" in cypher:
                    continue
        
        return True
    
    async def _correct_cypher(self, cypher: str, query: str) -> str:
        """Attempt to correct invalid Cypher"""
        
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
    
    async def _correct_cypher_with_error(
        self,
        cypher: str,
        query: str,
        error: str
    ) -> str:
        """Self-correcting Cypher with error feedback"""
        
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
        """
        Filter by metadata
        
        Args:
            filters: Dictionary of filter conditions
            limit: Maximum results
            
        Returns:
            Filtered results
        """
        
        # Build WHERE clause from filters
        where_clauses = []
        params = {}
        
        for i, (key, value) in enumerate(filters.items()):
            param_name = f"param_{i}"
            if isinstance(value, str):
                where_clauses.append(f"n.{key} = ${param_name}")
            elif isinstance(value, list):
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
        return results
