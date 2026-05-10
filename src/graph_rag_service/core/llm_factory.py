import logging
logger = logging.getLogger(__name__)
"""
Multi-LLM provider factory with unified interface
Supports OpenAI, Anthropic, Gemini, and Ollama
"""

from typing import Optional, Any, List, Type
from pydantic import BaseModel
import json
import asyncio

from llama_index.llms.openai import OpenAI
from llama_index.llms.anthropic import Anthropic
from llama_index.llms.gemini import Gemini
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
try:
    from llama_index.embeddings.gemini import GeminiEmbedding
except ImportError:
    pass
from llama_index.core.llms import ChatMessage

from .abstractions import LLMProvider
from ..config import settings

# Maximum retries for rate-limited API calls
_MAX_RETRIES = 6
_BASE_DELAY = 5  # seconds


class UnifiedLLMProvider(LLMProvider):
    """
    Unified LLM provider that wraps multiple backends
    Provides consistent interface across OpenAI, Anthropic, Gemini, Ollama
    """
    
    def __init__(self, provider: str = None, model: str = None):
        self.provider_name = provider or settings.default_llm_provider
        self.model_name = model
        self.llm = None
        self.embedder = None
        self._initialize_provider()
    
    def _initialize_provider(self):
        """Initialize the appropriate LLM provider"""
        
        # Configure Gemini SDK if using Gemini for LLM or embeddings
        # Removed global global genai.configure() due to poisoning risk.
        # Llama Index Gemini handles API keys within the constructor.
        
        if self.provider_name == "openai":
            self.llm = OpenAI(
                api_key=settings.openai_api_key,
                model=self.model_name or settings.openai_model,
                temperature=0.7
            )
            
        elif self.provider_name == "anthropic":
            self.llm = Anthropic(
                api_key=settings.anthropic_api_key,
                model=self.model_name or settings.anthropic_model,
                temperature=0.7
            )
            
        elif self.provider_name == "gemini":
            self.llm = Gemini(
                api_key=settings.google_api_key,
                model=self.model_name or settings.gemini_model,
                temperature=0.7
            )
            
        elif self.provider_name == "ollama":
            self.llm = Ollama(
                base_url=settings.ollama_base_url,
                model=self.model_name or settings.ollama_model,
                temperature=0.7,
                request_timeout=60.0
            )
            
            # Initialize embedder for Ollama
            self.embedder = OllamaEmbedding(
                base_url=settings.ollama_base_url,
                model_name=settings.ollama_embedding_model
            )
        elif self.provider_name == "mock":
            # Used for DEMO_MODE fallback in Docker when no API keys are provided
            self.llm = "mock_llm"
            self.embedder = "mock_embedder"
        else:
            raise ValueError(f"Unsupported provider: {self.provider_name}")
    
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """Generate completion from prompt with automatic rate-limit retry"""
        
        if self.provider_name == "mock":
            # Return minimal valid JSON that matches what each task expects
            p = prompt.lower()
            if '"entities"' in prompt and '"relationships"' in prompt:
                # Extract capitalized words as demo entities so graph has something
                import re as _re
                words = _re.findall(r'\b[A-Z][a-z]{2,}\b', prompt)
                unique_words = list(dict.fromkeys(words))[:5]
                demo_entities = [{"name": w, "type": "Concept", "description": f"Demo entity: {w}"} for w in unique_words] or [{"name": "Demo Entity", "type": "Concept", "description": "Mock entity for demo mode"}]
                return f'{{"entities": {__import__("json").dumps(demo_entities)}, "relationships": []}}'
            if '"findings"' in prompt or "community report" in p:
                return '{"title": "Demo Community", "summary": "Mock community summary for demo mode.", "findings": []}'
            if "return only a json list" in p or "sub-questions" in p or "decompose" in p:
                return '["demo query"]'
            if "ontology" in p or '"entity_types"' in prompt:
                return '{"entity_types": ["Person", "Organization", "Concept"], "relationship_types": ["RELATED_TO", "PART_OF"], "properties": {}}'
            if "cypher" in p or "match (" in p:
                return "MATCH (n) RETURN n LIMIT 0"
            return '{"answer": "Mock response. Set GOOGLE_API_KEY for real results.", "confidence": 0.0}'
            
        messages = []
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=prompt))
        
        # Update temperature if different
        if hasattr(self.llm, 'temperature'):
            self.llm.temperature = temperature
        
        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await asyncio.wait_for(self.llm.achat(messages), timeout=90.0)
                return response.message.content
            except asyncio.TimeoutError as e:
                last_error = e
                logger.info(f"LLM request timed out (attempt {attempt + 1}/{_MAX_RETRIES}).")
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2)
            except Exception as e:
                last_error = e
                err_str = str(e)
                # Retry on rate limit (429) errors
                if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                    delay = _BASE_DELAY * (2 ** attempt)
                    logger.info(f"Rate limited (attempt {attempt + 1}/{_MAX_RETRIES}), retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    raise
        raise last_error
    
    async def complete_structured(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        system_prompt: Optional[str] = None
    ) -> Any:
        """
        Generate structured output conforming to a Pydantic model
        Uses JSON mode with schema injection
        """
        
        if self.provider_name == "mock":
            # For extraction tasks, return a realistic small mock graph
            if response_model.__name__ == "ExtractionResult":
                from ..ingestion.pipeline import ExtractionResult
                from .models import Entity, Relationship
                import uuid
                return ExtractionResult(
                    entities=[
                        Entity(id=uuid.uuid4().hex[:8], name="Project Apollo", type="Project", properties={"status": "Active"}),
                        Entity(id=uuid.uuid4().hex[:8], name="Alice Smith", type="Person", properties={"role": "Lead"}),
                        Entity(id=uuid.uuid4().hex[:8], name="Data Science Dept", type="Organization", properties={"location": "HQ"})
                    ],
                    relationships=[
                        Relationship(source="Alice Smith", target="Project Apollo", type="LEADS", confidence=0.9, properties={"since": "2023"}),
                        Relationship(source="Alice Smith", target="Data Science Dept", type="WORKS_FOR", confidence=1.0, properties={})
                    ]
                )
                
            # Try to return an empty instance of the model with default values
            try:
                # Construct empty dictionary with expected fields based on schema
                schema = response_model.model_json_schema()
                mock_data = {}
                for prop_name, prop_details in schema.get("properties", {}).items():
                    if prop_details.get("type") == "array":
                        mock_data[prop_name] = []
                    elif prop_details.get("type") == "string":
                        mock_data[prop_name] = f"Mock {prop_name}"
                    elif prop_details.get("type") in ["integer", "number"]:
                        mock_data[prop_name] = 1
                    elif prop_details.get("type") == "boolean":
                        mock_data[prop_name] = True
                    else:
                        mock_data[prop_name] = None
                return response_model(**mock_data)
            except Exception:
                # If that fails, just instantiate with empty args and hope it has defaults
                return response_model()
                
        # Create schema-aware prompt
        schema = response_model.model_json_schema()
        enhanced_prompt = f"""
{prompt}

Please respond with a valid JSON object that matches this schema:
{json.dumps(schema, indent=2)}

Only return the JSON object, no additional text.
"""
        
        if system_prompt:
            enhanced_prompt = f"{system_prompt}\n\n{enhanced_prompt}"
        
        response = await self.complete(enhanced_prompt, temperature=0.1)
        
        # Try to parse JSON response
        try:
            import re
            cleaned = response.strip()
            # Remove markdown fence
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
            cleaned = cleaned.strip()
            
            # Parse JSON
            data = json.loads(cleaned)
            return response_model(**data)
        except Exception as e:
            # Fallback: try to extract JSON from response using more robust matching
            import re
            # Extract anything between the first { or [ and the last } or ]
            json_match = re.search(r'([\{\[].*[\}\]])', response, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    return response_model(**data)
                except Exception:
                    pass
            logger.error(f"Failed to parse structured JSON: {e}\nResponse: {response}")
            raise ValueError(f"Failed to parse structured response: {e}")
    
    async def embed(self, text: str) -> List[float]:
        """Generate embedding for text"""
        
        embed_provider = settings.embedding_provider
        if self.provider_name == "mock" or embed_provider == "mock":
            import hashlib
            import random
            seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
            rng = random.Random(seed)
            return [rng.uniform(-0.1, 0.1) for _ in range(768)]
            
        if embed_provider == "gemini":
            embedder = GeminiEmbedding(
                model_name="models/gemini-embedding-001",
                api_key=settings.google_api_key
            )
            last_error = None
            for attempt in range(6):
                try:
                    return await embedder.aget_text_embedding(text)
                except Exception as e:
                    last_error = e
                    if "429" in str(e) or "quota" in str(e).lower():
                        delay = 5 * (2 ** attempt)
                        logger.info(f"Embedding rate limited, retrying in {delay}s...")
                        await asyncio.sleep(delay)
                    else:
                        raise
            raise last_error
        
        elif embed_provider == "ollama":
            if not self.embedder:
                self.embedder = OllamaEmbedding(
                    base_url=settings.ollama_base_url,
                    model_name=settings.ollama_embedding_model
                )
            embedding = await self.embedder.aget_text_embedding(text)
            return embedding
            
        elif embed_provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.embeddings.create(
                input=text,
                model="text-embedding-3-large"
            )
            return response.data[0].embedding
        else:
            raise ValueError(f"Unsupported embedding provider: {embed_provider}")
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        
        embed_provider = settings.embedding_provider
        if self.provider_name == "mock" or embed_provider == "mock":
            import hashlib
            import random
            result = []
            for t in texts:
                seed = int(hashlib.md5(t.encode()).hexdigest()[:8], 16)
                rng = random.Random(seed)
                result.append([rng.uniform(-0.1, 0.1) for _ in range(768)])
            return result
            
        if embed_provider == "gemini":
            embedder = GeminiEmbedding(
                model_name="models/gemini-embedding-001",
                api_key=settings.google_api_key
            )
            last_error = None
            for attempt in range(6):
                try:
                    return await embedder.aget_text_embedding_batch(texts)
                except Exception as e:
                    last_error = e
                    if "429" in str(e) or "quota" in str(e).lower():
                        delay = 5 * (2 ** attempt)
                        logger.info(f"Embedding rate limited, retrying in {delay}s...")
                        await asyncio.sleep(delay)
                    else:
                        raise
            raise last_error
        
        elif embed_provider == "ollama":
            if not self.embedder:
                self.embedder = OllamaEmbedding(
                    base_url=settings.ollama_base_url,
                    model_name=settings.ollama_embedding_model
                )
            embeddings = await self.embedder.aget_text_embedding_batch(texts)
            return embeddings
            
        elif embed_provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.embeddings.create(
                input=texts,
                model="text-embedding-3-large"
            )
            return [item.embedding for item in response.data]
        else:
            raise ValueError(f"Unsupported embedding provider: {embed_provider}")


class LLMFactory:
    """Factory for creating LLM providers"""
    
    @staticmethod
    def create(provider: str = None, model: str = None) -> UnifiedLLMProvider:
        """
        Create an LLM provider instance
        
        Args:
            provider: Provider name (openai, anthropic, gemini, ollama)
            model: Model name (optional, uses default from settings)
            
        Returns:
            UnifiedLLMProvider instance
        """
        return UnifiedLLMProvider(provider=provider, model=model)
    
    @staticmethod
    def create_from_config(config: dict) -> UnifiedLLMProvider:
        """
        Create provider from configuration dictionary
        
        Args:
            config: Configuration with 'provider' and optional 'model' keys
            
        Returns:
            UnifiedLLMProvider instance
        """
        provider = config.get("provider", settings.default_llm_provider)
        model = config.get("model")
        return LLMFactory.create(provider=provider, model=model)
