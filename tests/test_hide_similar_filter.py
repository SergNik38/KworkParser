from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kwork_parser.app import Application
from kwork_parser.config import Settings
from kwork_parser.models import Project
from kwork_parser.scoring import ScoreResult, apply_hide_similar_penalty
from kwork_parser.storage import ProjectFeedback


def make_settings(database_path: Path) -> Settings:
    return Settings(
        poll_interval_seconds=45,
        request_timeout_seconds=20,
        request_retries=1,
        retry_backoff_seconds=1,
        max_pages=1,
        database_path=database_path,
        skip_existing_on_first_run=False,
        min_rule_score=55.0,
        min_ai_score=70.0,
        min_price=None,
        max_price=None,
        min_hiring_percent=None,
        category_ids=[],
        include_keywords=[],
        exclude_keywords=[],
        dry_run=True,
        telegram_bot_token=None,
        telegram_chat_id=None,
        openrouter_api_key=None,
        openrouter_model=None,
        openrouter_site_url=None,
        openrouter_site_name=None,
        ai_profile_brief="",
        ai_extra_instructions="",
    )


def make_project(
    project_id: int,
    *,
    title: str,
    description: str,
    category_id: int,
    price: int = 10000,
) -> Project:
    return Project.from_api(
        {
            "id": str(project_id),
            "name": title,
            "description": description,
            "category_id": str(category_id),
            "priceLimit": str(price),
            "user": {},
        }
    )


class FakeClient:
    def __init__(self, projects: list[Project]) -> None:
        self.projects = projects

    def fetch_projects(self, page: int = 1) -> list[Project]:
        return self.projects if page == 1 else []


class FakeNotifier:
    def send(self, project: Project, rule_result: ScoreResult, ai_result: ScoreResult | None) -> None:
        return


class HideSimilarFilterTests(unittest.TestCase):
    def test_hide_similar_penalty_matches_category_and_shared_terms(self) -> None:
        hidden_project = make_project(
            1001,
            title="Парсер отзывов Авито",
            description="Нужна автоматизация сбора отзывов и карточек Авито",
            category_id=7,
        )
        new_project = make_project(
            1002,
            title="Сделать парсер отзывов Авито",
            description="Автоматизация карточек и отзывов для Авито",
            category_id=7,
        )

        result = apply_hide_similar_penalty(
            new_project,
            ScoreResult(80.0, "base", ["base reason"]),
            [hidden_project],
        )

        self.assertEqual(result.score, 55.0)
        self.assertIn("похож на скрытый ранее заказ #1001", result.reasons[0])

    def test_hide_similar_penalty_does_not_match_unrelated_project(self) -> None:
        hidden_project = make_project(
            1001,
            title="Парсер отзывов Авито",
            description="Нужна автоматизация сбора отзывов и карточек Авито",
            category_id=7,
        )
        new_project = make_project(
            1002,
            title="Telegram бот для заявок",
            description="Нужна интеграция Telegram API с CRM",
            category_id=9,
        )
        base_result = ScoreResult(80.0, "base", ["base reason"])

        result = apply_hide_similar_penalty(new_project, base_result, [hidden_project])

        self.assertIs(result, base_result)

    def test_application_uses_hide_similar_feedback_before_saving_new_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = Application(make_settings(Path(tmpdir) / "kwork_parser.db"))
            hidden_project = make_project(
                1001,
                title="Парсер отзывов Авито",
                description="Нужна автоматизация сбора отзывов и карточек Авито",
                category_id=7,
            )
            new_project = make_project(
                1002,
                title="Сделать парсер отзывов Авито",
                description="Автоматизация карточек и отзывов для Авито",
                category_id=7,
            )
            app.storage.save_project(hidden_project, ScoreResult(80.0, "base", []))
            app.storage.mark_notified(hidden_project.id, None)
            app.storage.save_feedback(
                ProjectFeedback(
                    project_id=hidden_project.id,
                    feedback="hide_similar",
                    telegram_user_id=123,
                    telegram_username="user",
                    payload={},
                )
            )
            app.client = FakeClient([new_project])
            app.notifier = FakeNotifier()

            processed = app.run_once()

            row = app.storage.connection.execute(
                "SELECT rule_score, rule_summary, notification_status FROM projects WHERE id = 1002"
            ).fetchone()
            self.assertEqual(processed, 0)
            self.assertEqual(row["rule_score"], 35.0)
            self.assertIn("похож на скрытый ранее заказ #1001", row["rule_summary"])
            self.assertEqual(row["notification_status"], "skipped")


if __name__ == "__main__":
    unittest.main()
