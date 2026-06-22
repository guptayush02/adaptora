import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.logger import logger
from app.routes.api import router
from app.routes.auth import router as auth_router
from app.routes.dynamic_agent import router as dynamic_agent_router
from app.routes.developer_api import router as developer_api_router
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    # Startup
    logger.info("Starting LLM Token Optimizer Middleware...")
    init_db()
    logger.info("Database initialized")
    yield
    # Shutdown
    logger.info("Shutting down middleware...")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="A middleware for optimizing prompts and tracking tokens across LLM models",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# Add CORS middleware. Browsers reject credentialed requests when allow_origins
# is "*", so we drop credentials in that case and let the client send Bearer
# tokens in headers instead.
_cors_origins = settings.CORS_ALLOW_ORIGINS
_wildcard = isinstance(_cors_origins, list) and "*" in _cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)
app.include_router(auth_router)
app.include_router(dynamic_agent_router)
app.include_router(developer_api_router)


# Serve the built React app from FastAPI when ./frontend/dist exists.
# This makes the Docker image self-contained — one container, one process,
# no nginx reverse proxy needed. In dev (no build dir present) the root
# falls back to the JSON status page below.
_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
_FRONTEND_AVAILABLE = os.path.isdir(_FRONTEND_DIST) and os.path.isfile(
    os.path.join(_FRONTEND_DIST, "index.html")
)

if _FRONTEND_AVAILABLE:
    # Mount the assets dir (hashed JS/CSS bundles vite emits) at /assets.
    # Everything else — react-router paths like /home, /tools, /agent —
    # falls through to the catch-all below that returns index.html so
    # client-side routing works on direct page loads / refreshes.
    _ASSETS_DIR = os.path.join(_FRONTEND_DIST, "assets")
    if os.path.isdir(_ASSETS_DIR):
        app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")
    logger.info(f"serving frontend from {_FRONTEND_DIST}")
else:
    logger.info(
        "frontend/dist not found — root will return JSON status. "
        "Run `npm --prefix frontend run build` to enable single-container mode."
    )


@app.get("/")
async def root():
    """Root endpoint. Returns the SPA shell when a frontend build is
    present, else a JSON status page for API-only deploys."""
    if _FRONTEND_AVAILABLE:
        return FileResponse(os.path.join(_FRONTEND_DIST, "index.html"))
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": "LLM Middleware for prompt optimization and token tracking",
        "endpoints": {
            "process": "/api/process",
            "health": "/api/health",
            "stats": "/api/stats/{user_id}",
            "cache_clear": "/api/cache/clear",
        },
    }


# SPA catch-all. Must be added LAST so it doesn't shadow /api/* routes.
# Returns index.html for any GET that wasn't matched above — react-router
# then takes over and renders the right page from the URL.
if _FRONTEND_AVAILABLE:

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Belt-and-suspenders: never swallow /api/* — those should 404
        # cleanly so the client gets a useful error instead of HTML.
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(os.path.join(_FRONTEND_DIST, "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )
