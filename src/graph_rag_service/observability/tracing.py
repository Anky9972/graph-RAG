"""
OpenTelemetry instrumentation for observability
Provides tracing, metrics, and structured logging
"""

import logging
from typing import Optional
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from ..config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def setup_observability(app=None):
    """
    Setup OpenTelemetry observability
    
    Args:
        app: FastAPI application instance (optional)
    """
    
    if not settings.enable_tracing:
        logger.info("Tracing disabled")
        return
    
    # Create resource
    resource = Resource.create({
        "service.name": settings.app_name,
        "service.version": settings.app_version,
        "deployment.environment": settings.environment
    })
    
    # Setup tracing
    if settings.enable_tracing:
        tracer_provider = TracerProvider(resource=resource)
        
        # Add span processor (console for now, can add OTLP exporter)
        span_processor = BatchSpanProcessor(ConsoleSpanExporter())
        tracer_provider.add_span_processor(span_processor)
        
        trace.set_tracer_provider(tracer_provider)
        
        # Instrument FastAPI if provided
        if app:
            FastAPIInstrumentor.instrument_app(app)
        
        logger.info("Tracing enabled")
    
    # Setup metrics
    if settings.enable_metrics:
        metric_reader = PeriodicExportingMetricReader(
            ConsoleMetricExporter()
        )
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[metric_reader]
        )
        metrics.set_meter_provider(meter_provider)
        
        logger.info("Metrics enabled")


def get_tracer(name: str):
    """Get tracer for instrumentation"""
    return trace.get_tracer(name)


def get_meter(name: str):
    """Get meter for metrics"""
    return metrics.get_meter(name)


# Create global tracer and meter
tracer = get_tracer(__name__)
meter = get_meter(__name__)

# Create metrics
ingestion_counter = meter.create_counter(
    "documents_ingested",
    description="Number of documents ingested",
    unit="1"
)

query_counter = meter.create_counter(
    "queries_executed",
    description="Number of queries executed",
    unit="1"
)

query_duration = meter.create_histogram(
    "query_duration_seconds",
    description="Query execution time in seconds",
    unit="s"
)

entity_counter = meter.create_counter(
    "entities_extracted",
    description="Number of entities extracted",
    unit="1"
)
