from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path

from kwork_parser.app import Application
from kwork_parser.config import Settings
from kwork_parser.models import Project
from kwork_parser.notifier import (
    TelegramDraftAction,
    TelegramFeedbackPoll,
    TelegramFeedbackUpdate,
    TelegramHealthCommand,
    TelegramNotifier,
)
from kwork_parser.scoring import ScoreResult
from kwork_parser.storage import ProjectFeedback, ResponseDraft, Storage


def make_settings(database_path: Path | None = None, telegram_chat_id: str = "chat") -> Settings:
    return Settings(
        poll_interval_seconds=45,
        request_timeout_seconds=20,
        request_retries=1,
        retry_backoff_seconds=1,
        max_pages=1,
        database_path=database_path or Path(":memory:"),
        skip_existing_on_first_run=False,
        min_rule_score=55.0,
        min_ai_score=70.0,
        min_price=None,
        max_price=None,
        min_hiring_percent=None,
        category_ids=[],
        include_keywords=[],
        exclude_keywords=[],
        dry_run=False,
        telegram_bot_token="token",
        telegram_chat_id=telegram_chat_id,
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


def make_project() -> Project:
    return Project.from_api(
        {
            "id": "1001",
            "name": "Python Telegram bot",
            "description": "Need Python automation for Telegram API",
            "priceLimit": "10000",
            "max_days": "5",
            "user": {
                "username": "customer",
                "data": {
                    "wants_hired_percent": "50",
                },
            },
            "wantUserGetProfileUrl": "https://kwork.ru/user/customer",
            "kwork_count": "2",
            "views_dirty": "10",
        }
    )


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict:
        return self.payload


class FakeTelegramSession:
    def __init__(self, updates: list[dict]) -> None:
        self.updates = updates
        self.get_calls: list[dict] = []
        self.post_calls: list[dict] = []

    def get(self, url: str, params: dict, timeout: int) -> FakeResponse:
        self.get_calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse({"ok": True, "result": self.updates})

    def post(self, url: str, json: dict, timeout: int) -> FakeResponse:
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({"ok": True})


class FakeFeedbackNotifier:
    def __init__(self) -> None:
        self.answered: list[tuple[str, str]] = []

    def fetch_feedback(self, offset: int | None) -> TelegramFeedbackPoll:
        self.offset = offset
        return TelegramFeedbackPoll(
            actions=[
                TelegramFeedbackUpdate(
                    project_id=1001,
                    feedback="interesting",
                    update_id=42,
                    callback_query_id="callback-1",
                    telegram_user_id=123,
                    telegram_username="user",
                    payload={"update_id": 42},
                )
            ],
            next_offset=43,
        )

    def answer_feedback(self, callback_query_id: str, feedback: str) -> None:
        self.answered.append((callback_query_id, feedback))


class FakeHealthNotifier:
    def __init__(self) -> None:
        self.health_messages: list[tuple[TelegramHealthCommand, str]] = []

    def fetch_feedback(self, offset: int | None) -> TelegramFeedbackPoll:
        self.offset = offset
        return TelegramFeedbackPoll(
            actions=[],
            next_offset=100,
            health_commands=[
                TelegramHealthCommand(
                    chat_id=-100123,
                    update_id=99,
                    message_id=7,
                    telegram_user_id=123,
                    telegram_username="user",
                    payload={"update_id": 99},
                )
            ],
        )

    def send_health(self, command: TelegramHealthCommand, text: str) -> None:
        self.health_messages.append((command, text))


class FakeDraftGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def generate(self, project: Project, rule_result: ScoreResult, ai_result: ScoreResult | None, variant: str) -> str:
        self.calls.append((project.id, variant))
        return f"Черновик {variant}"


class FakeDraftNotifier:
    def __init__(self) -> None:
        self.drafts: list[tuple[int, str]] = []
        self.answers: list[tuple[str, str]] = []

    def send_response_draft(self, project: Project, draft_text: str) -> None:
        self.drafts.append((project.id, draft_text))

    def answer_feedback(self, callback_query_id: str, feedback: str) -> None:
        self.answers.append((callback_query_id, feedback))


class TelegramFeedbackTests(unittest.TestCase):
    def test_message_contains_description_reasons_and_buttons(self) -> None:
        notifier = TelegramNotifier(make_settings())
        project = make_project()

        message = notifier._format_message(
            project,
            ScoreResult(78, "rule ok", ["keyword", "budget"]),
            ScoreResult(85, "ai ok", ["technical task"]),
        )
        markup = notifier._build_reply_markup(project)

        self.assertIn("<b>Описание:</b>", message)
        self.assertIn("Need Python automation", message)
        self.assertIn("Rule причины", message)
        self.assertIn("AI причины", message)
        callback_data = [
            button.get("callback_data")
            for row in markup["inline_keyboard"]
            for button in row
            if "callback_data" in button
        ]
        self.assertEqual(
            callback_data,
            [
                "fb:1001:interesting",
                "fb:1001:miss",
                "draft:1001:generate",
                "fb:1001:hide_similar",
            ],
        )

    def test_draft_message_contains_text_and_buttons(self) -> None:
        notifier = TelegramNotifier(make_settings())
        project = make_project()

        message = notifier._format_response_draft(project, "Готов помочь с задачей.")
        markup = notifier._build_draft_reply_markup(project)

        self.assertIn("Черновик отклика", message)
        self.assertIn("Готов помочь", message)
        callback_data = [
            button.get("callback_data")
            for row in markup["inline_keyboard"]
            for button in row
            if "callback_data" in button
        ]
        self.assertEqual(
            callback_data,
            [
                "draft:1001:regenerate",
                "draft:1001:short",
                "draft:1001:questions",
                "draft:1001:sent",
            ],
        )

    def test_fetch_feedback_parses_callbacks_and_advances_offset(self) -> None:
        notifier = TelegramNotifier(make_settings())
        notifier.session = FakeTelegramSession(
            [
                {
                    "update_id": 10,
                    "callback_query": {
                        "id": "callback-1",
                        "from": {"id": 123, "username": "user"},
                        "data": "fb:1001:miss",
                    },
                },
                {
                    "update_id": 11,
                    "callback_query": {
                        "id": "callback-2",
                        "from": {"id": 123},
                        "data": "ignored",
                    },
                },
            ]
        )

        poll = notifier.fetch_feedback(offset=None)

        self.assertEqual(poll.next_offset, 12)
        self.assertEqual(len(poll.actions), 1)
        self.assertEqual(poll.actions[0].project_id, 1001)
        self.assertEqual(poll.actions[0].feedback, "miss")
        self.assertEqual(poll.actions[0].telegram_user_id, 123)
        self.assertEqual(poll.actions[0].telegram_username, "user")

    def test_fetch_feedback_parses_health_command_for_configured_chat(self) -> None:
        notifier = TelegramNotifier(make_settings(telegram_chat_id="-100123"))
        notifier.session = FakeTelegramSession(
            [
                {
                    "update_id": 20,
                    "message": {
                        "message_id": 5,
                        "chat": {"id": -100123},
                        "from": {"id": 123, "username": "user"},
                        "text": "/health@KworkParserBot",
                    },
                },
                {
                    "update_id": 21,
                    "message": {
                        "message_id": 6,
                        "chat": {"id": -999},
                        "from": {"id": 456},
                        "text": "/health",
                    },
                },
            ]
        )

        poll = notifier.fetch_feedback(offset=10)

        self.assertEqual(poll.next_offset, 22)
        self.assertEqual(len(poll.health_commands), 1)
        self.assertEqual(poll.health_commands[0].chat_id, -100123)
        self.assertEqual(poll.health_commands[0].message_id, 5)
        self.assertEqual(poll.health_commands[0].telegram_user_id, 123)

    def test_fetch_feedback_parses_draft_action(self) -> None:
        notifier = TelegramNotifier(make_settings())
        notifier.session = FakeTelegramSession(
            [
                {
                    "update_id": 30,
                    "callback_query": {
                        "id": "draft-callback",
                        "from": {"id": 123, "username": "user"},
                        "data": "draft:1001:generate",
                    },
                }
            ]
        )

        poll = notifier.fetch_feedback(offset=None)

        self.assertEqual(poll.next_offset, 31)
        self.assertEqual(len(poll.draft_actions), 1)
        self.assertEqual(poll.draft_actions[0].project_id, 1001)
        self.assertEqual(poll.draft_actions[0].action, "generate")

    def test_application_sync_saves_feedback_and_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = Application(make_settings(Path(tmpdir) / "kwork_parser.db"))
            fake_notifier = FakeFeedbackNotifier()
            app.notifier = fake_notifier

            saved = app._sync_telegram_feedback()

            feedback = app.storage.get_feedback(1001, 123)
            self.assertEqual(saved, 1)
            self.assertIsNotNone(feedback)
            self.assertEqual(feedback.feedback, "interesting")
            self.assertEqual(feedback.telegram_user_id, 123)
            self.assertEqual(app.storage.get_telegram_update_offset(), 43)
            self.assertEqual(fake_notifier.answered, [("callback-1", "interesting")])

    def test_application_sync_answers_health_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = Application(make_settings(Path(tmpdir) / "kwork_parser.db", telegram_chat_id="-100123"))
            fake_notifier = FakeHealthNotifier()
            app.notifier = fake_notifier

            saved = app._sync_telegram_feedback()

            self.assertEqual(saved, 0)
            self.assertEqual(app.storage.get_telegram_update_offset(), 100)
            self.assertEqual(len(fake_notifier.health_messages), 1)
            self.assertIn("Kwork Parser health", fake_notifier.health_messages[0][1])
            self.assertIn("Проекты", fake_notifier.health_messages[0][1])

    def test_application_generates_and_saves_response_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = Application(make_settings(Path(tmpdir) / "kwork_parser.db"))
            app.response_draft_generator = FakeDraftGenerator()
            app.notifier = FakeDraftNotifier()
            project = make_project()
            rule_result = ScoreResult(70, "rule", [])

            generated = app._send_response_draft(project, rule_result, None, variant="short")
            draft = app.storage.get_response_draft(project.id)

            self.assertTrue(generated)
            self.assertEqual(draft.text, "Черновик short")
            self.assertEqual(draft.variant, "short")
            self.assertEqual(app.notifier.drafts, [(1001, "Черновик short")])

    def test_application_marks_response_draft_sent_manually(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = Application(make_settings(Path(tmpdir) / "kwork_parser.db"))
            app.notifier = FakeDraftNotifier()
            project = make_project()
            app.storage.save_response_draft(
                ResponseDraft(
                    project_id=project.id,
                    text="Черновик",
                    variant="default",
                )
            )

            app._handle_draft_action(
                TelegramDraftAction(
                    project_id=project.id,
                    action="sent",
                    update_id=1,
                    callback_query_id="draft-callback",
                    telegram_user_id=123,
                    telegram_username="user",
                    payload={},
                )
            )

            status = app.storage.connection.execute(
                "SELECT status FROM response_drafts WHERE project_id = ?",
                (project.id,),
            ).fetchone()["status"]
            self.assertEqual(status, "sent_manually")
            self.assertEqual(app.notifier.answers, [("draft-callback", "Отклик отмечен как отправленный")])

    def test_storage_keeps_feedback_per_telegram_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = Storage(Path(tmpdir) / "kwork_parser.db")

            storage.save_feedback(
                ProjectFeedback(
                    project_id=1001,
                    feedback="interesting",
                    telegram_user_id=123,
                    telegram_username="first",
                    payload={"source": "first"},
                )
            )
            storage.save_feedback(
                ProjectFeedback(
                    project_id=1001,
                    feedback="miss",
                    telegram_user_id=456,
                    telegram_username="second",
                    payload={"source": "second"},
                )
            )
            storage.save_feedback(
                ProjectFeedback(
                    project_id=1001,
                    feedback="hide_similar",
                    telegram_user_id=123,
                    telegram_username="first",
                    payload={"source": "updated"},
                )
            )

            first_feedback = storage.get_feedback(1001, 123)
            second_feedback = storage.get_feedback(1001, 456)
            all_feedback = storage.list_feedback(1001)

            self.assertEqual(first_feedback.feedback, "hide_similar")
            self.assertEqual(first_feedback.payload, {"source": "updated"})
            self.assertEqual(second_feedback.feedback, "miss")
            self.assertEqual(len(all_feedback), 2)

    def test_storage_migrates_old_single_project_feedback_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kwork_parser.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE project_feedback (
                    project_id INTEGER PRIMARY KEY,
                    feedback TEXT NOT NULL,
                    telegram_user_id INTEGER,
                    telegram_username TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO project_feedback (
                    project_id, feedback, telegram_user_id, telegram_username, payload_json
                ) VALUES (1001, 'interesting', 123, 'user', '{}')
                """
            )
            connection.commit()
            connection.close()

            storage = Storage(db_path)
            storage.save_feedback(
                ProjectFeedback(
                    project_id=1001,
                    feedback="miss",
                    telegram_user_id=456,
                    telegram_username="second",
                    payload={"source": "second"},
                )
            )

            self.assertEqual(storage.get_feedback(1001, 123).feedback, "interesting")
            self.assertEqual(storage.get_feedback(1001, 456).feedback, "miss")
            self.assertEqual(len(storage.list_feedback(1001)), 2)


if __name__ == "__main__":
    unittest.main()
