"""REST API routers."""

from app.api.rooms import router as rooms_router
from app.api.sessions import router as sessions_router
from app.api.users import router as users_router

__all__ = ["rooms_router", "sessions_router", "users_router"]
