from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from elasticsearch.exceptions import ApiError
from app.core.seed_models import seed_builtin_models


from app.routes.v1 import api_router
from app.core.settings import settings
from app.core.database import check_migration_status
from app.core.elastic import check_es_connection
from app.core.model_registry import register_models
from app.core.middleware import SecurityHeadersMiddleware
from app.core.exceptions import (
    database_exception_handler,
    elasticsearch_exception_handler,
    validation_exception_handler,
    generic_exception_handler,
)

logger = logging.getLogger(__name__)

# ================================================
# Application setup
# ================================================


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("🚀 LIFESPAN STARTED")

    try:
        logger.info("🌱 Seeding models...")
        seed_builtin_models()
        logger.info("🌱 Seeding completed")
    except Exception as e:
        logger.exception(f"❌ Seed failed: {e}")

    migration_status = check_migration_status()

    if not migration_status["up_to_date"]:
        logger.warning(
            "Database migrations are not up to date!\n"
            f"  Current revision: {migration_status['current']}\n"
            f"  Latest revision:  {migration_status['head']}\n"
        )
    else:
        logger.info(f"DB is up to date: {migration_status['current']}")

    register_models()
    check_es_connection()

    yield

# initialize the FastAPI app
app = FastAPI(
    title=settings.SERVICE_NAME, openapi_url="/api/openapi.json", lifespan=lifespan
)

# ================================================
# Middleware configuration
# ================================================

# Set all CORS enabled origins
cors_origins = [str(origin).rstrip("/") for origin in settings.BACKEND_CORS_ORIGINS]

if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# ================================================
# Exception handlers
# ================================================

# Register exception handlers
app.add_exception_handler(SQLAlchemyError, database_exception_handler)
app.add_exception_handler(ApiError, elasticsearch_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(ValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# ================================================
# API routes
# ================================================

# add API routes
app.include_router(api_router, prefix=settings.API_V1_STR)



#app.include_router(training_events_router, prefix="/api/v1/bioner")
