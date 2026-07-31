from .auth import router as auth_router
from .credits import router as credits_router
from .jobs import router as jobs_router
from .profiles import router as profiles_router
from .saved_jobs import router as saved_jobs_router

__all__ = [
    "auth_router",
    "credits_router",
    "jobs_router",
    "profiles_router",
    "saved_jobs_router",
]
