from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Project
from .scoring import ScoreResult


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                created_at TEXT,
                seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                notified_at TEXT,
                rule_score REAL,
                rule_summary TEXT,
                ai_score REAL,
                ai_summary TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def is_known(self, project_id: int) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM projects WHERE id = ? LIMIT 1",
            (project_id,),
        ).fetchone()
        return row is not None

    def is_empty(self) -> bool:
        row = self.connection.execute("SELECT COUNT(*) AS count FROM projects").fetchone()
        return not row or row["count"] == 0

    def save_project(self, project: Project, rule_result: ScoreResult) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO projects (
                id, title, url, created_at, rule_score, rule_summary, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project.id,
                project.title,
                project.url,
                project.created_at.isoformat(sep=" ") if project.created_at else None,
                rule_result.score,
                rule_result.summary,
                json.dumps(project.raw, ensure_ascii=False),
            ),
        )
        self.connection.commit()

    def mark_notified(self, project_id: int, ai_result: ScoreResult | None) -> None:
        self.connection.execute(
            """
            UPDATE projects
            SET notified_at = CURRENT_TIMESTAMP,
                ai_score = ?,
                ai_summary = ?
            WHERE id = ?
            """,
            (
                ai_result.score if ai_result else None,
                ai_result.summary if ai_result else None,
                project_id,
            ),
        )
        self.connection.commit()
