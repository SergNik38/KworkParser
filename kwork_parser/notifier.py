from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field

import requests

from .config import Settings
from .models import Project
from .scoring import ScoreResult


logger = logging.getLogger(__name__)


FEEDBACK_ACTION_LABELS = {
    "interesting": "Интересно",
    "miss": "Мимо",
    "hide_similar": "Скрыть похожие",
}
DRAFT_ACTION_LABELS = {
    "regenerate": "Переделать отклик",
    "short": "Короче",
    "questions": "Добавить вопросы",
    "sent": "Отправил вручную",
}


@dataclass(slots=True)
class TelegramFeedbackUpdate:
    project_id: int
    feedback: str
    update_id: int
    callback_query_id: str
    telegram_user_id: int | None
    telegram_username: str
    payload: dict


@dataclass(slots=True)
class TelegramHealthCommand:
    chat_id: int
    update_id: int
    message_id: int | None
    telegram_user_id: int | None
    telegram_username: str
    payload: dict


@dataclass(slots=True)
class TelegramDraftAction:
    project_id: int
    action: str
    update_id: int
    callback_query_id: str
    telegram_user_id: int | None
    telegram_username: str
    payload: dict


@dataclass(slots=True)
class TelegramFeedbackPoll:
    actions: list[TelegramFeedbackUpdate]
    next_offset: int | None
    health_commands: list[TelegramHealthCommand] = field(default_factory=list)
    draft_actions: list[TelegramDraftAction] = field(default_factory=list)


class TelegramNotifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()

    def send(self, project: Project, rule_result: ScoreResult, ai_result: ScoreResult | None) -> None:
        message = self._format_message(project, rule_result, ai_result)
        if self.settings.dry_run:
            logger.info("Dry-run notification preview:\n%s\n%s\n%s", "=" * 80, message, "=" * 80)
            return

        if not self.settings.telegram_enabled:
            raise RuntimeError("Telegram is disabled: configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

        response = self.session.post(
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": self.settings.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": self._build_reply_markup(project),
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error: {payload!r}")

    def fetch_feedback(self, offset: int | None) -> TelegramFeedbackPoll:
        if not self.settings.telegram_enabled:
            return TelegramFeedbackPoll(actions=[], next_offset=offset)

        params: dict[str, object] = {
            "timeout": 0,
            "allowed_updates": json.dumps(["callback_query", "message"]),
        }
        if offset is not None:
            params["offset"] = offset

        response = self.session.get(
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/getUpdates",
            params=params,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram getUpdates API error: {payload!r}")

        updates = payload.get("result") or []
        if not isinstance(updates, list):
            return TelegramFeedbackPoll(actions=[], next_offset=offset)

        next_offset = offset
        actions: list[TelegramFeedbackUpdate] = []
        draft_actions: list[TelegramDraftAction] = []
        health_commands: list[TelegramHealthCommand] = []
        for update in updates:
            if not isinstance(update, dict):
                continue
            update_id = self._parse_int(update.get("update_id"))
            if update_id is not None:
                next_offset = max(next_offset or 0, update_id + 1)

            action = self._parse_feedback_update(update, update_id)
            if action:
                actions.append(action)
                continue

            draft_action = self._parse_draft_action(update, update_id)
            if draft_action:
                draft_actions.append(draft_action)
                continue

            health_command = self._parse_health_command(update, update_id)
            if health_command:
                health_commands.append(health_command)

        return TelegramFeedbackPoll(
            actions=actions,
            next_offset=next_offset,
            health_commands=health_commands,
            draft_actions=draft_actions,
        )

    def answer_feedback(self, callback_query_id: str, feedback: str) -> None:
        if not self.settings.telegram_enabled or not callback_query_id:
            return

        label = FEEDBACK_ACTION_LABELS.get(feedback, feedback)
        response = self.session.post(
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/answerCallbackQuery",
            json={
                "callback_query_id": callback_query_id,
                "text": label if feedback not in FEEDBACK_ACTION_LABELS else f"Сохранено: {label}",
                "show_alert": False,
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram answerCallbackQuery API error: {payload!r}")

    def send_health(self, command: TelegramHealthCommand, text: str) -> None:
        if not self.settings.telegram_enabled:
            return

        message: dict[str, object] = {
            "chat_id": command.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if command.message_id is not None:
            message["reply_to_message_id"] = command.message_id

        response = self.session.post(
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
            json=message,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram health response API error: {payload!r}")

    def send_response_draft(self, project: Project, draft_text: str) -> None:
        if self.settings.dry_run:
            logger.info("Dry-run response draft for project %s:\n%s", project.id, draft_text)
            return

        if not self.settings.telegram_enabled:
            raise RuntimeError("Telegram is disabled: configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

        response = self.session.post(
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": self.settings.telegram_chat_id,
                "text": self._format_response_draft(project, draft_text),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": self._build_draft_reply_markup(project),
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram response draft API error: {payload!r}")

    def _format_message(self, project: Project, rule_result: ScoreResult, ai_result: ScoreResult | None) -> str:
        budget = project.budget_rub or project.possible_budget_rub
        budget_line = f"{budget} ₽" if budget is not None else "не указан"
        description = self._truncate(project.description, 900)
        description_block = f"\n\n<b>Описание:</b>\n{html.escape(description)}" if description else ""
        customer_link = html.escape(project.user_profile_url or project.username or "unknown")
        rule_reasons = self._format_reasons(rule_result.reasons)
        rule_reasons_block = f"\n<b>Rule причины:</b> {rule_reasons}" if rule_reasons else ""

        if ai_result:
            ai_block = (
                f"\n<b>AI score:</b> {ai_result.score:.1f}"
                f"\n<b>AI вывод:</b> {html.escape(ai_result.summary)}"
                f"{self._format_ai_reasons(ai_result)}"
            )
        else:
            ai_block = ""

        return (
            f"<b>{html.escape(project.title)}</b>\n"
            f"<b>Бюджет:</b> {budget_line}\n"
            f"<b>Дедлайн:</b> {project.max_days if project.max_days is not None else 'n/a'} дн.\n"
            f"<b>Отклики:</b> {project.kwork_count if project.kwork_count is not None else 'n/a'}\n"
            f"<b>Просмотры:</b> {project.views if project.views is not None else 'n/a'}\n"
            f"<b>Заказчик:</b> {html.escape(project.username or 'unknown')}\n"
            f"<b>Профиль:</b> {customer_link}\n"
            f"<b>Hiring:</b> {project.user_hired_percent if project.user_hired_percent is not None else 'n/a'}\n"
            f"<b>Rule score:</b> {rule_result.score:.1f}\n"
            f"<b>Rule вывод:</b> {html.escape(rule_result.summary)}"
            f"{rule_reasons_block}"
            f"{ai_block}"
            f"{description_block}\n\n"
            f"<b>Ссылка:</b> {project.url}"
        )

    def _build_reply_markup(self, project: Project) -> dict:
        return {
            "inline_keyboard": [
                [
                    {
                        "text": FEEDBACK_ACTION_LABELS["interesting"],
                        "callback_data": f"fb:{project.id}:interesting",
                    },
                    {
                        "text": FEEDBACK_ACTION_LABELS["miss"],
                        "callback_data": f"fb:{project.id}:miss",
                    },
                ],
                [
                    {
                        "text": FEEDBACK_ACTION_LABELS["hide_similar"],
                        "callback_data": f"fb:{project.id}:hide_similar",
                    },
                    {
                        "text": "Открыть заказ",
                        "url": project.url,
                    },
                ],
            ]
        }

    def _format_response_draft(self, project: Project, draft_text: str) -> str:
        return (
            f"<b>Черновик отклика</b>\n"
            f"<b>Проект:</b> {html.escape(project.title)}\n"
            f"<b>Ссылка:</b> {project.url}\n\n"
            f"{html.escape(draft_text)}"
        )

    def _build_draft_reply_markup(self, project: Project) -> dict:
        return {
            "inline_keyboard": [
                [
                    {
                        "text": DRAFT_ACTION_LABELS["regenerate"],
                        "callback_data": f"draft:{project.id}:regenerate",
                    },
                    {
                        "text": DRAFT_ACTION_LABELS["short"],
                        "callback_data": f"draft:{project.id}:short",
                    },
                ],
                [
                    {
                        "text": DRAFT_ACTION_LABELS["questions"],
                        "callback_data": f"draft:{project.id}:questions",
                    },
                    {
                        "text": DRAFT_ACTION_LABELS["sent"],
                        "callback_data": f"draft:{project.id}:sent",
                    },
                ],
            ]
        }

    def _parse_feedback_update(
        self,
        update: dict,
        update_id: int | None,
    ) -> TelegramFeedbackUpdate | None:
        callback_query = update.get("callback_query")
        if not isinstance(callback_query, dict) or update_id is None:
            return None

        data = callback_query.get("data")
        if not isinstance(data, str):
            return None

        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "fb":
            return None

        project_id = self._parse_int(parts[1])
        feedback = parts[2]
        if project_id is None or feedback not in FEEDBACK_ACTION_LABELS:
            return None

        user = callback_query.get("from") or {}
        if not isinstance(user, dict):
            user = {}

        return TelegramFeedbackUpdate(
            project_id=project_id,
            feedback=feedback,
            update_id=update_id,
            callback_query_id=str(callback_query.get("id") or ""),
            telegram_user_id=self._parse_int(user.get("id")),
            telegram_username=str(user.get("username") or "").strip(),
            payload=update,
        )

    def _parse_draft_action(
        self,
        update: dict,
        update_id: int | None,
    ) -> TelegramDraftAction | None:
        callback_query = update.get("callback_query")
        if not isinstance(callback_query, dict) or update_id is None:
            return None

        data = callback_query.get("data")
        if not isinstance(data, str):
            return None

        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "draft":
            return None

        project_id = self._parse_int(parts[1])
        action = parts[2]
        if project_id is None or action not in DRAFT_ACTION_LABELS:
            return None

        user = callback_query.get("from") or {}
        if not isinstance(user, dict):
            user = {}

        return TelegramDraftAction(
            project_id=project_id,
            action=action,
            update_id=update_id,
            callback_query_id=str(callback_query.get("id") or ""),
            telegram_user_id=self._parse_int(user.get("id")),
            telegram_username=str(user.get("username") or "").strip(),
            payload=update,
        )

    def _parse_health_command(
        self,
        update: dict,
        update_id: int | None,
    ) -> TelegramHealthCommand | None:
        message = update.get("message")
        if not isinstance(message, dict) or update_id is None:
            return None

        text = message.get("text")
        if not isinstance(text, str) or not self._is_health_command(text):
            return None

        chat = message.get("chat") or {}
        if not isinstance(chat, dict):
            return None

        chat_id = self._parse_int(chat.get("id"))
        if chat_id is None or not self._chat_matches(chat_id):
            return None

        user = message.get("from") or {}
        if not isinstance(user, dict):
            user = {}

        return TelegramHealthCommand(
            chat_id=chat_id,
            update_id=update_id,
            message_id=self._parse_int(message.get("message_id")),
            telegram_user_id=self._parse_int(user.get("id")),
            telegram_username=str(user.get("username") or "").strip(),
            payload=update,
        )

    def _is_health_command(self, text: str) -> bool:
        command = text.strip().split(maxsplit=1)[0].lower()
        return command == "/health" or command.startswith("/health@")

    def _chat_matches(self, chat_id: int) -> bool:
        return str(chat_id) == str(self.settings.telegram_chat_id)

    def _format_ai_reasons(self, ai_result: ScoreResult) -> str:
        reasons = self._format_reasons(ai_result.reasons)
        return f"\n<b>AI причины:</b> {reasons}" if reasons else ""

    def _format_reasons(self, reasons: list[str]) -> str:
        if not reasons:
            return ""
        return html.escape("; ".join(reasons[:4]))

    def _truncate(self, text: str, limit: int) -> str:
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def _parse_int(self, value: object) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
