from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def compute_file_signature(path: Path) -> Dict[str, Any]:
    """
    Returns filesize, modified timestamp, and sha256 checksum for the file.
    """
    stat = path.stat()
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return {
        "filesize": stat.st_size,
        "file_mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc),
        "checksum": checksum.hexdigest(),
    }


async def log_ingest_result(
    conn,
    filename: str,
    status: str,
    detail: Optional[str],
    signature: Optional[Dict[str, Any]] = None,
) -> None:
    sig = signature or {}
    await conn.execute(
        """
        INSERT INTO ingest_log(filename, status, detail, filesize, file_mtime, checksum)
        VALUES ($1,$2,$3,$4,$5,$6)
        """,
        filename,
        status,
        detail,
        sig.get("filesize"),
        sig.get("file_mtime"),
        sig.get("checksum"),
    )
