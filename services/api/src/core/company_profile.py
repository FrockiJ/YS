from __future__ import annotations

import json
from typing import Any, Dict

from . import db

COMPANY_PROFILE_FILENAME = "__ys_company_profile__"
DEFAULT_SYSTEM_DISPLAY_NAME = "企業系統"


def build_system_display_name(company_name: str | None) -> str:
    name = " ".join(str(company_name or "").split()).strip()
    return f"{name}系統" if name else DEFAULT_SYSTEM_DISPLAY_NAME


async def fetch_company_profile_payload() -> Dict[str, Any]:
    conn = await db.get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT meta FROM documents WHERE filename=$1 LIMIT 1",
            COMPANY_PROFILE_FILENAME,
        )
    finally:
        await conn.close()
    if not row:
        return {}
    meta = row.get("meta") if hasattr(row, "get") else row["meta"]
    if isinstance(meta, str) and meta.strip():
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    if isinstance(meta, dict):
        profile = meta.get("profile") or {}
        return dict(profile) if isinstance(profile, dict) else {}
    return {}
