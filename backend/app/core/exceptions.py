import logging
from typing import Union

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError
from elasticsearch.exceptions import (
    ConnectionError as ESConnectionError,
    ApiError,
)

from app.core.settings import settings

# Initialize logger
logger = logging.getLogger(__name__)


# ================================================
# Exception handler functions
# ================================================


async def database_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    """
    Handle database-related exceptions.

    Args:
        request: The incoming request
        exc: The SQLAlchemy exception

    Returns:
        JSONResponse with appropriate error message and status code
    """
    logger.error(
        f"Database error on {request.method} {request.url.path}: {str(exc)}",
        exc_info=True,
    )

    # Check specific error types
    if isinstance(exc, OperationalError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Database service is temporarily unavailable. Please try again later."
            },
        )
    elif isinstance(exc, IntegrityError):
        # This should typically be caught in route handlers, but handle it here as fallback
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Database constraint violation. The operation conflicts with existing data."
            },
        )

    # Generic database error
    if settings.ENVIRONMENT == "local":
        detail = f"Database error: {str(exc)}"
    else:
        detail = "An internal database error occurred. Please try again later."

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": detail},
    )


async def elasticsearch_exception_handler(
    request: Request, exc: ApiError
) -> JSONResponse:
    """
    Handle Elasticsearch-related exceptions.

    Args:
        request: The incoming request
        exc: The Elasticsearch exception

    Returns:
        JSONResponse with appropriate error message and status code
    """
    logger.error(
        f"Elasticsearch error on {request.method} {request.url.path}: {str(exc)}",
        exc_info=True,
    )

    # Check for connection errors
    if isinstance(exc, ESConnectionError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Search service is temporarily unavailable. Please try again later."
            },
        )

    # Generic Elasticsearch error
    if settings.ENVIRONMENT == "local":
        detail = f"Search service error: {str(exc)}"
    else:
        detail = "An internal search service error occurred. Please try again later."

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": detail},
    )


async def validation_exception_handler(
    request: Request, exc: Union[RequestValidationError, ValidationError]
) -> JSONResponse:
    """
    Handle validation errors from Pydantic models and FastAPI request validation.

    Args:
        request: The incoming request
        exc: The validation exception

    Returns:
        JSONResponse with validation error details
    """
    logger.warning(
        f"Validation error on {request.method} {request.url.path}: {str(exc)}"
    )

    # pydantic v2 puts the raw exception raised by a field validator in each
    # error's ``ctx``, which JSONResponse cannot render. Encode the errors the
    # same way FastAPI's own handler does so rendering can never fail.
    errors = jsonable_encoder(exc.errors())

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": errors,
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle any unhandled exceptions.

    Args:
        request: The incoming request
        exc: The unhandled exception

    Returns:
        JSONResponse with generic error message
    """
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {str(exc)}",
        exc_info=True,
    )

    # Never expose internal error details in production
    if settings.ENVIRONMENT == "local":
        detail = f"Internal server error: {str(exc)}"
    else:
        detail = "An internal server error occurred. Please try again later."

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": detail},
    )
