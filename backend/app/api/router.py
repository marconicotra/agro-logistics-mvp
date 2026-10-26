from fastapi import APIRouter

from app.api.routes.admin_ops import router as admin_ops_router
from app.api.routes.backoffice import router as backoffice_router
from app.api.routes.health import router as health_router
from app.api.routes.webhooks import router as webhooks_router

from app.api.routes.routing import router as routing_router

api_router = APIRouter()
api_router.include_router(routing_router)
api_router.include_router(health_router)
api_router.include_router(admin_ops_router)
api_router.include_router(backoffice_router)
api_router.include_router(webhooks_router)
