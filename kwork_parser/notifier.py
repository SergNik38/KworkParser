from __future__ import annotations

import html

import requests

from .config import Settings
from .models import Project
from .scoring import ScoreResult


class TelegramNotifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()

    def send(self, project: Project, rule_result: ScoreResult, ai_result: ScoreResult | None) -> None:
        message = self._format_message(project, rule_result, ai_result)
        if self.settings.dry_run:
            print("\n" + "=" * 80)
            print(message)
            print("=" * 80 + "\n")
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
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error: {payload!r}")

    def _format_message(self, project: Project, rule_result: ScoreResult, ai_result: ScoreResult | None) -> str:
        budget = project.budget_rub or project.possible_budget_rub
        budget_line = f"{budget} ₽" if budget is not None else "не указан"
        ai_block = ""
        if ai_result:
            ai_block = (
                f"\n<b>AI score:</b> {ai_result.score:.1f}"
                f"\n<b>AI вывод:</b> {html.escape(ai_result.summary)}"
            )

        return (
            f"<b>{html.escape(project.title)}</b>\n"
            f"<b>Бюджет:</b> {budget_line}\n"
            f"<b>Rule score:</b> {rule_result.score:.1f}\n"
            f"<b>Rule вывод:</b> {html.escape(rule_result.summary)}"
            f"{ai_block}\n"
            f"<b>Заказчик:</b> {html.escape(project.username or 'unknown')}\n"
            f"<b>Hiring:</b> {project.user_hired_percent if project.user_hired_percent is not None else 'n/a'}\n"
            f"<b>Отклики:</b> {project.kwork_count if project.kwork_count is not None else 'n/a'}\n"
            f"<b>Ссылка:</b> {project.url}"
        )
