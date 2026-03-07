"""
Main entry point for the Graph RAG Service
"""

import uvicorn
from .api.server import app
from .observability.tracing import setup_observability
from .config import settings


def main():
    """Start the API server"""
    
    # Setup observability
    setup_observability(app)
    
    # Run server
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        reload=settings.debug
    )


if __name__ == "__main__":
    main()
