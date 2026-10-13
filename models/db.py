"""
SQLite database layer — schema creation, CRUD helpers for Projects and Documents.
Uses raw sqlite3 (no ORM overhead) with JSON columns for Pydantic model storage.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import os

load_dotenv()

DB_PATH = Path(os.getenv("DB_PATH", "db/database.db"))

# ─────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────

_CREATE_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    data        TEXT NOT NULL,        -- full Project JSON
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    doc_type        TEXT NOT NULL,
    filename        TEXT NOT NULL,
    filepath        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'ok',   -- ok | blurry | missing
    extracted_text  TEXT,
    uploaded_at     TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS change_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    field       TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    changed_by  TEXT NOT NULL,
    changed_at  TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS ad_copy (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    data        TEXT NOT NULL,        -- full AdCopy JSON
    generated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS validation_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL,
    creative_path   TEXT NOT NULL,
    status          TEXT NOT NULL,    -- passed | failed
    reasons         TEXT NOT NULL,    -- JSON array
    checked_at      TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
"""


# ─────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    """Return a sqlite3 connection, creating the DB and schema if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_SQL)
    conn.commit()
    return conn


# ─────────────────────────────────────────────
# Project CRUD
# ─────────────────────────────────────────────

def save_project(project_dict: dict) -> None:
    """Insert or replace a project (upsert by id)."""
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO projects (id, name, data, created_at, updated_at)
        VALUES (:id, :name, :data, :created_at, :updated_at)
        ON CONFLICT(id) DO UPDATE SET
            name       = excluded.name,
            data       = excluded.data,
            updated_at = excluded.updated_at
        """,
        {
            "id":         project_dict["id"],
            "name":       project_dict.get("name"),
            "data":       json.dumps(project_dict),
            "created_at": project_dict.get("created_at", now),
            "updated_at": now,
        },
    )
    conn.commit()
    conn.close()


def load_project(project_id: str) -> Optional[dict]:
    """Load a project by ID. Returns None if not found."""
    conn = get_conn()
    row = conn.execute(
        "SELECT data FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    conn.close()
    return json.loads(row["data"]) if row else None


def list_projects() -> list[dict]:
    """Return a summary list of all projects (id, name, updated_at)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, updated_at FROM projects ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_project(project_id: str) -> None:
    """Delete a project and all related rows."""
    conn = get_conn()
    conn.execute("DELETE FROM validation_results WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM ad_copy WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM change_log WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM documents WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Document CRUD
# ─────────────────────────────────────────────

def save_document(doc_dict: dict) -> None:
    """Insert or replace a document record."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO documents
            (id, project_id, doc_type, filename, filepath,
             status, extracted_text, uploaded_at)
        VALUES
            (:id, :project_id, :doc_type, :filename, :filepath,
             :status, :extracted_text, :uploaded_at)
        ON CONFLICT(id) DO UPDATE SET
            status         = excluded.status,
            extracted_text = excluded.extracted_text
        """,
        {
            "id":             doc_dict["id"],
            "project_id":     doc_dict["project_id"],
            "doc_type":       doc_dict["doc_type"],
            "filename":       doc_dict["filename"],
            "filepath":       doc_dict["filepath"],
            "status":         doc_dict.get("status", "ok"),
            "extracted_text": doc_dict.get("extracted_text"),
            "uploaded_at":    doc_dict.get(
                "uploaded_at", datetime.now(timezone.utc).isoformat()
            ),
        },
    )
    conn.commit()
    conn.close()


def get_documents(project_id: str) -> list[dict]:
    """Return all documents for a project."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM documents WHERE project_id = ? ORDER BY uploaded_at",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# Ad Copy CRUD
# ─────────────────────────────────────────────

def save_ad_copy(project_id: str, copy_dict: dict) -> None:
    """Persist a generated AdCopy record."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO ad_copy (project_id, data, generated_at)
        VALUES (?, ?, ?)
        """,
        (project_id, json.dumps(copy_dict), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_latest_ad_copy(project_id: str) -> Optional[dict]:
    """Return the most recently generated ad copy for a project."""
    conn = get_conn()
    row = conn.execute(
        """
        SELECT data FROM ad_copy
        WHERE project_id = ?
        ORDER BY generated_at DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    conn.close()
    return json.loads(row["data"]) if row else None


# ─────────────────────────────────────────────
# Validation Results CRUD
# ─────────────────────────────────────────────

def save_validation_result(project_id: str, result_dict: dict) -> None:
    """Persist a validation result for one creative."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO validation_results
            (project_id, creative_path, status, reasons, checked_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            project_id,
            result_dict["creative_path"],
            result_dict["status"],
            json.dumps(result_dict.get("reasons", [])),
            result_dict.get("checked_at", datetime.now(timezone.utc).isoformat()),
        ),
    )
    conn.commit()
    conn.close()


def get_validation_results(project_id: str) -> list[dict]:
    """Return all validation results for a project."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT * FROM validation_results
        WHERE project_id = ?
        ORDER BY checked_at DESC
        """,
        (project_id,),
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["reasons"] = json.loads(d["reasons"])
        results.append(d)
    return results
