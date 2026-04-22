"""
Neo4j implementation of GraphStore and VectorStore
Extended with:
  - Gap #1: BM25 fulltext index for hybrid search
  - Gap #2: Community detection queries
  - Gap #5: Temporal relationship support
  - Gap #7: Multi-tenant namespace isolation
"""

import asyncio
from typing import List, Dict, Any, Optional
from neo4j import AsyncGraphDatabase, AsyncDriver
import uuid
from datetime import datetime

from .abstractions import GraphStore, VectorStore
from .models import Entity, Relationship, Chunk
from ..config import settings
import logging

logging.getLogger("neo4j").setLevel(logging.ERROR)


class Neo4jStore(GraphStore, VectorStore):
    """
    Unified Neo4j implementation for both graph and vector storage
    Uses Neo4j 5.x vector search + fulltext capabilities
    """

    def __init__(
        self,
        uri: str = None,
        user: str = None,
        password: str = None,
        database: str = None
    ):
        self.uri = uri or settings.neo4j_uri
        self.user = user or settings.neo4j_user
        self.password = password or settings.neo4j_password
        self.database = database or settings.neo4j_database
        self.driver: Optional[AsyncDriver] = None

    async def connect(self) -> None:
        """Establish connection to Neo4j"""
        self.driver = AsyncGraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password)
        )
        await self._create_vector_index()
        await self._create_fulltext_index()   # Gap #1 — BM25
        await self._create_constraints()

    async def disconnect(self) -> None:
        """Close connection to Neo4j"""
        if self.driver:
            await self.driver.close()

    # ── Index creation ────────────────────────────────────────────────────────

    async def _create_vector_index(self) -> None:
        """Create vector index for semantic search"""
        query = """
        CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
        FOR (c:Chunk)
        ON c.embedding
        OPTIONS {indexConfig: {
            `vector.dimensions`: $dimension,
            `vector.similarity_function`: 'cosine'
        }}
        """
        async with self.driver.session(database=self.database) as session:
            try:
                await session.run(query, dimension=settings.embedding_dimension)
            except Exception as e:
                print(f"Vector index creation: {e}")

    async def _create_fulltext_index(self) -> None:
        """
        Gap #1 — Create BM25 fulltext index for hybrid search
        Neo4j 5.x supports FULLTEXT indexes natively with Lucene scoring
        """
        query = """
        CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS
        FOR (c:Chunk)
        ON EACH [c.text]
        """
        async with self.driver.session(database=self.database) as session:
            try:
                await session.run(query)
            except Exception as e:
                print(f"Fulltext index creation: {e}")

    async def _create_constraints(self) -> None:
        """Create constraints and indexes for performance"""
        constraints = [
            "CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE",
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
            "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
            "CREATE INDEX chunk_document IF NOT EXISTS FOR (c:Chunk) ON (c.document_id)",
            # Gap #5 — Temporal indexes
            "CREATE INDEX entity_valid_from IF NOT EXISTS FOR (e:Entity) ON (e.valid_from)",
            # Gap #7 — Tenant isolation index
            "CREATE INDEX entity_tenant IF NOT EXISTS FOR (e:Entity) ON (e.tenant_id)",
        ]
        async with self.driver.session(database=self.database) as session:
            for constraint in constraints:
                try:
                    await session.run(constraint)
                except Exception:
                    pass

    # ── GraphStore methods ────────────────────────────────────────────────────

    async def create_node(self, entity: Entity) -> str:
        """Create an entity node in the graph with temporal + tenant support"""
        import json
        node_id = entity.id or str(uuid.uuid4())

        query = """
        MERGE (e:Entity {name: $name})
        SET e.type = $type,
            e.properties = $properties,
            e.ontology_version = $ontology_version,
            e.confidence = $confidence,
            e.id = $id,
            e.tenant_id = $tenant_id,
            e.community_id = $community_id,
            e.valid_from = $valid_from,
            e.valid_until = $valid_until,
            e.ingested_at = datetime()
        RETURN e.id as id
        """

        async with self.driver.session(database=self.database) as session:
            result = await session.run(
                query,
                name=entity.name,
                type=entity.type,
                properties=json.dumps(entity.properties) if entity.properties else "{}",
                ontology_version=entity.ontology_version,
                confidence=entity.confidence,
                id=node_id,
                tenant_id=entity.tenant_id or settings.default_tenant_id,
                community_id=entity.community_id,
                valid_from=entity.valid_from.isoformat() if entity.valid_from else None,
                valid_until=entity.valid_until.isoformat() if entity.valid_until else None,
            )
            record = await result.single()
            return record["id"] if record else node_id

    async def create_relationship(self, relationship: Relationship) -> str:
        """Create a relationship between entities with temporal support (Gap #5)"""
        import json
        rel_id = str(uuid.uuid4())

        query = """
        MATCH (source:Entity {name: $source})
        MATCH (target:Entity {name: $target})
        MERGE (source)-[r:%s]->(target)
        SET r.properties = $properties,
            r.confidence = $confidence,
            r.ontology_version = $ontology_version,
            r.id = $id,
            r.valid_from = $valid_from,
            r.valid_until = $valid_until,
            r.source_document_id = $source_document_id,
            r.source_chunk_id = $source_chunk_id,
            r.tenant_id = $tenant_id,
            r.ingested_at = datetime()
        RETURN r.id as id
        """ % relationship.type

        async with self.driver.session(database=self.database) as session:
            result = await session.run(
                query,
                source=relationship.source,
                target=relationship.target,
                properties=json.dumps(relationship.properties) if relationship.properties else "{}",
                confidence=relationship.confidence,
                ontology_version=relationship.ontology_version,
                id=rel_id,
                valid_from=relationship.valid_from.isoformat() if relationship.valid_from else None,
                valid_until=relationship.valid_until.isoformat() if relationship.valid_until else None,
                source_document_id=relationship.source_document_id,
                source_chunk_id=relationship.source_chunk_id,
                tenant_id=relationship.tenant_id or settings.default_tenant_id,
            )
            record = await result.single()
            return record["id"] if record else rel_id

    async def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute a Cypher query"""
        params = params or {}
        async with self.driver.session(database=self.database) as session:
            result = await session.run(query, parameters=params)
            records = await result.data()
            return records

    async def find_path(
        self,
        source: str,
        target: str,
        max_depth: int = 3
    ) -> List[Dict[str, Any]]:
        """Find paths between two entities"""
        query = """
        MATCH path = (source:Entity {name: $source})-[*1..%d]-(target:Entity {name: $target})
        RETURN [node in nodes(path) | {name: node.name, type: node.type}] as nodes,
               [rel in relationships(path) | type(rel)] as relationships,
               length(path) as length
        ORDER BY length
        LIMIT 5
        """ % max_depth

        async with self.driver.session(database=self.database) as session:
            result = await session.run(query, source=source, target=target)
            paths = await result.data()
            return paths

    async def get_neighbors(
        self,
        entity_name: str,
        depth: int = 1
    ) -> List[Dict[str, Any]]:
        """Get neighboring entities"""
        query = """
        MATCH (e:Entity {name: $name})-[r*1..%d]-(neighbor:Entity)
        RETURN DISTINCT neighbor.name as name,
               neighbor.type as type,
               neighbor.properties as properties
        LIMIT 50
        """ % depth

        async with self.driver.session(database=self.database) as session:
            result = await session.run(query, name=entity_name)
            neighbors = await result.data()
            return neighbors

    async def merge_entities(self, entity1_id: str, entity2_id: str) -> str:
        """Merge duplicate entities"""
        query = """
        MATCH (e1:Entity {id: $id1})
        MATCH (e2:Entity {id: $id2})

        SET e1.properties = e1.properties + e2.properties

        WITH e1, e2
        MATCH (e2)-[r]->(other)
        MERGE (e1)-[r2:RELATED_TO]->(other)
        SET r2 = properties(r)

        WITH e1, e2
        MATCH (other)-[r]->(e2)
        MERGE (other)-[r2:RELATED_TO]->(e1)
        SET r2 = properties(r)

        WITH e1, e2
        DETACH DELETE e2

        RETURN e1.id as id
        """
        async with self.driver.session(database=self.database) as session:
            result = await session.run(query, id1=entity1_id, id2=entity2_id)
            record = await result.single()
            return record["id"]

    # ── Gap #1: BM25 Fulltext search ──────────────────────────────────────────

    async def bm25_search(
        self,
        query_text: str,
        k: int = 10,
        document_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        BM25 fulltext (Lucene) search over chunk text.
        Returns results with BM25 score for RRF fusion.
        """
        if document_id:
            cypher = """
            CALL db.index.fulltext.queryNodes('chunk_text_index', $query)
            YIELD node, score
            WHERE node.document_id = $doc_id
            RETURN node.id as id,
                   node.text as text,
                   node.document_id as document_id,
                   node.chunk_index as chunk_index,
                   score
            LIMIT $k
            """
            params = {"query": query_text, "doc_id": document_id, "k": k}
        else:
            cypher = """
            CALL db.index.fulltext.queryNodes('chunk_text_index', $query)
            YIELD node, score
            RETURN node.id as id,
                   node.text as text,
                   node.document_id as document_id,
                   node.chunk_index as chunk_index,
                   score
            LIMIT $k
            """
            params = {"query": query_text, "k": k}

        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(cypher, parameters=params)
                records = await result.data()
                return records
        except Exception as e:
            print(f"BM25 search error: {e}")
            return []

    # ── Gap #2: Community Detection ───────────────────────────────────────────

    async def get_communities(
        self,
        entity_names: List[str],
        tenant_id: Optional[str] = None
    ) -> Dict[int, List[Dict[str, Any]]]:
        """
        Get community groupings for a list of entities.
        Uses community_id property stored on entities (assigned during ingestion
        or via background Louvain task).
        Returns {community_id: [entity_dict, ...]}
        """
        tenant_filter = "AND e.tenant_id = $tenant_id" if tenant_id else ""
        query = f"""
        MATCH (e:Entity)
        WHERE e.name IN $names {tenant_filter}
          AND e.community_id IS NOT NULL
        RETURN e.community_id as community_id,
               collect({{name: e.name, type: e.type, properties: e.properties}}) as entities
        ORDER BY size(collect(e)) DESC
        LIMIT 10
        """
        params: Dict[str, Any] = {"names": entity_names}
        if tenant_id:
            params["tenant_id"] = tenant_id

        try:
            rows = await self.execute_query(query, params)
            result: Dict[int, List[Dict]] = {}
            for row in rows:
                result[row["community_id"]] = row["entities"]
            return result
        except Exception as e:
            print(f"Community query error: {e}")
            return {}

    async def get_community_entities(
        self,
        community_id: int,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get all entities in a community"""
        query = """
        MATCH (e:Entity {community_id: $community_id})
        OPTIONAL MATCH (e)-[r]-(neighbor:Entity)
        RETURN e.name as name, e.type as type, e.properties as properties,
               collect(DISTINCT {name: neighbor.name, rel: type(r)}) as connections
        LIMIT $limit
        """
        return await self.execute_query(query, {"community_id": community_id, "limit": limit})

    async def assign_community_ids(self) -> int:
        """
        Simple community assignment using connected components (WCC).
        Each disconnected entity cluster gets a unique community_id.
        This is a lightweight substitute for Louvain when Neo4j GDS is not available.
        Returns number of communities found.
        """
        # Use in-memory approach: find all entity pairs via relationships
        # and assign sequential community IDs using Union-Find
        all_entities_query = "MATCH (e:Entity) RETURN e.name as name, e.id as id"
        all_rels_query = """
        MATCH (a:Entity)-[r]-(b:Entity)
        RETURN a.name as a, b.name as b
        """
        try:
            entities = await self.execute_query(all_entities_query)
            rels = await self.execute_query(all_rels_query)

            if not entities:
                return 0

            # Union-Find
            parent: Dict[str, str] = {e["name"]: e["name"] for e in entities}

            def find(x: str) -> str:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(a: str, b: str):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb

            for rel in rels:
                if rel["a"] in parent and rel["b"] in parent:
                    union(rel["a"], rel["b"])

            # Map root → community int id
            root_to_id: Dict[str, int] = {}
            counter = 0
            entity_community: Dict[str, int] = {}
            for e in entities:
                root = find(e["name"])
                if root not in root_to_id:
                    root_to_id[root] = counter
                    counter += 1
                entity_community[e["name"]] = root_to_id[root]

            # Write community_ids back to Neo4j in batches
            batch_size = 100
            items = list(entity_community.items())
            for i in range(0, len(items), batch_size):
                batch = [{"name": n, "cid": c} for n, c in items[i:i + batch_size]]
                update_query = """
                UNWIND $batch as item
                MATCH (e:Entity {name: item.name})
                SET e.community_id = item.cid
                """
                await self.execute_query(update_query, {"batch": batch})

            return counter
        except Exception as e:
            print(f"Community assignment error: {e}")
            return 0

    # ── Gap #5: Temporal queries ──────────────────────────────────────────────

    async def get_entities_at_time(
        self,
        entity_name: str,
        at_time: datetime,
        tenant_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get relationships valid at a specific point in time"""
        tenant_filter = "AND r.tenant_id = $tenant_id" if tenant_id else ""
        query = f"""
        MATCH (e:Entity {{name: $name}})-[r]->(other:Entity)
        WHERE (r.valid_from IS NULL OR r.valid_from <= $at_time)
          AND (r.valid_until IS NULL OR r.valid_until >= $at_time)
          {tenant_filter}
        RETURN other.name as entity, type(r) as relationship,
               r.valid_from as valid_from, r.valid_until as valid_until,
               r.confidence as confidence
        """
        params: Dict[str, Any] = {"name": entity_name, "at_time": at_time.isoformat()}
        if tenant_id:
            params["tenant_id"] = tenant_id
        return await self.execute_query(query, params)

    # ── VectorStore methods ───────────────────────────────────────────────────

    async def add_vectors(
        self,
        vectors: List[List[float]],
        metadata: List[Dict[str, Any]],
        ids: Optional[List[str]] = None
    ) -> List[str]:
        """Add chunk vectors to Neo4j"""
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in vectors]

        query = """
        UNWIND $batch as item
        MERGE (c:Chunk {id: item.id})
        SET c.text = item.text,
            c.document_id = item.document_id,
            c.embedding = item.embedding,
            c.chunk_index = item.chunk_index,
            c.page_number = item.page_number,
            c.section_title = item.section_title

        WITH c, item
        MATCH (d:Document {id: item.document_id})
        MERGE (d)-[:CONTAINS]->(c)

        RETURN c.id as id
        """

        batch = [
            {
                "id": ids[i],
                "text": metadata[i].get("text", ""),
                "document_id": metadata[i].get("document_id", ""),
                "embedding": vectors[i],
                "metadata": metadata[i],
                "chunk_index": metadata[i].get("chunk_index", i),
                "page_number": metadata[i].get("page_number"),
                "section_title": metadata[i].get("section_title"),
            }
            for i in range(len(vectors))
        ]

        async with self.driver.session(database=self.database) as session:
            result = await session.run(query, batch=batch)
            records = await result.data()
            return [r["id"] for r in records]

    async def search(
        self,
        query_vector: List[float],
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Vector similarity search using Neo4j vector index"""
        base_query = """
        CALL db.index.vector.queryNodes('chunk_embeddings', $k, $query_vector)
        YIELD node, score
        RETURN node.id as id,
               node.text as text,
               node.document_id as document_id,
               node.chunk_index as chunk_index,
               node.page_number as page_number,
               node.section_title as section_title,
               score
        """

        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(
                    base_query,
                    query_vector=query_vector,
                    k=k
                )
                results = await result.data()
                # Apply client-side filter if provided
                if filter and results:
                    for key, value in filter.items():
                        results = [r for r in results if str(r.get(key, "")) == str(value)]
                return results
        except Exception as e:
            print(f"Vector search not available: {e}")
            return await self._fallback_search(k)

    async def _fallback_search(self, k: int) -> List[Dict[str, Any]]:
        """Fallback search without vector index"""
        query = """
        MATCH (c:Chunk)
        RETURN c.id as id,
               c.text as text,
               c.document_id as document_id,
               c.chunk_index as chunk_index,
               0.5 as score
        LIMIT $k
        """
        async with self.driver.session(database=self.database) as session:
            result = await session.run(query, k=k)
            return await result.data()

    async def delete_vectors(self, ids: List[str]) -> None:
        """Delete chunks by ID"""
        query = """
        UNWIND $ids as id
        MATCH (c:Chunk {id: id})
        DETACH DELETE c
        """
        async with self.driver.session(database=self.database) as session:
            await session.run(query, ids=ids)

    # ── Ontology persistence ──────────────────────────────────────────────────

    async def save_ontology(self, ontology) -> None:
        """Persist ontology to Neo4j"""
        import json
        query = """
        MERGE (o:OntologyMeta {id: 'current'})
        SET o.version = $version,
            o.entity_types = $entity_types,
            o.relationship_types = $relationship_types,
            o.properties = $properties,
            o.created_at = $created_at,
            o.approved = $approved
        """
        async with self.driver.session(database=self.database) as session:
            await session.run(
                query,
                version=ontology.version,
                entity_types=ontology.entity_types,
                relationship_types=ontology.relationship_types,
                properties=json.dumps(ontology.properties),
                created_at=ontology.created_at.isoformat(),
                approved=ontology.approved
            )

    async def load_ontology(self):
        """Load persisted ontology from Neo4j. Returns OntologySchema or None."""
        import json
        from datetime import datetime
        from .models import OntologySchema
        query = """
        MATCH (o:OntologyMeta {id: 'current'})
        RETURN o.version as version,
               o.entity_types as entity_types,
               o.relationship_types as relationship_types,
               o.properties as properties,
               o.created_at as created_at,
               o.approved as approved
        """
        async with self.driver.session(database=self.database) as session:
            result = await session.run(query)
            record = await result.single()
            if not record:
                return None
            return OntologySchema(
                version=record["version"],
                entity_types=record["entity_types"],
                relationship_types=record["relationship_types"],
                properties=json.loads(record["properties"]) if record["properties"] else {},
                created_at=datetime.fromisoformat(record["created_at"]),
                approved=record["approved"]
            )

    async def save_eval_result(self, result) -> str:
        """Persist an EvalResult to Neo4j for dashboard trending (Gap #8)"""
        node_id = str(uuid.uuid4())
        query = """
        CREATE (e:EvalResult {
            id: $id,
            question: $question,
            answer: $answer,
            faithfulness: $faithfulness,
            answer_relevancy: $answer_relevancy,
            context_precision: $context_precision,
            context_recall: $context_recall,
            overall_score: $overall_score,
            hallucination_detected: $hallucination_detected,
            timestamp: $timestamp,
            document_id: $document_id
        })
        RETURN e.id as id
        """
        await self.execute_query(query, {
            "id": node_id,
            "question": result.question,
            "answer": result.answer[:500],
            "faithfulness": result.faithfulness,
            "answer_relevancy": result.answer_relevancy,
            "context_precision": result.context_precision,
            "context_recall": result.context_recall,
            "overall_score": result.overall_score,
            "hallucination_detected": result.hallucination_detected,
            "timestamp": result.timestamp.isoformat(),
            "document_id": result.document_id,
        })
        return node_id

    async def get_eval_results(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve eval results for the dashboard (Gap #8)"""
        query = """
        MATCH (e:EvalResult)
        RETURN e.id as id, e.question as question, e.faithfulness as faithfulness,
               e.answer_relevancy as answer_relevancy, e.context_precision as context_precision,
               e.overall_score as overall_score, e.hallucination_detected as hallucination_detected,
               e.timestamp as timestamp, e.document_id as document_id
        ORDER BY e.timestamp DESC
        LIMIT $limit
        """
        return await self.execute_query(query, {"limit": limit})

    # ── Chunk + entity helpers ────────────────────────────────────────────────

    async def create_chunk_with_entities(
        self,
        chunk: Chunk,
        entities: List[Entity]
    ) -> str:
        """Create a chunk and link it to entities it mentions"""
        chunk_id = chunk.id or str(uuid.uuid4())

        chunk_query = """
        MERGE (c:Chunk {id: $id})
        SET c.text = $text,
            c.document_id = $document_id,
            c.metadata = $metadata,
            c.chunk_index = $chunk_index,
            c.embedding = $embedding,
            c.page_number = $page_number,
            c.section_title = $section_title
        RETURN c.id as id
        """

        async with self.driver.session(database=self.database) as session:
            import json
            await session.run(
                chunk_query,
                id=chunk_id,
                text=chunk.text,
                document_id=chunk.document_id,
                metadata=json.dumps(chunk.metadata) if chunk.metadata else "{}",
                chunk_index=chunk.chunk_index,
                embedding=chunk.embedding,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
            )

            for entity in entities:
                await self.create_node(entity)
                link_query = """
                MATCH (c:Chunk {id: $chunk_id})
                MATCH (e:Entity {name: $entity_name})
                MERGE (c)-[:MENTIONS]->(e)
                """
                await session.run(
                    link_query,
                    chunk_id=chunk_id,
                    entity_name=entity.name
                )

        return chunk_id

    # ── User Management methods ───────────────────────────────────────────────

    async def create_user(self, user_data: Dict[str, Any]) -> str:
        """Create a new user node in the graph"""
        query = """
        MERGE (u:User {username: $username})
        ON CREATE SET
            u.hashed_password = $hashed_password,
            u.email = $email,
            u.full_name = $full_name,
            u.disabled = $disabled,
            u.scopes = $scopes,
            u.tenant_id = $tenant_id,
            u.created_at = datetime()
        RETURN u.username as username
        """
        async with self.driver.session(database=self.database) as session:
            result = await session.run(
                query,
                username=user_data["username"],
                hashed_password=user_data["hashed_password"],
                email=user_data.get("email"),
                full_name=user_data.get("full_name"),
                disabled=user_data.get("disabled", False),
                scopes=user_data.get("scopes", ["read", "write"]),
                tenant_id=user_data.get("tenant_id", settings.default_tenant_id),
            )
            record = await result.single()
            if not record:
                raise ValueError(f"User {user_data['username']} already exists")
            return record["username"]

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get a user by username"""
        query = """
        MATCH (u:User {username: $username})
        RETURN u.username as username,
               u.hashed_password as hashed_password,
               u.email as email,
               u.full_name as full_name,
               u.disabled as disabled,
               u.scopes as scopes,
               u.tenant_id as tenant_id
        """
        async with self.driver.session(database=self.database) as session:
            result = await session.run(query, username=username)
            record = await result.single()
            if not record:
                return None
            return {
                "username": record["username"],
                "hashed_password": record["hashed_password"],
                "email": record["email"],
                "full_name": record["full_name"],
                "disabled": record["disabled"],
                "scopes": record["scopes"],
                "tenant_id": record.get("tenant_id", settings.default_tenant_id),
            }
