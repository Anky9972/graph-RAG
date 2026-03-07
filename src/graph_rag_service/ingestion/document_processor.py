"""
Document processing and chunking
Supports PDF, TXT, MD, DOCX formats
Uses LlamaParse for advanced PDF parsing when available
"""

import aiofiles
from pathlib import Path
from typing import List, Dict, Any, Optional
import hashlib
from datetime import datetime
import os

from pypdf import PdfReader
from llama_index.core.node_parser import SentenceSplitter

from ..core.models import Document, Chunk
from ..config import settings

# LlamaParse import (optional)
try:
    from llama_parse import LlamaParse
    LLAMA_PARSE_AVAILABLE = True
except ImportError:
    LLAMA_PARSE_AVAILABLE = False


class DocumentProcessor:
    """Process and chunk documents for ingestion"""
    
    def __init__(self):
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        self.splitter = SentenceSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )
        
        # Initialize LlamaParse if API key is available
        self.llama_parser: Optional[LlamaParse] = None
        if (LLAMA_PARSE_AVAILABLE and 
            settings.use_llama_parse and 
            settings.llama_cloud_api_key):
            try:
                # Set API key for LlamaParse
                os.environ["LLAMA_CLOUD_API_KEY"] = settings.llama_cloud_api_key
                
                self.llama_parser = LlamaParse(
                    result_type="markdown",  # Get markdown output for better structure
                    verbose=True,
                    language="en",
                )
            except Exception as e:
                print(f"Warning: Failed to initialize LlamaParse: {e}")
                self.llama_parser = None
    
    async def process_document(self, file_path: Path) -> Document:
        """
        Process a document and extract metadata
        
        Args:
            file_path: Path to document file
            
        Returns:
            Document with metadata
        """
        
        # Extract text based on file type
        text = await self._extract_text(file_path)
        
        # Create document metadata
        document = Document(
            id=self._generate_document_id(file_path),
            filename=file_path.name,
            file_type=file_path.suffix,
            size_bytes=file_path.stat().st_size,
            upload_date=datetime.utcnow(),
            content=text,
            metadata={
                "file_path": str(file_path),
                "extension": file_path.suffix
            }
        )
        
        return document
    
    async def chunk_document(
        self,
        document: Document
    ) -> List[Chunk]:
        """
        Chunk document into smaller pieces
        
        Args:
            document: Document to chunk
            
        Returns:
            List of chunks
        """
        
        if not document.content:
            return []
        
        # Use LlamaIndex splitter
        text_chunks = self.splitter.split_text(document.content)
        
        # Create Chunk objects
        chunks = []
        for i, text in enumerate(text_chunks):
            chunk = Chunk(
                id=f"{document.id}_chunk_{i}",
                text=text,
                document_id=document.id,
                chunk_index=i,
                metadata={
                    "document_filename": document.filename,
                    "document_type": document.file_type,
                    "chunk_index": i,
                    "total_chunks": len(text_chunks)
                }
            )
            chunks.append(chunk)
        
        return chunks
    
    async def _extract_text(self, file_path: Path) -> str:
        """Extract text from file based on type"""
        
        extension = file_path.suffix.lower()
        
        if extension == '.pdf':
            return await self._extract_pdf(file_path)
        elif extension == '.txt':
            return await self._extract_txt(file_path)
        elif extension == '.md':
            return await self._extract_txt(file_path)
        elif extension == '.docx':
            return await self._extract_docx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {extension}")
    
    async def _extract_pdf(self, file_path: Path) -> str:
        """
        Extract text from PDF using LlamaParse (if available) or pypdf
        
        LlamaParse provides superior extraction quality with:
        - Better table handling
        - Preserved document structure
        - Multi-column layout support
        - Image extraction and OCR
        """
        
        # Try LlamaParse first if available
        if self.llama_parser:
            try:
                print(f"Using LlamaParse for {file_path.name}...")
                # LlamaParse returns LlamaIndex Document objects
                documents = await self.llama_parser.aload_data(str(file_path))
                
                # Combine all document texts
                text = "\n\n".join([doc.text for doc in documents])
                print(f"✓ LlamaParse extracted {len(text)} characters")
                return text.strip()
                
            except Exception as e:
                print(f"Warning: LlamaParse failed, falling back to pypdf: {e}")
        
        # Fallback to pypdf for basic extraction
        print(f"Using pypdf for {file_path.name}...")
        reader = PdfReader(str(file_path))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n\n"
        return text.strip()
    
    async def _extract_txt(self, file_path: Path) -> str:
        """Extract text from TXT/MD file"""
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            return await f.read()
    
    async def _extract_docx(self, file_path: Path) -> str:
        """Extract text from DOCX"""
        # Simple implementation - can be enhanced with python-docx
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            
            with zipfile.ZipFile(file_path) as docx:
                xml_content = docx.read('word/document.xml')
                tree = ET.XML(xml_content)
                
                paragraphs = []
                for paragraph in tree.iter():
                    if paragraph.tag.endswith('}t'):
                        if paragraph.text:
                            paragraphs.append(paragraph.text)
                
                return '\n'.join(paragraphs)
        except Exception as e:
            raise ValueError(f"Failed to extract text from DOCX: {e}")
    
    def _generate_document_id(self, file_path: Path) -> str:
        """Generate unique document ID based on file content"""
        hasher = hashlib.sha256()
        hasher.update(str(file_path).encode())
        hasher.update(str(file_path.stat().st_mtime).encode())
        return hasher.hexdigest()[:16]
