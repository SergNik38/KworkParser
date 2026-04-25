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


@dataclass(slots=True)
class HealthSnapshot:
    total_projects: int
    status_counts: dict[str, int]
    feedback_counts: dict[str, int]
    last_seen_at: str
    last_notified_at: str
    error_count: int
    latest_error: str


@dataclass(slots=True)
class ResponseDraft:
    project_id: int
    text: str
    variant: str
    demo_available: bool = False
    demo_summary: str = ""
    demo_path: str = ""
    demo_archive_path: str = ""


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
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS response_drafts (
                project_id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                variant TEXT NOT NULL DEFAULT 'default',
                demo_available INTEGER NOT NULL DEFAULT 0,
                demo_summary TEXT,
                demo_path TEXT,
                demo_archive_path TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._migrate_schema()
        self._migrate_feedback_schema()
        self._migrate_response_drafts_schema()
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

    def _migrate_response_drafts_schema(self) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(response_drafts)").fetchall()
        }
        migrations = {
            "demo_available": "ALTER TABLE response_drafts ADD COLUMN demo_available INTEGER NOT NULL DEFAULT 0",
            "demo_summary": "ALTER TABLE response_drafts ADD COLUMN demo_summary TEXT",
            "demo_path": "ALTER TABLE response_drafts ADD COLUMN demo_path TEXT",
            "demo_archive_path": "ALTER TABLE response_drafts ADD COLUMN demo_archive_path TEXT",
        }
        for column, statement in migrations.items():
            if column not in columns:
                self.connection.execute(statement)

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

    def update_rule_result(self, project_id: int, rule_result: ScoreResult) -> None:
        self.connection.execute(
            """
            UPDATE projects
            SET scored_at = CURRENT_TIMESTAMP,
                rule_score = ?,
                rule_summary = ?,
                rule_reasons_json = ?
            WHERE id = ?
            """,
            (
                rule_result.score,
                rule_result.summary,
                json.dumps(rule_result.reasons, ensure_ascii=False),
                project_id,
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

    def get_project_candidate(self, project_id: int) -> NotificationCandidate | None:
        row = self.connection.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if not row:
            return None
        return self._candidate_from_row(row)

    def get_hide_similar_projects(self, limit: int = 100) -> list[Project]:
        rows = self.connection.execute(
            """
            SELECT p.payload_json
            FROM projects p
            JOIN project_feedback f ON f.project_id = p.id
            WHERE f.feedback = 'hide_similar'
            GROUP BY p.id
            ORDER BY MAX(f.updated_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        projects: list[Project] = []
        for row in rows:
            try:
                projects.append(Project.from_api(json.loads(row["payload_json"])))
            except (ValueError, json.JSONDecodeError):
                continue
        return projects

    def get_health_snapshot(self) -> HealthSnapshot:
        total_row = self.connection.execute("SELECT COUNT(*) AS count FROM projects").fetchone()
        status_rows = self.connection.execute(
            """
            SELECT notification_status, COUNT(*) AS count
            FROM projects
            GROUP BY notification_status
            """
        ).fetchall()
        feedback_rows = self.connection.execute(
            """
            SELECT feedback, COUNT(*) AS count
            FROM project_feedback
            GROUP BY feedback
            """
        ).fetchall()
        dates_row = self.connection.execute(
            """
            SELECT
                MAX(seen_at) AS last_seen_at,
                MAX(notified_at) AS last_notified_at
            FROM projects
            """
        ).fetchone()
        error_row = self.connection.execute(
            """
            SELECT notification_error
            FROM projects
            WHERE notification_error IS NOT NULL
            ORDER BY seen_at DESC
            LIMIT 1
            """
        ).fetchone()

        status_counts = {
            row["notification_status"] or "unknown": int(row["count"])
            for row in status_rows
        }
        feedback_counts = {
            row["feedback"] or "unknown": int(row["count"])
            for row in feedback_rows
        }
        return HealthSnapshot(
            total_projects=int(total_row["count"] or 0),
            status_counts=status_counts,
            feedback_counts=feedback_counts,
            last_seen_at=dates_row["last_seen_at"] or "n/a",
            last_notified_at=dates_row["last_notified_at"] or "n/a",
            error_count=status_counts.get("error", 0),
            latest_error=(error_row["notification_error"] if error_row else "") or "",
        )

    def save_response_draft(self, draft: ResponseDraft) -> None:
        self.connection.execute(
            """
            INSERT INTO response_drafts (
                project_id, text, variant, demo_available, demo_summary,
                demo_path, demo_archive_path, status, updated_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, NULL, 'draft', CURRENT_TIMESTAMP)
            ON CONFLICT(project_id) DO UPDATE SET
                text = excluded.text,
                variant = excluded.variant,
                demo_available = excluded.demo_available,
                demo_summary = excluded.demo_summary,
                demo_path = NULL,
                demo_archive_path = NULL,
                status = 'draft',
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                draft.project_id,
                draft.text,
                draft.variant,
                1 if draft.demo_available else 0,
                draft.demo_summary or None,
            ),
        )
        self.connection.commit()

    def get_response_draft(self, project_id: int) -> ResponseDraft | None:
        row = self.connection.execute(
            """
            SELECT project_id, text, variant, demo_available, demo_summary, demo_path, demo_archive_path
            FROM response_drafts
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        if not row:
            return None
        return ResponseDraft(
            project_id=int(row["project_id"]),
            text=row["text"],
            variant=row["variant"],
            demo_available=bool(row["demo_available"]),
            demo_summary=row["demo_summary"] or "",
            demo_path=row["demo_path"] or "",
            demo_archive_path=row["demo_archive_path"] or "",
        )

    def save_demo_project_artifacts(self, project_id: int, demo_path: str, demo_archive_path: str) -> None:
        self.connection.execute(
            """
            UPDATE response_drafts
            SET demo_path = ?,
                demo_archive_path = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE project_id = ?
            """,
            (demo_path, demo_archive_path, project_id),
        )
        self.connection.commit()

    def mark_response_draft_sent_manually(self, project_id: int) -> None:
        self.connection.execute(
            """
            UPDATE response_drafts
            SET status = 'sent_manually',
                updated_at = CURRENT_TIMESTAMP
            WHERE project_id = ?
            """,
            (project_id,),
        )
        self.connection.commit()

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
