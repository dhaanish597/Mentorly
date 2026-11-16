"""Browser navigation fallback after every coordinator route.

Vercel serves actual public/ files from its CDN. Missing API, WebSocket and
asset requests must continue to produce a genuine error instead of SPA HTML.
"""

from pathlib import Path, PurePosixPath

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response


def _accepts_html(header: str) -> bool:
    for item in header.lower().split(","):
        media_type, *parameters = item.strip().split(";")
        if media_type not in {"text/html", "application/xhtml+xml"}:
            continue
        quality = 1.0
        for parameter in parameters:
            key, separator, value = parameter.strip().partition("=")
            if key == "q" and separator:
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if 0 < quality <= 1:
            return True
    return False


def register_frontend_fallback(app: FastAPI, index: Path) -> None:
    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def frontend_fallback(request: Request, path: str) -> Response:
        parts = PurePosixPath(path).parts
        reserved = bool(parts and parts[0].lower() in {"api", "ws", "assets"})
        asset = bool(parts and "." in parts[-1])
        if reserved or asset or not _accepts_html(request.headers.get("accept", "")):
            return JSONResponse({"detail": "Not Found"}, status_code=404,
                                headers={"Cache-Control": "no-store"})
        return FileResponse(index, media_type="text/html", headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
        })
