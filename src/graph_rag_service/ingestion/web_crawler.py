import asyncio
import logging
from typing import List, Dict, Any, Set
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

class WebCrawler:
    """
    Advanced Web Crawler utilizing Crawl4AI to orchestrate Headless Playwright browsers.
    Extracts high quality markdown directly from dynamic, JS-heavy web properties.
    """
    def __init__(self, max_depth: int = 1, max_pages: int = 10, max_concurrent: int = 2):
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.max_concurrent = max_concurrent
        self.visited_urls: Set[str] = set()
        self.results: List[Dict[str, Any]] = []
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def _is_same_domain(self, base_url: str, target_url: str) -> bool:
        base_domain = urlparse(base_url).netloc
        target_domain = urlparse(target_url).netloc
        return base_domain == target_domain
        
    async def _crawl_recursive(self, crawler: Any, url: str, base_url: str, current_depth: int):
        if current_depth > self.max_depth or len(self.visited_urls) >= self.max_pages:
            return
            
        parsed = urlparse(url)
        normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        
        if normalized_url in self.visited_urls or not self._is_same_domain(base_url, normalized_url):
            return
            
        self.visited_urls.add(normalized_url)
        logger.info(f"Crawling {normalized_url} (Depth {current_depth}/{self.max_depth})")
        
        try:
            async with self._semaphore:
                result = await crawler.arun(url=normalized_url)
            
            if hasattr(result, 'success') and result.success:
                title = ""
                if hasattr(result, 'metadata') and isinstance(result.metadata, dict):
                    title = result.metadata.get("title", "")
                    
                self.results.append({
                    "url": normalized_url,
                    "title": title,
                    "markdown": result.markdown
                })
                
                if current_depth < self.max_depth and hasattr(result, "links") and result.links:
                    tasks = []
                    internal_links = result.links.get("internal", []) if isinstance(result.links, dict) else []
                    
                    for link_item in internal_links:
                        href = link_item.get("href")
                        if href and isinstance(href, str) and not href.startswith("mailto:") and not href.startswith("tel:"):
                            absolute_url = urljoin(base_url, href)
                            tasks.append(self._crawl_recursive(crawler, absolute_url, base_url, current_depth + 1))
                            
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"Error crawling {normalized_url}: {e}")

    async def crawl(self, start_url: str) -> List[Dict[str, Any]]:
        self.visited_urls.clear()
        self.results.clear()
        
        try:
            # We import here to fail gracefully if the dependency is not yet installed
            from crawl4ai import AsyncWebCrawler
        except ImportError:
            logger.error("crawl4ai is not installed. Please run 'npm install' or 'uv sync'")
            raise ImportError("crawl4ai package is missing.")
            
        logger.info(f"Starting web crawl for {start_url} (Max Depth: {self.max_depth})")
        async with AsyncWebCrawler(verbose=False) as crawler:
            await self._crawl_recursive(crawler, start_url, start_url, 0)
            
        return self.results
