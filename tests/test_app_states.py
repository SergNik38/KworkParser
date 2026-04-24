from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kwork_parser.app import Application
from kwork_parser.config import Settings
from kwork_parser.models import Project


def make_settings(database_path: Path, *, dry_run: bool, skip_first_run: bool = False) -> Settings:
    return Settings(
        poll_interval_seconds=45,
        request_timeout_seconds=20,
        request_retries=1,
        retry_backoff_seconds=1,
        max_pages=1,
        database_path=database_path,
        skip_existing_on_first_run=skip_first_run,
        min_rule_score=55.0,
        min_ai_score=70.0,
        min_price=None,
        max_price=None,
        min_hiring_percent=None,
        category_ids=[],
        include_keywords=["python"],
        exclude_keywords=[],
        dry_run=dry_run,
        telegram_bot_token=None,
        telegram_chat_id=None,
        openrouter_api_key=None,
        openrouter_model=None,
        openrouter_site_url=None,
        openrouter_site_name=None,
        response_draft_api_key=None,
        response_draft_model=None,
        response_draft_base_url=None,
        response_draft_timeout_seconds=None,
        ai_profile_brief="",
        ai_extra_instructions="",
    )


def make_project(project_id: int = 1001) -> Project:
    return Project.from_api(
        {
            "id": project_id,
            "name": "Python Telegram bot",
            "description": "Need Python automation for Telegram API",
            "category_id": "1",
            "priceLimit": "10000",
            "possiblePriceLimit": "",
            "max_days": "5",
            "user": {
                "username": "customer",
                "data": {
                    "wants_count": "5",
                    "wants_hired_percent": "50",
                },
            },
            "wantUserGetProfileUrl": "https://kwork.ru/user/customer",
            "kwork_count": "2",
            "views_dirty": "10",
            "date_create": "2026-04-23 10:00:00",
            "date_active": "2026-04-23 10:00:00",
            "date_expire": "2026-04-30 10:00:00",
            "hasPortfolioAvailable": True,
        }
    )


class FakeClient:
    def __init__(self, projects: list[Project]) -> None:
        self.projects = projects

    def fetch_projects(self, page: int = 1) -> list[Project]:
        return self.projects if page == 1 else []


class FakeNotifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[int] = []
        self.drafts: list[int] = []

    def send(self, project: Project, rule_result, ai_result) -> None:
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append(project.id)

    def send_response_draft(self, project: Project, draft_text: str) -> None:
        self.drafts.append(project.id)


class ApplicationStateTests(unittest.TestCase):
    def make_app(self, *, dry_run: bool, skip_first_run: bool = False) -> Application:
        self.tmpdir = tempfile.TemporaryDirectory()
        settings = make_settings(
            Path(self.tmpdir.name) / "kwork_parser.db",
            dry_run=dry_run,
            skip_first_run=skip_first_run,
        )
        app = Application(settings)
        app.client = FakeClient([make_project()])
        app.notifier = FakeNotifier()
        return app

    def tearDown(self) -> None:
        if hasattr(self, "tmpdir"):
            self.tmpdir.cleanup()

    def fetch_row(self, app: Application):
        return app.storage.connection.execute("SELECT * FROM projects WHERE id = 1001").fetchone()

    def test_dry_run_previews_without_marking_notified(self) -> None:
        app = self.make_app(dry_run=True)

        processed = app.run_once()

        row = self.fetch_row(app)
        self.assertEqual(processed, 1)
        self.assertEqual(row["notification_status"], "previewed")
        self.assertIsNone(row["notified_at"])
        self.assertEqual(app.storage.get_notification_candidates(include_previewed=False), [])
        self.assertEqual(len(app.storage.get_notification_candidates(include_previewed=True)), 1)

    def test_previewed_project_is_sent_when_dry_run_is_disabled(self) -> None:
        app = self.make_app(dry_run=True)
        app.run_once()

        app.settings.dry_run = False
        processed = app.run_once()

        row = self.fetch_row(app)
        self.assertEqual(processed, 1)
        self.assertEqual(row["notification_status"], "sent")
        self.assertIsNotNone(row["notified_at"])
        self.assertEqual(app.notifier.sent, [1001, 1001])
        self.assertEqual(app.notifier.drafts, [])

    def test_telegram_error_keeps_project_retryable(self) -> None:
        app = self.make_app(dry_run=False)
        app.notifier = FakeNotifier(fail=True)

        processed = app.run_once()

        row = self.fetch_row(app)
        self.assertEqual(processed, 0)
        self.assertEqual(row["notification_status"], "error")
        self.assertIn("Telegram notification failed", row["notification_error"])
        self.assertIsNone(row["notified_at"])
        self.assertEqual(len(app.storage.get_notification_candidates(include_previewed=True)), 1)

    def test_bootstrap_marks_initial_feed_skipped(self) -> None:
        app = self.make_app(dry_run=False, skip_first_run=True)

        processed = app.run_once()

        row = self.fetch_row(app)
        self.assertEqual(processed, 0)
        self.assertEqual(row["notification_status"], "skipped")
        self.assertEqual(row["ignored_reason"], "bootstrap first run")
        self.assertEqual(app.storage.get_notification_candidates(include_previewed=True), [])


if __name__ == "__main__":
    unittest.main()
