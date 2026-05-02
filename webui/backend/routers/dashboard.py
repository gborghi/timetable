"""Dashboard endpoints: dataset state already lives in routers/dataset.py;
this router hosts the `/api/dashboard/graph` endpoint that powers the
Network panel, plus Import/Export DB and snapshot management."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import zipfile
from typing import Any

from fastapi import (APIRouter, Depends, File, HTTPException, Query,
                      UploadFile)
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .. import db as db_mod
from ..db import get_db
from ..services.graph import build_graph
from ..utils.ttl_cache import cached as ttl_cached

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ----------------------------- helpers --------------------------------

# webui/data/snapshots/
DATA_DIR = db_mod.DATA_DIR
SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)


def _safe_filename(name: str) -> str:
    """Strip any path component and reject anything outside [A-Za-z0-9._-]."""
    base = os.path.basename(name or "")
    if not base:
        raise HTTPException(400, "filename vuoto")
    if re.search(r"[^A-Za-z0-9._-]", base):
        raise HTTPException(400, "filename non valido")
    return base


def _alembic_revision() -> str | None:
    try:
        with db_mod.engine.connect() as conn:
            row = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).first()
            return str(row[0]) if row else None
    except Exception:
        return None


def _table_csv(conn, table: str) -> bytes:
    """Dump one table as CSV bytes using the live engine connection."""
    res = conn.execute(text(f'SELECT * FROM "{table}"'))
    cols = list(res.keys())
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(cols)
    for row in res:
        w.writerow([("" if v is None else v) for v in row])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def _build_export_zip(*, schema_only: bool = False) -> tuple[bytes, dict]:
    """Build the export zip in memory. Returns (zip_bytes, metadata_dict).

    Layout inside the zip:
      database.db                        -- raw SQLite file (when SQLite)
      metadata.json                      -- schema_version + counts + hashes
      tables/<table>.csv                 -- one CSV per table
                                            (skipped when schema_only=True)
    """
    insp = inspect(db_mod.engine)
    tables = sorted(insp.get_table_names())
    row_counts: dict[str, int] = {}
    csv_hashes: dict[str, str] = {}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # Raw SQLite file (when applicable). Fast atomic restore path.
        if db_mod.IS_SQLITE and db_mod.DB_PATH and os.path.exists(db_mod.DB_PATH):
            with open(db_mod.DB_PATH, "rb") as f:
                z.writestr("database.db", f.read())
        # Per-table CSVs (always for documentation/portability)
        with db_mod.engine.connect() as conn:
            for t in tables:
                try:
                    cnt = conn.execute(
                        text(f'SELECT COUNT(*) FROM "{t}"')
                    ).scalar() or 0
                except Exception:
                    cnt = 0
                row_counts[t] = int(cnt)
                if schema_only:
                    continue
                try:
                    body = _table_csv(conn, t)
                except Exception:
                    continue
                z.writestr(f"tables/{t}.csv", body)
                csv_hashes[t] = hashlib.sha256(body).hexdigest()
        meta = {
            "kind": "pitantum-db-export",
            "schema_version": _alembic_revision(),
            "schema_only": bool(schema_only),
            "exported_at": dt.datetime.now().isoformat(timespec="seconds"),
            "tables": tables,
            "row_counts": row_counts,
            "csv_sha256": csv_hashes,
            "is_sqlite": db_mod.IS_SQLITE,
        }
        z.writestr("metadata.json", json.dumps(meta, indent=2))
    return buf.getvalue(), meta


def _restore_zip(blob: bytes) -> dict:
    """Apply an export zip to the running DB. Strategy:
       - if the zip contains `database.db` AND we're on SQLite,
         atomically replace the live DB file (closes connections,
         copies, reconnects).
       - otherwise: not yet supported (would require row-by-row import
         from CSV). Returns 400.
    """
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise HTTPException(400, "il file caricato non e' un zip valido")
    names = z.namelist()
    if "metadata.json" not in names:
        raise HTTPException(
            400,
            "metadata.json mancante: il file non sembra un export piTantum.",
        )
    try:
        meta = json.loads(z.read("metadata.json").decode("utf-8"))
    except Exception as e:
        raise HTTPException(400, f"metadata.json non parseable: {e}")
    if meta.get("kind") != "pitantum-db-export":
        raise HTTPException(
            400, f"export non riconosciuto: kind={meta.get('kind')}"
        )
    if not db_mod.IS_SQLITE:
        raise HTTPException(
            400,
            "import-db: solo SQLite supportato (per Postgres serve un "
            "pg_restore lato server, non disponibile da qui).",
        )
    if "database.db" not in names:
        raise HTTPException(
            400,
            "database.db assente nel zip; il restore CSV-per-CSV non e' "
            "ancora supportato.",
        )
    new_db = z.read("database.db")
    # Atomically swap the SQLite file
    db_path = db_mod.DB_PATH
    if not db_path:
        raise HTTPException(500, "DB path non risolvibile")
    # Close pooled connections so Windows lets us replace the file
    db_mod.engine.dispose()
    backup_path = db_path + ".pre_import_backup"
    try:
        if os.path.exists(db_path):
            shutil.copy2(db_path, backup_path)
        with open(db_path, "wb") as f:
            f.write(new_db)
    except Exception as e:
        # Best-effort rollback
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, db_path)
        raise HTTPException(500, f"errore swap DB: {e}")
    finally:
        # New connections will auto-open against the new file
        pass
    # Bump mutation epoch so caches invalidate
    try:
        from ..utils.ttl_cache import bump_mutation
        bump_mutation()
    except Exception:
        pass
    return {
        "ok": True,
        "schema_version": meta.get("schema_version"),
        "exported_at": meta.get("exported_at"),
        "tables": meta.get("tables"),
        "row_counts": meta.get("row_counts"),
        "backup": backup_path,
    }


# ----------------------------- endpoints ------------------------------


@router.get("/graph")
def get_graph(
    mode: str = Query(
        "classes",
        description=(
            "'classes' -> nodes are SchoolClass, edges weighted by shared "
            "teachers; 'teachers' -> nodes are Teacher, edges weighted by "
            "shared classes."
        ),
        pattern="^(classes|teachers)$",
    ),
    db: Session = Depends(get_db),
):
    """Network graph. Server-side cache 60s + mutation-aware; plus
    Cache-Control: no-store on response so the browser never serves a
    stale frame after an import."""
    try:
        body = ttl_cached(
            f"dashboard.graph.{mode}",
            ttl_s=60.0,
            mutation_aware=True,
            compute=lambda: build_graph(db, mode),
        )
        return JSONResponse(
            content=body,
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# ----- Import / Export DB ----------------------------------------------

@router.get("/export-db")
def export_db(
    schema_only: bool = Query(
        False,
        description=(
            "If true, omits the table data — useful as a 'template' "
            "starter package for a different school."
        ),
    ),
):
    """Build a zip containing:
      - database.db    (raw SQLite, when applicable)
      - tables/*.csv   (one CSV per table, BOM+UTF-8)
      - metadata.json  (schema_version + row counts + sha256)
    """
    body, meta = _build_export_zip(schema_only=schema_only)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    fn = f"pitantum_export_{ts}.zip"
    return StreamingResponse(
        io.BytesIO(body),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{fn}"',
            "X-Pitantum-Schema-Version": meta.get("schema_version") or "",
        },
    )


@router.post("/import-db")
async def import_db(file: UploadFile = File(...)):
    """Upload a zip previously produced by /api/dashboard/export-db
    and replace the running DB with it. SQLite-only path: writes a
    .pre_import_backup file next to the live DB before the swap.
    """
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "file vuoto")
    return _restore_zip(blob)


@router.post("/snapshot/create")
def snapshot_create():
    """Save a timestamped snapshot zip in webui/data/snapshots/ and
    return the filename + size."""
    body, meta = _build_export_zip(schema_only=False)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    fn = f"snapshot_{ts}.zip"
    path = os.path.join(SNAPSHOTS_DIR, fn)
    with open(path, "wb") as f:
        f.write(body)
    return {
        "ok": True,
        "filename": fn,
        "path": path,
        "size_bytes": len(body),
        "schema_version": meta.get("schema_version"),
    }


@router.get("/snapshot/list")
def snapshot_list():
    """List all snapshot zips in webui/data/snapshots/."""
    out: list[dict[str, Any]] = []
    if not os.path.isdir(SNAPSHOTS_DIR):
        return out
    for fn in sorted(os.listdir(SNAPSHOTS_DIR), reverse=True):
        if not fn.lower().endswith(".zip"):
            continue
        full = os.path.join(SNAPSHOTS_DIR, fn)
        try:
            stat = os.stat(full)
        except OSError:
            continue
        out.append({
            "filename": fn,
            "size_bytes": stat.st_size,
            "modified_at": dt.datetime.fromtimestamp(
                stat.st_mtime
            ).isoformat(timespec="seconds"),
        })
    return out


@router.post("/snapshot/restore/{filename}")
def snapshot_restore(filename: str):
    fn = _safe_filename(filename)
    full = os.path.join(SNAPSHOTS_DIR, fn)
    if not os.path.isfile(full):
        raise HTTPException(404, f"snapshot {fn} non trovato")
    with open(full, "rb") as f:
        return _restore_zip(f.read())


@router.delete("/snapshot/{filename}")
def snapshot_delete(filename: str):
    fn = _safe_filename(filename)
    full = os.path.join(SNAPSHOTS_DIR, fn)
    if not os.path.isfile(full):
        raise HTTPException(404, f"snapshot {fn} non trovato")
    os.remove(full)
    return {"ok": True, "deleted": fn}
