import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.identity_routes import router as identity_router, admin as admin_router
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.4.0", description="DEMO/PAPER-only starter. No live orders are implemented.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data", "X-CSRF-Token"],
)
app.include_router(identity_router)
app.include_router(admin_router)
app.include_router(router)



@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "mode": "DEMO", "live_enabled": False}


@app.get("/ready", tags=["health"])
def ready() -> dict:
    # Process readiness only; this is not trading readiness.
    return {"status": "ready", "trading_ready": False, "reason": "Trading integrations are not implemented or connected."}


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", str(PROJECT_ROOT / "frontend" / "dist")))
ASSETS_DIR = FRONTEND_DIST / "assets"
if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/", include_in_schema=False)
def frontend_root():
    index_file = FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return JSONResponse({"message": "Frontend build is not present. Run npm run build in frontend/.", "api_docs": "/docs"}, status_code=503)


@app.get("/{path:path}", include_in_schema=False)
def frontend_fallback(path: str):
    # Serve the SPA for client-side routes, but never shadow API or health paths.
    if path.startswith(("api/", "health", "ready", "docs", "openapi.json", "redoc", "assets/")):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    index_file = FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return JSONResponse({"detail": "Not found"}, status_code=404)
