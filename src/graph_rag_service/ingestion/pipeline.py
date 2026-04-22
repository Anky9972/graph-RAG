"""
Complete ingestion pipeline
Orchestrates document processing, extraction, and graph construction
"""

from pathlib import Path
from typing import List, Optional
import asyncio

from .document_processor import DocumentProcessor
from .ontology_generator import OntologyGenerator
from .extractor import KnowledgeExtractor
from ..core.neo4j_store import Neo4jStore
from ..core.models import Document, OntologySchema, ExtractionResult
from ..config import settings


class IngestionPipeline:
    """
    End-to-end ingestion pipeline:
    1. Process document -> chunks
    2. Generate/use ontology
    3. Extract entities and relationships
    4. Resolve duplicates
    5. Store in graph + vector store
    """
    
    def __init__(
        self,
        graph_store: Optional[Neo4jStore] = None,
        llm_provider: Optional[str] = None
    ):
        self.document_processor = DocumentProcessor()
        self.ontology_generator = OntologyGenerator(llm_provider)
        self.extractor = KnowledgeExtractor(llm_provider)
        self.graph_store = graph_store
        self._ontology: Optional[OntologySchema] = None
    
    async def initialize(self):
        """Initialize connections"""
        if self.graph_store:
            await self.graph_store.connect()
    
    async def close(self):
        """Close connections"""
        if self.graph_store:
            await self.graph_store.disconnect()
    
    async def ingest_document(
        self,
        file_path: Path,
        ontology: Optional[OntologySchema] = None,
        store_results: bool = True,
        progress_callback=None
    ) -> ExtractionResult:
        """
        Ingest a single document through the full pipeline
        
        Args:
            file_path: Path to document
            ontology: Optional ontology (will generate if None)
            store_results: Whether to store in graph database
            
        Returns:
            Extraction result
        """
        
        # Step 1: Process document
        print(f"Processing document: {file_path.name}")
        document = await self.document_processor.process_document(file_path)
        chunks = await self.document_processor.chunk_document(document)
        
        if not chunks:
            raise ValueError("No chunks extracted from document")
        
        print(f"Created {len(chunks)} chunks")
        
        # Step 2: Generate or use ontology
        if ontology is None:
            if self._ontology is None:
                print("Generating ontology from sample chunks...")
                self._ontology = await self.ontology_generator.generate_initial_ontology(
                    chunks[:5]
                )
                print(f"Generated ontology v{self._ontology.version}")
                print(f"Entity types: {', '.join(self._ontology.entity_types)}")
                print(f"Relationship types: {', '.join(self._ontology.relationship_types)}")
                # Persist ontology to Neo4j so the API server can load it
                if self.graph_store:
                    await self.graph_store.save_ontology(self._ontology)
            ontology = self._ontology
        
        # Step 3: Extract entities and relationships
        print("Extracting entities and relationships...")
        extraction_result = await self.extractor.extract_from_chunks(
            chunks,
            ontology=ontology,
            resolve_entities=True,
            progress_callback=progress_callback
        )
        
        print(f"Extracted {len(extraction_result.entities)} entities")
        print(f"Extracted {len(extraction_result.relationships)} relationships")
        
        # Step 4: Generate embeddings
        print("Generating embeddings...")
        chunks_with_embeddings = await self.extractor.generate_embeddings(chunks)
        extraction_result.chunks = chunks_with_embeddings
        
        # Step 5: Store in graph database
        if store_results and self.graph_store:
            print("Storing in graph database...")
            await self._store_extraction(document, extraction_result)
            print("Storage complete")
        
        return extraction_result
    
    async def ingest_documents(
        self,
        file_paths: List[Path],
        ontology: Optional[OntologySchema] = None
    ) -> List[ExtractionResult]:
        """
        Ingest multiple documents
        
        Args:
            file_paths: List of document paths
            ontology: Optional ontology to use
            
        Returns:
            List of extraction results
        """
        
        results = []
        
        for file_path in file_paths:
            try:
                result = await self.ingest_document(file_path, ontology)
                results.append(result)
            except Exception as e:
                print(f"Failed to ingest {file_path}: {e}")
        
        return results
    
    async def _store_extraction(
        self,
        document: Document,
        extraction: ExtractionResult
    ) -> None:
        """Store extraction results in graph database"""
        
        # Store document node
        doc_query = """
        MERGE (d:Document {id: $id})
        SET d.filename = $filename,
            d.file_type = $file_type,
            d.size_bytes = $size_bytes,
            d.upload_date = datetime($upload_date),
            d.processed = true
        """
        
        await self.graph_store.execute_query(
            doc_query,
            {
                "id": document.id,
                "filename": document.filename,
                "file_type": document.file_type,
                "size_bytes": document.size_bytes,
                "upload_date": document.upload_date.isoformat()
            }
        )
        
        # Store entities
        for entity in extraction.entities:
            await self.graph_store.create_node(entity)
        
        # Store relationships
        for relationship in extraction.relationships:
            try:
                await self.graph_store.create_relationship(relationship)
            except Exception as e:
                print(f"Failed to create relationship {relationship.type}: {e}")
        
        # Store chunks with entity links
        for chunk in extraction.chunks:
            # Find entities mentioned in this chunk
            chunk_text_lower = chunk.text.lower()
            mentioned_entities = [
                e for e in extraction.entities
                if e.name.lower() in chunk_text_lower
            ]
            
            await self.graph_store.create_chunk_with_entities(
                chunk,
                mentioned_entities
            )
            
            # Store chunk vector
            if chunk.embedding:
                await self.graph_store.add_vectors(
                    vectors=[chunk.embedding],
                    metadata=[{
                        "text": chunk.text,
                        "document_id": chunk.document_id,
                        "chunk_index": chunk.chunk_index
                    }],
                    ids=[chunk.id]
                )
    
    def get_ontology(self) -> Optional[OntologySchema]:
        """Get current ontology"""
        return self._ontology
    
    def set_ontology(self, ontology: OntologySchema):
        """Set ontology to use"""
        self._ontology = ontology
