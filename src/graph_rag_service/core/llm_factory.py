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
from llama_index.core.llms import ChatMessage
import google.generativeai as genai

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
        if self.provider_name == "gemini" or settings.embedding_provider == "gemini":
            if settings.google_api_key:
                genai.configure(api_key=settings.google_api_key)
        
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
                response = await self.llm.achat(messages)
                return response.message.content
            except Exception as e:
                last_error = e
                err_str = str(e)
                # Retry on rate limit (429) errors
                if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                    delay = _BASE_DELAY * (2 ** attempt)
                    print(f"Rate limited (attempt {attempt + 1}/{_MAX_RETRIES}), retrying in {delay}s...")
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
            # Clean up response - remove markdown code blocks if present
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            # Parse JSON
            data = json.loads(cleaned)
            return response_model(**data)
        except Exception as e:
            # Fallback: try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    return response_model(**data)
                except:
                    pass
            
            raise ValueError(f"Failed to parse structured response: {e}\nResponse: {response}")
    
    async def embed(self, text: str) -> List[float]:
        """Generate embedding for text"""
        
        embed_provider = settings.embedding_provider
        
        if embed_provider == "gemini":
            result = genai.embed_content(
                model="models/gemini-embedding-001",
                content=text,
                task_type="retrieval_document",
            )
            return result["embedding"]
        
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
        
        if embed_provider == "gemini":
            embeddings = []
            for text in texts:
                result = genai.embed_content(
                    model="models/gemini-embedding-001",
                    content=text,
                    task_type="retrieval_document",
                )
                embeddings.append(result["embedding"])
                await asyncio.sleep(0.1)  # gentle rate limiting
            return embeddings
        
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
