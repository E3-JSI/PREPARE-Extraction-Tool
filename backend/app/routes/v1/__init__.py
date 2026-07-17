from fastapi import APIRouter
from app.routes.v1 import (
    health,
    auth,
    datasets,
    source_term,
    clusters,
    bioner,
    live_eval,
    training_events,
    vocabularies,
    mappings,
)

api_router = APIRouter()

# Health check route
api_router.include_router(health.router, prefix="/health", tags=["Health"])

# Authentication routes
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])

# Main routes
api_router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
api_router.include_router(
    source_term.router, prefix="/source-terms", tags=["Source Terms"]
)
api_router.include_router(clusters.router, prefix="/clusters", tags=["Clusters"])
api_router.include_router(bioner.router, prefix="/bioner", tags=["BioNER"])
api_router.include_router(live_eval.router, prefix="/bioner", tags=["BioNER"])
api_router.include_router(
    training_events.router, prefix="/bioner", tags=["Training"]
)


api_router.include_router(
    vocabularies.router, prefix="/vocabularies", tags=["Vocabularies"]
)

api_router.include_router(mappings.router, prefix="/datasets", tags=["Mappings"])
