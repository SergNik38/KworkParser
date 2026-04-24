from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

import requests

from .config import Settings
from .models import Project
from .scoring import ScoreResult


class ResponseDraftService:
    DEFAULT_API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()

    def generate(
        self,
        project: Project,
        rule_result: ScoreResult,
        ai_result: ScoreResult | None,
        variant: str = "default",
    ) -> str:
        data = self._post_chat_completion(project, rule_result, ai_result, variant)
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        if not content:
            raise ValueError("Response draft is empty")
        return self._clean_draft_text(content)

    def _post_chat_completion(
        self,
        project: Project,
        rule_result: ScoreResult,
        ai_result: ScoreResult | None,
        variant: str,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.openrouter_site_url:
            headers["HTTP-Referer"] = self.settings.openrouter_site_url
        if self.settings.openrouter_site_name:
            headers["X-Title"] = self.settings.openrouter_site_name

        prompt_payload = {
            "profile": self.settings.ai_profile_brief,
            "extra_instructions": self.settings.ai_extra_instructions,
            "variant": variant,
            "rule_score": rule_result.score,
            "rule_summary": rule_result.summary,
            "rule_reasons": rule_result.reasons,
            "ai_score": ai_result.score if ai_result else None,
            "ai_summary": ai_result.summary if ai_result else None,
            "ai_reasons": ai_result.reasons if ai_result else [],
            "project": {
                "id": project.id,
                "title": project.title,
                "description": project.description,
                "url": project.url,
                "category_id": project.category_id,
                "budget_rub": project.budget_rub,
                "possible_budget_rub": project.possible_budget_rub,
                "max_days": project.max_days,
                "username": project.username,
                "user_hired_percent": project.user_hired_percent,
                "kwork_count": project.kwork_count,
                "views": project.views,
            },
        }
        if variant == "short":
            prompt_payload["extra_instructions"] += "\nСделай отклик заметно короче: 3-5 предложений."
        elif variant == "questions":
            prompt_payload["extra_instructions"] += "\nДобавь отдельный короткий блок уточняющих вопросов."

        request_body = {
            "model": self._model,
            "temperature": 0.35,
            "max_tokens": 450,
            "messages": [
                {
                    "role": "system",
                    "content": load_response_draft_prompt(),
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt_payload, ensure_ascii=False),
                },
            ],
        }

        last_error: Exception | None = None
        for attempt in range(1, self.settings.request_retries + 1):
            try:
                response = self.session.post(
                    self._api_url,
                    headers=headers,
                    json=request_body,
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Response draft JSON must be an object")
                return data
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt >= self.settings.request_retries:
                    raise
                time.sleep(self.settings.retry_backoff_seconds)

        raise RuntimeError(f"Response draft request failed: {last_error}")

    @property
    def _api_key(self) -> str:
        return self.settings.response_draft_api_key or self.settings.openrouter_api_key or ""

    @property
    def _model(self) -> str:
        return self.settings.response_draft_model or self.settings.openrouter_model or ""

    @property
    def _api_url(self) -> str:
        return self.settings.response_draft_base_url or self.DEFAULT_API_URL

    @property
    def _timeout_seconds(self) -> int:
        return self.settings.response_draft_timeout_seconds or self.settings.request_timeout_seconds

    def _clean_draft_text(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = self._strip_code_fence(text)
        return text.strip()

    def _strip_code_fence(self, text: str) -> str:
        text = re.sub(r"^```(?:json)?", "", text).strip()
        return re.sub(r"```$", "", text).strip()


@lru_cache(maxsize=1)
def load_response_draft_prompt() -> str:
    prompt_path = Path(__file__).with_name("prompts") / "response_draft_system_prompt.txt"
    return prompt_path.read_text(encoding="utf-8").strip()
