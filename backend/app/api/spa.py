"""Static frontend with SPA fallback (PLAN §11, TEAM.md §2.5).

Serves the Next.js static export from `STATIC_DIR` (default `static`). Resolution for a
non-/api GET path: the exact file, then `<path>.html` (Next export with
`trailingSlash: false`), then `<path>/index.html`, then `index.html`. Unknown /api paths
stay JSON 404s. Registered last so every API route wins.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

log = logging.getLogger(__name__)


def _resolve(root: Path, path: str) -> Path | None:
    candidates = [path, f"{path}.html", f"{path}/index.html"] if path else []
    for rel in candidates:
        p = (root / rel).resolve()
        if p.is_relative_to(root) and p.is_file():
            return p
    index = root / "index.html"
    return index if index.is_file() else None


def mount_frontend(app: FastAPI, static_dir: str | Path) -> None:
    root = Path(static_dir).resolve()
    if not (root / "index.html").is_file():
        log.warning("no frontend build at %s (STATIC_DIR); serving the API only", root)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        target = _resolve(root, path.strip("/"))
        if target is None:
            raise HTTPException(status_code=404, detail="Frontend not built")
        return FileResponse(target)
