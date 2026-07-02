from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, validate_startup
from api.routes import health, image


def _configure_logging() -> None:
    settings = get_settings()
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    renderer = (
        structlog.dev.ConsoleRenderer()
        if settings.log_level.upper() == "DEBUG"
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    logging.basicConfig(level=settings.log_level.upper())


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    validate_startup(settings)
    # Warm up CLIP weights at startup to avoid cold-start latency on first request.
    # ViT-B/32 weights are ~350MB and take 2-3s to load from disk.
    from stages.qa_validator import _ensure_clip_loaded
    await _ensure_clip_loaded()
    yield


_configure_logging()

app = FastAPI(
    title="Campaign Image Generator",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_methods=["POST", "GET"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)

app.include_router(health.router)
app.include_router(image.router)
