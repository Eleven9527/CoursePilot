from fastapi import APIRouter

from app.api.v1.endpoints import documents, health, qa

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(documents.router, tags=["documents"])
api_router.include_router(qa.router, tags=["qa"])
