"""
Neo4j implementation of GraphStore and VectorStore
Uses Neo4j's built-in vector capabilities for unified storage
"""

import asyncio
from typing import List, Dict, Any, Optional
from neo4j import AsyncGraphDatabase, AsyncDriver
import uuid

from .abstractions import GraphStore, VectorStore
from .models import Entity, Relationship, Chunk
from ..config import settings


class Neo4jStore(GraphStore, VectorStore):
    """
    Unified Neo4j implementation for both graph and vector storage
    Uses Neo4j 5.x vector search capabilities
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
        
        # Create vector index for embeddings
        await self._create_vector_index()
        
        # Create constraints and indexes
        await self._create_constraints()
    
    async def disconnect(self) -> None:
        """Close connection to Neo4j"""
        if self.driver:
            await self.driver.close()
    
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
                # Index might already exist or Neo4j version doesn't support vectors
                print(f"Vector index creation: {e}")
    
    async def _create_constraints(self) -> None:
        """Create constraints and indexes for performance"""
        constraints = [
            "CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE",
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
            "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
            "CREATE INDEX chunk_document IF NOT EXISTS FOR (c:Chunk) ON (c.document_id)",
        ]
        
        async with self.driver.session(database=self.database) as session:
            for constraint in constraints:
                try:
                    await session.run(constraint)
                except Exception as e:
                    # Constraint might already exist
                    pass
    
    # GraphStore methods
    
    async def create_node(self, entity: Entity) -> str:
        """Create an entity node in the graph"""
        import json
        node_id = entity.id or str(uuid.uuid4())
        
        query = """
        MERGE (e:Entity {name: $name})
        SET e.type = $type,
            e.properties = $properties,
            e.ontology_version = $ontology_version,
            e.confidence = $confidence,
            e.id = $id
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
                id=node_id
            )
            record = await result.single()
            return record["id"] if record else node_id
    
    async def create_relationship(self, relationship: Relationship) -> str:
        """Create a relationship between entities"""
        import json
        rel_id = str(uuid.uuid4())
        
        query = """
        MATCH (source:Entity {name: $source})
        MATCH (target:Entity {name: $target})
        MERGE (source)-[r:%s]->(target)
        SET r.properties = $properties,
            r.confidence = $confidence,
            r.ontology_version = $ontology_version,
            r.id = $id
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
                id=rel_id
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
            result = await session.run(query, **params)
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
        
        // Merge properties
        SET e1.properties = e1.properties + e2.properties
        
        // Redirect relationships
        MATCH (e2)-[r]->(other)
        MERGE (e1)-[r2:RELATED_TO]->(other)
        SET r2 = properties(r)
        
        MATCH (other)-[r]->(e2)
        MERGE (other)-[r2:RELATED_TO]->(e1)
        SET r2 = properties(r)
        
        // Delete duplicate
        DETACH DELETE e2
        
        RETURN e1.id as id
        """
        
        async with self.driver.session(database=self.database) as session:
            result = await session.run(query, id1=entity1_id, id2=entity2_id)
            record = await result.single()
            return record["id"]
    
    # VectorStore methods
    
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
            c.chunk_index = item.chunk_index
        
        // Link to document
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
                "chunk_index": metadata[i].get("chunk_index", i)
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
        
        # For Neo4j versions with vector search support
        query = """
        CALL db.index.vector.queryNodes('chunk_embeddings', $k, $query_vector)
        YIELD node, score
        RETURN node.id as id,
               node.text as text,
               node.document_id as document_id,
               node.metadata as metadata,
               score
        """
        
        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(
                    query,
                    query_vector=query_vector,
                    k=k
                )
                results = await result.data()
                return results
        except Exception as e:
            # Fallback to simple retrieval if vector search not available
            print(f"Vector search not available: {e}")
            return await self._fallback_search(k)
    
    async def _fallback_search(self, k: int) -> List[Dict[str, Any]]:
        """Fallback search without vector index"""
        query = """
        MATCH (c:Chunk)
        RETURN c.id as id,
               c.text as text,
               c.document_id as document_id,
               c.metadata as metadata,
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
    
    # Helper methods for hybrid storage
    
    async def save_ontology(self, ontology) -> None:
        """Persist ontology to Neo4j so the API server can reload it after restart"""
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

    async def create_chunk_with_entities(
        self,
        chunk: Chunk,
        entities: List[Entity]
    ) -> str:
        """Create a chunk and link it to entities it mentions"""
        chunk_id = chunk.id or str(uuid.uuid4())
        
        # Create chunk
        chunk_query = """
        MERGE (c:Chunk {id: $id})
        SET c.text = $text,
            c.document_id = $document_id,
            c.metadata = $metadata,
            c.chunk_index = $chunk_index,
            c.embedding = $embedding
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
                embedding=chunk.embedding
            )
            
            # Link chunk to entities
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
