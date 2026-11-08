"""App factory. Routers are auto-discovered: any module in careerpilot.api.routes that exposes
`router` (APIRouter) is mounted under /api/v1. Lanes add their own module; no shared-file edits."""
import importlib, pkgutil, logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core.config import get_settings
from . import routes

log = logging.getLogger("careerpilot")
STARTUP_HOOKS: list = []   # lanes may append callables(app) run at startup (e.g. scheduler)
SHUTDOWN_HOOKS: list = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    for h in STARTUP_HOOKS:
        h(app)
    yield
    for h in SHUTDOWN_HOOKS:
        h(app)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="CareerPilot AI", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])
    for m in pkgutil.iter_modules(routes.__path__):
        mod = importlib.import_module(f"{routes.__name__}.{m.name}")
        r = getattr(mod, "router", None)
        if r is not None:
            app.include_router(r, prefix="/api/v1")
    return app


app = create_app()
