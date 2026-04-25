from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import requests

from kwork_parser.config import Settings
from kwork_parser.models import Project
from kwork_parser.response_drafts import GeneratedDemoProject, ResponseDraftResult, ResponseDraftService
from kwork_parser.scoring import OpenRouterScorer, ScoreResult


def make_settings() -> Settings:
    return Settings(
        poll_interval_seconds=45,
        request_timeout_seconds=20,
        request_retries=2,
        retry_backoff_seconds=1,
        max_pages=1,
        database_path=Path(":memory:"),
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
        openrouter_api_key="test-key",
        openrouter_model="test-model",
        openrouter_site_url=None,
        openrouter_site_name=None,
        response_draft_api_key=None,
        response_draft_model=None,
        response_draft_base_url=None,
        response_draft_timeout_seconds=None,
        ai_profile_brief="profile",
        ai_extra_instructions="extra",
    )


def make_project() -> Project:
    return Project.from_api(
        {
            "id": "1001",
            "name": "Python task",
            "description": "Build API integration",
            "user": {},
        }
    )


class FakeResponse:
    def __init__(self, payload: object, *, raises: Exception | None = None) -> None:
        self.payload = payload
        self.raises = raises

    def raise_for_status(self) -> None:
        if self.raises:
            raise self.raises

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls = 0

    def post(self, *args, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


class OpenRouterScorerTests(unittest.TestCase):
    def test_extract_json_handles_fenced_json_with_surrounding_text(self) -> None:
        scorer = OpenRouterScorer(make_settings())

        parsed = scorer._extract_json(
            """
            ```json
            {"is_relevant": true, "score": 87, "summary": "ok", "reasons": ["r"], "category": "backend"}
            ```
            """
        )
        result = scorer._score_from_parsed(parsed)

        self.assertEqual(result.score, 87.0)
        self.assertEqual(result.reasons, ["r"])
        self.assertIn("backend", result.summary)

    def test_extract_json_skips_invalid_brace_fragment(self) -> None:
        scorer = OpenRouterScorer(make_settings())

        parsed = scorer._extract_json(
            'ignore {not json} then {"is_relevant": "false", "score": "80", "summary": "no", "reasons": []}'
        )
        result = scorer._score_from_parsed(parsed)

        self.assertEqual(result.score, 39.0)
        self.assertIn("non-relevant", result.summary)

    def test_invalid_score_raises_clear_error(self) -> None:
        scorer = OpenRouterScorer(make_settings())

        with self.assertRaisesRegex(ValueError, "score"):
            scorer._score_from_parsed({"is_relevant": True, "score": "bad"})

    def test_request_retries_transient_errors(self) -> None:
        scorer = OpenRouterScorer(make_settings())
        scorer.session = FakeSession(
            [
                requests.Timeout("temporary timeout"),
                FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"is_relevant": true, "score": 75, "summary": "ok", '
                                        '"reasons": ["technical"], "category": "integration"}'
                                    )
                                }
                            }
                        ]
                    }
                ),
            ]
        )

        with patch("kwork_parser.scoring.time.sleep", return_value=None):
            result = scorer.score(make_project(), ScoreResult(70, "rule", []))

        self.assertEqual(result.score, 75.0)
        self.assertEqual(scorer.session.calls, 2)


class OpenRouterResponseDraftGeneratorTests(unittest.TestCase):
    def test_generate_returns_structured_draft_and_demo_flag(self) -> None:
        generator = ResponseDraftService(make_settings())
        generator.session = FakeSession(
            [
                FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"draft_text": "Здравствуйте! Готов помочь с API-интеграцией.", '
                                        '"demo_available": true, '
                                        '"demo_summary": "Можно показать мини-демо формы и API-обмена."}'
                                    )
                                }
                            }
                        ]
                    }
                )
            ]
        )

        result = generator.generate(
            make_project(),
            ScoreResult(70, "rule", ["api"]),
            ScoreResult(80, "ai", ["integration"]),
        )

        self.assertEqual(
            result,
            ResponseDraftResult(
                text="Здравствуйте! Готов помочь с API-интеграцией.",
                demo_available=True,
                demo_summary="Можно показать мини-демо формы и API-обмена.",
            ),
        )

    def test_generate_rejects_empty_draft(self) -> None:
        generator = ResponseDraftService(make_settings())
        generator.session = FakeSession(
            [
                FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"draft_text": "", "demo_available": false, "demo_summary": ""}'
                                }
                            }
                        ]
                    }
                )
            ]
        )

        with self.assertRaisesRegex(ValueError, "draft is empty"):
            generator.generate(make_project(), ScoreResult(70, "rule", []), None)

    def test_generate_demo_project_writes_files_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings()
            settings.database_path = Path(tmpdir) / "kwork_parser.db"
            generator = ResponseDraftService(settings)
            generator.session = FakeSession(
                [
                    FakeResponse(
                        {
                            "choices": [
                                {
                                    "message": {
                                        "content": (
                                            '{"project_name": "demo-bot", '
                                            '"summary": "Мини-демо Telegram-формы.", '
                                            '"stack": ["HTML", "JavaScript"], '
                                            '"run_steps": ["Открыть index.html"], '
                                            '"files": ['
                                            '{"path": "index.html", "content": "<h1>Demo</h1>"}, '
                                            '{"path": "app.js", "content": "console.log(1);"}'
                                            ']}'
                                        )
                                    }
                                }
                            ]
                        }
                    )
                ]
            )

            result = generator.generate_demo_project(
                make_project(),
                ScoreResult(70, "rule", ["api"]),
                ScoreResult(80, "ai", ["integration"]),
                demo_summary="Можно показать мини-демо формы и API-обмена.",
            )

            self.assertIsInstance(result, GeneratedDemoProject)
            self.assertTrue((result.output_dir / "index.html").exists())
            self.assertTrue((result.output_dir / "app.js").exists())
            self.assertTrue((result.output_dir / "README.md").exists())
            self.assertTrue(result.archive_path.exists())


if __name__ == "__main__":
    unittest.main()
