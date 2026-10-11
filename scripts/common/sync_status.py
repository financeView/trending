"""Local sync_complete SoT for live_shadow authority (incomplete-asof Spec)."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

PathLike = Union[str, Path]

DEFAULT_SYNC_STATUS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "data",
    "cache",
    "sync_status.json",
)

_ENV_BYPASS = "TRENDING_ALLOW_INCOMPLETE_FILL"


def write_sync_status(
    *,
    sync_complete: bool,
    session_asof: str,
    elapsed_min: float = 0.0,
    path: Optional[PathLike] = None,
    written_at: Optional[str] = None,
) -> None:
    dest = Path(path or DEFAULT_SYNC_STATUS_PATH)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sync_complete": bool(sync_complete),
        "elapsed_min": float(elapsed_min),
        "written_at": written_at
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_asof": str(session_asof),
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(dest.parent), prefix=".sync_status.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
        os.replace(tmp_name, dest)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_sync_status(path: Optional[PathLike] = None) -> Optional[dict[str, Any]]:
    p = Path(path or DEFAULT_SYNC_STATUS_PATH)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def check_sync_complete_for_fill(
    *,
    fill_asof: str,
    status_path: Optional[PathLike] = None,
) -> int:
    """Return 0 if SoT authorizes fill_asof; else 1 (and print stderr)."""
    if os.environ.get(_ENV_BYPASS) == "1":
        return 0
    status = read_sync_status(status_path)
    if status is None:
        _fail(
            "no fresh sync_complete covering fill_asof=%s "
            "(missing/stale/false data/cache/sync_status.json) — re-run full sync "
            "(session_asof >= fill_asof, sync_complete=true) before live_shadow fill"
            % fill_asof
        )
        return 1
    if status.get("sync_complete") is not True:
        _fail(
            "no fresh sync_complete covering fill_asof=%s "
            "(missing/stale/false data/cache/sync_status.json) — re-run full sync "
            "(session_asof >= fill_asof, sync_complete=true) before live_shadow fill"
            % fill_asof
        )
        return 1
    tip = status.get("session_asof")
    if not isinstance(tip, str) or not tip:
        _fail(
            "no fresh sync_complete covering fill_asof=%s "
            "(missing/stale/false data/cache/sync_status.json) — re-run full sync "
            "(session_asof >= fill_asof, sync_complete=true) before live_shadow fill"
            % fill_asof
        )
        return 1
    if tip < str(fill_asof):
        _fail(
            "no fresh sync_complete covering fill_asof=%s "
            "(missing/stale/false data/cache/sync_status.json) — re-run full sync "
            "(session_asof >= fill_asof, sync_complete=true) before live_shadow fill"
            % fill_asof
        )
        return 1
    return 0


def _fail(msg: str) -> None:
    print("[sync_authority] " + msg, file=__import__("sys").stderr)
