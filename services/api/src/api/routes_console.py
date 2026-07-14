from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["Console"])

_CONSOLE_DIR = Path(__file__).resolve().parents[1] / "web" / "console"


def _console_file(name: str) -> Path:
    path = (_CONSOLE_DIR / name).resolve()
    if path.parent != _CONSOLE_DIR.resolve():
        raise FileNotFoundError(name)
    return path


@router.get("/console/extract-monitor")
async def extract_monitor_page():
    return FileResponse(_console_file("extract-monitor.html"))


@router.get("/console/")
async def console_index():
    return FileResponse(_console_file("index.html"))


@router.get("/console/app.js")
async def console_app_js():
    return FileResponse(_console_file("app.js"), media_type="application/javascript")


@router.get("/console/style.css")
async def console_style_css():
    return FileResponse(_console_file("style.css"), media_type="text/css")


@router.get("/console/extract-monitor.js")
async def extract_monitor_js():
    return FileResponse(_console_file("extract-monitor.js"), media_type="application/javascript")


@router.get("/console/extract-monitor.css")
async def extract_monitor_css():
    return FileResponse(_console_file("extract-monitor.css"), media_type="text/css")
