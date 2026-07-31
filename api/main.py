"""VPN Gateway Admin API."""

import logging
import sys
from pathlib import Path

# Add api directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from config import API_VERSION, API_VERSION_DATE
from middleware.client_filter import ClientFilterMiddleware
from routers import domains, networks, routing, dns, system, notifications, vpn, openvpn
from routers import services_rt, xray, xray_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="VPN Gateway Admin API",
    version=API_VERSION,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Middleware
app.add_middleware(ClientFilterMiddleware)
# CORS not needed — SPA is same-origin (served by this app)

# Routers
app.include_router(system.router, prefix="/api/v1")
app.include_router(services_rt.router, prefix="/api/v1")
app.include_router(domains.router, prefix="/api/v1")
app.include_router(networks.router, prefix="/api/v1")
app.include_router(routing.router, prefix="/api/v1")
app.include_router(dns.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(vpn.router, prefix="/api/v1")
app.include_router(openvpn.router, prefix="/api/v1")
app.include_router(xray.router, prefix="/api/v1")
app.include_router(xray_client.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {
        "status": "ok",
        "version": API_VERSION,
        "version_date": API_VERSION_DATE,
    }


# Static files for web UI
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/favicon.ico")
    @app.get("/favicon.png")
    async def serve_favicon():
        return FileResponse(
            str(static_dir / "favicon.png"),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/apple-touch-icon.png")
    @app.get("/apple-touch-icon-precomposed.png")
    async def serve_apple_icon():
        return FileResponse(
            str(static_dir / "apple-touch-icon.png"),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Cache index.html bytes once at startup so each request just runs a
    # cheap str.replace on __VER__ instead of re-reading the file.
    _INDEX_HTML = (static_dir / "index.html").read_text()

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def serve_spa(request: Request, full_path: str):
        """Serve index.html for SPA — all non-API routes.

        Substitute __VER__ → API_VERSION inside the HTML so all <script>
        and <link rel=stylesheet> tags become e.g. `?v=2.0.16`. A new
        deploy bumps the version → URLs change → browsers fetch fresh
        copies without the user having to hard-refresh.

        index.html itself is sent with `Cache-Control: no-cache` because
        it's the one file whose content depends on the version string;
        the static assets keep their default StaticFiles caching but
        their query string changes per release.

        NB: explicitly return JSON 404 for /api/* paths that didn't
        match any registered route. Without this guard the SPA HTML is
        returned, which then trips JSON.parse() in the frontend with
        the unhelpful "Unexpected token '<', '<html>' is not valid
        JSON" error. See CHANGELOG entry 75.
        """
        if full_path.startswith("api/") or full_path == "api":
            return JSONResponse(
                status_code=404,
                content={"status": "error", "error": f"unknown API path: /{full_path}"},
            )
        html = _INDEX_HTML.replace("__VER__", API_VERSION)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
