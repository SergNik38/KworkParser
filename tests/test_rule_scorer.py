from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from kwork_parser.app import Application
from kwork_parser.config import Settings
from kwork_parser.models import Project
from kwork_parser.scoring import RuleScorer, ScoreResult


def make_settings(*, include_keywords: list[str], min_rule_score: float = 40.0) -> Settings:
    return Settings(
        poll_interval_seconds=45,
        request_timeout_seconds=20,
        request_retries=1,
        retry_backoff_seconds=1,
        max_pages=1,
        database_path=Path(":memory:"),
        skip_existing_on_first_run=False,
        min_rule_score=min_rule_score,
        min_ai_score=65.0,
        min_price=15000,
        max_price=150000,
        min_hiring_percent=None,
        category_ids=[],
        include_keywords=include_keywords,
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


def make_project(*, title: str, description: str, price: int = 50000) -> Project:
    return Project.from_api(
        {
            "id": "1001",
            "name": title,
            "description": description,
            "priceLimit": str(price),
            "user": {},
        }
    )


class RuleScorerTests(unittest.TestCase):
    def test_missing_include_keyword_stays_below_rule_threshold_even_with_good_budget(self) -> None:
        scorer = RuleScorer(make_settings(include_keywords=["python"]))
        project = make_project(
            title="Нужно оформить карточки товара",
            description="Большой бюджет, но без разработки и без нужных ключевых слов",
        )

        result = scorer.score(project)

        self.assertLess(result.score, 40.0)
        self.assertIn("нет совпадений по include keywords", result.reasons)
        self.assertIn("без include keywords не проходит rule-порог", result.reasons)

    def test_include_keyword_can_pass_rule_threshold(self) -> None:
        scorer = RuleScorer(make_settings(include_keywords=["python"]))
        project = make_project(
            title="Python парсер для сайта",
            description="Нужна автоматизация сбора данных",
        )

        result = scorer.score(project)

        self.assertGreaterEqual(result.score, 40.0)

    def test_empty_include_keywords_keep_broad_scoring_available(self) -> None:
        scorer = RuleScorer(make_settings(include_keywords=[]))
        project = make_project(
            title="Интеграция сервиса",
            description="Нужна задача с хорошим бюджетом",
        )

        result = scorer.score(project)

        self.assertGreaterEqual(result.score, 40.0)

    def test_application_rescores_existing_pending_candidate_before_sending(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(
                include_keywords=["python"],
                min_rule_score=40.0,
            )
            settings.database_path = Path(tmpdir) / "kwork_parser.db"
            app = Application(settings)
            project = make_project(
                title="Оформить карточки товара",
                description="Большой бюджет без нужных ключевых слов",
            )
            app.storage.save_project(project, ScoreResult(44.0, "old broad score", []))
            app.client = EmptyClient()
            app.notifier = FailingNotifier()

            processed = app.run_once()

            row = app.storage.connection.execute(
                "SELECT notification_status, rule_score FROM projects WHERE id = 1001"
            ).fetchone()
            self.assertEqual(processed, 0)
            self.assertEqual(row["notification_status"], "skipped")
            self.assertLess(row["rule_score"], 40.0)


class EmptyClient:
    def fetch_projects(self, page: int = 1) -> list[Project]:
        return []


class FailingNotifier:
    def send(self, project: Project, rule_result: ScoreResult, ai_result: ScoreResult | None) -> None:
        raise AssertionError("Notifier should not be called")


if __name__ == "__main__":
    unittest.main()
