from fastapi import APIRouter, Depends

from app.api.v1.endpoints import documents, health, prep, qa
from app.core.auth import require_login, require_teacher

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(documents.router, tags=["documents"], dependencies=[Depends(require_teacher)])
api_router.include_router(qa.router, tags=["qa"], dependencies=[Depends(require_login)])
api_router.include_router(prep.router, tags=["prep"], dependencies=[Depends(require_teacher)])
