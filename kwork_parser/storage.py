from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .models import Project
from .scoring import ScoreResult


@dataclass(slots=True)
class NotificationCandidate:
    project: Project
    rule_result: ScoreResult
    ai_result: ScoreResult | None


@dataclass(slots=True)
class ProjectFeedback:
    project_id: int
    feedback: str
    telegram_user_id: int | None
    telegram_username: str
    payload: dict


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
                scored_at TEXT,
                rule_score REAL,
                rule_summary TEXT,
                rule_reasons_json TEXT,
                ai_score REAL,
                ai_summary TEXT,
                ai_reasons_json TEXT,
                notification_status TEXT NOT NULL DEFAULT 'pending',
                notification_error TEXT,
                ignored_reason TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_feedback (
                project_id INTEGER NOT NULL,
                feedback TEXT NOT NULL,
                telegram_user_id INTEGER NOT NULL DEFAULT 0,
                telegram_username TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (project_id, telegram_user_id)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._migrate_schema()
        self._migrate_feedback_schema()
        self.connection.commit()

    def _migrate_schema(self) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(projects)").fetchall()
        }
        migrations = {
            "scored_at": "ALTER TABLE projects ADD COLUMN scored_at TEXT",
            "rule_reasons_json": "ALTER TABLE projects ADD COLUMN rule_reasons_json TEXT",
            "ai_reasons_json": "ALTER TABLE projects ADD COLUMN ai_reasons_json TEXT",
            "notification_status": (
                "ALTER TABLE projects ADD COLUMN notification_status TEXT NOT NULL DEFAULT 'pending'"
            ),
            "notification_error": "ALTER TABLE projects ADD COLUMN notification_error TEXT",
            "ignored_reason": "ALTER TABLE projects ADD COLUMN ignored_reason TEXT",
        }
        for column, statement in migrations.items():
            if column not in columns:
                self.connection.execute(statement)

        self.connection.execute(
            """
            UPDATE projects
            SET notification_status = CASE
                    WHEN notified_at IS NOT NULL THEN 'sent'
                    WHEN ignored_reason IS NOT NULL THEN 'skipped'
                    ELSE notification_status
                END
            """
        )

    def _migrate_feedback_schema(self) -> None:
        columns = self.connection.execute("PRAGMA table_info(project_feedback)").fetchall()
        primary_key_columns = [row["name"] for row in sorted(columns, key=lambda row: row["pk"]) if row["pk"]]
        telegram_user_column = next(
            (row for row in columns if row["name"] == "telegram_user_id"),
            None,
        )
        has_composite_key = primary_key_columns == ["project_id", "telegram_user_id"]
        telegram_user_required = bool(telegram_user_column and telegram_user_column["notnull"])
        if has_composite_key and telegram_user_required:
            return

        self.connection.execute(
            """
            CREATE TABLE project_feedback_new (
                project_id INTEGER NOT NULL,
                feedback TEXT NOT NULL,
                telegram_user_id INTEGER NOT NULL DEFAULT 0,
                telegram_username TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (project_id, telegram_user_id)
            )
            """
        )
        self.connection.execute(
            """
            INSERT OR REPLACE INTO project_feedback_new (
                project_id, feedback, telegram_user_id, telegram_username, updated_at, payload_json
            )
            SELECT
                project_id,
                feedback,
                COALESCE(telegram_user_id, 0),
                telegram_username,
                updated_at,
                payload_json
            FROM project_feedback
            """
        )
        self.connection.execute("DROP TABLE project_feedback")
        self.connection.execute("ALTER TABLE project_feedback_new RENAME TO project_feedback")

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
                id, title, url, created_at, scored_at, rule_score, rule_summary,
                rule_reasons_json, notification_status, notification_error,
                ignored_reason, payload_json
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, 'pending', NULL, NULL, ?)
            """,
            (
                project.id,
                project.title,
                project.url,
                project.created_at.isoformat(sep=" ") if project.created_at else None,
                rule_result.score,
                rule_result.summary,
                json.dumps(rule_result.reasons, ensure_ascii=False),
                json.dumps(project.raw, ensure_ascii=False),
            ),
        )
        self.connection.commit()

    def get_notification_candidates(self, include_previewed: bool) -> list[NotificationCandidate]:
        statuses = ["pending", "error"]
        if include_previewed:
            statuses.append("previewed")

        placeholders = ", ".join("?" for _ in statuses)
        rows = self.connection.execute(
            f"""
            SELECT *
            FROM projects
            WHERE notified_at IS NULL
              AND ignored_reason IS NULL
              AND notification_status IN ({placeholders})
            ORDER BY created_at IS NULL, created_at ASC, seen_at ASC
            """,
            statuses,
        ).fetchall()
        return [self._candidate_from_row(row) for row in rows]

    def save_ai_result(self, project_id: int, ai_result: ScoreResult) -> None:
        self.connection.execute(
            """
            UPDATE projects
            SET ai_score = ?,
                ai_summary = ?,
                ai_reasons_json = ?,
                notification_error = NULL
            WHERE id = ?
            """,
            (
                ai_result.score,
                ai_result.summary,
                json.dumps(ai_result.reasons, ensure_ascii=False),
                project_id,
            ),
        )
        self.connection.commit()

    def mark_previewed(self, project_id: int, ai_result: ScoreResult | None) -> None:
        self.connection.execute(
            """
            UPDATE projects
            SET notification_status = 'previewed',
                notification_error = NULL,
                ai_score = ?,
                ai_summary = ?,
                ai_reasons_json = ?
            WHERE id = ?
            """,
            (
                ai_result.score if ai_result else None,
                ai_result.summary if ai_result else None,
                json.dumps(ai_result.reasons, ensure_ascii=False) if ai_result else None,
                project_id,
            ),
        )
        self.connection.commit()

    def mark_ignored(self, project_id: int, reason: str, ai_result: ScoreResult | None = None) -> None:
        self.connection.execute(
            """
            UPDATE projects
            SET notification_status = 'skipped',
                ignored_reason = ?,
                notification_error = NULL,
                ai_score = ?,
                ai_summary = ?,
                ai_reasons_json = ?
            WHERE id = ?
            """,
            (
                reason,
                ai_result.score if ai_result else None,
                ai_result.summary if ai_result else None,
                json.dumps(ai_result.reasons, ensure_ascii=False) if ai_result else None,
                project_id,
            ),
        )
        self.connection.commit()

    def mark_error(self, project_id: int, error: str) -> None:
        self.connection.execute(
            """
            UPDATE projects
            SET notification_status = 'error',
                notification_error = ?
            WHERE id = ?
            """,
            (error, project_id),
        )
        self.connection.commit()

    def mark_notified(self, project_id: int, ai_result: ScoreResult | None) -> None:
        self.connection.execute(
            """
            UPDATE projects
            SET notified_at = CURRENT_TIMESTAMP,
                notification_status = 'sent',
                notification_error = NULL,
                ai_score = ?,
                ai_summary = ?,
                ai_reasons_json = ?
            WHERE id = ?
            """,
            (
                ai_result.score if ai_result else None,
                ai_result.summary if ai_result else None,
                json.dumps(ai_result.reasons, ensure_ascii=False) if ai_result else None,
                project_id,
            ),
        )
        self.connection.commit()

    def save_feedback(self, feedback: ProjectFeedback) -> None:
        telegram_user_id = self._feedback_user_id(feedback.telegram_user_id)
        self.connection.execute(
            """
            INSERT INTO project_feedback (
                project_id, feedback, telegram_user_id, telegram_username, updated_at, payload_json
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(project_id, telegram_user_id) DO UPDATE SET
                feedback = excluded.feedback,
                telegram_username = excluded.telegram_username,
                updated_at = CURRENT_TIMESTAMP,
                payload_json = excluded.payload_json
            """,
            (
                feedback.project_id,
                feedback.feedback,
                telegram_user_id,
                feedback.telegram_username,
                json.dumps(feedback.payload, ensure_ascii=False),
            ),
        )
        self.connection.commit()

    def get_feedback(self, project_id: int, telegram_user_id: int | None = None) -> ProjectFeedback | None:
        if telegram_user_id is None:
            row = self.connection.execute(
                """
                SELECT project_id, feedback, telegram_user_id, telegram_username, payload_json
                FROM project_feedback
                WHERE project_id = ?
                ORDER BY updated_at DESC, telegram_user_id DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT project_id, feedback, telegram_user_id, telegram_username, payload_json
                FROM project_feedback
                WHERE project_id = ? AND telegram_user_id = ?
                """,
                (project_id, self._feedback_user_id(telegram_user_id)),
            ).fetchone()
        if not row:
            return None
        return self._feedback_from_row(row)

    def list_feedback(self, project_id: int) -> list[ProjectFeedback]:
        rows = self.connection.execute(
            """
            SELECT project_id, feedback, telegram_user_id, telegram_username, payload_json
            FROM project_feedback
            WHERE project_id = ?
            ORDER BY updated_at DESC, telegram_user_id DESC
            """,
            (project_id,),
        ).fetchall()
        return [self._feedback_from_row(row) for row in rows]

    def _feedback_from_row(self, row: sqlite3.Row) -> ProjectFeedback:
        return ProjectFeedback(
            project_id=int(row["project_id"]),
            feedback=row["feedback"],
            telegram_user_id=int(row["telegram_user_id"]) if row["telegram_user_id"] else None,
            telegram_username=row["telegram_username"] or "",
            payload=json.loads(row["payload_json"]),
        )

    def get_telegram_update_offset(self) -> int | None:
        row = self.connection.execute(
            "SELECT value FROM app_state WHERE key = 'telegram_update_offset'"
        ).fetchone()
        if not row:
            return None
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return None

    def set_telegram_update_offset(self, offset: int) -> None:
        self.connection.execute(
            """
            INSERT INTO app_state (key, value)
            VALUES ('telegram_update_offset', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(offset),),
        )
        self.connection.commit()

    def _candidate_from_row(self, row: sqlite3.Row) -> NotificationCandidate:
        raw = json.loads(row["payload_json"])
        rule_result = ScoreResult(
            score=float(row["rule_score"] or 0),
            summary=row["rule_summary"] or "",
            reasons=self._load_reasons(row["rule_reasons_json"]),
        )
        ai_result = None
        if row["ai_score"] is not None:
            ai_result = ScoreResult(
                score=float(row["ai_score"]),
                summary=row["ai_summary"] or "",
                reasons=self._load_reasons(row["ai_reasons_json"]),
            )
        return NotificationCandidate(
            project=Project.from_api(raw),
            rule_result=rule_result,
            ai_result=ai_result,
        )

    def _load_reasons(self, value: str | None) -> list[str]:
        if not value:
            return []
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            return []
        return [str(item) for item in parsed]

    def _feedback_user_id(self, telegram_user_id: int | None) -> int:
        return telegram_user_id if telegram_user_id is not None else 0
