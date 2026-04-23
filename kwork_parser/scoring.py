from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import requests

from .config import Settings
from .models import Project


def clamp_score(score: float) -> float:
    return max(0.0, min(100.0, round(score, 1)))


@dataclass(slots=True)
class ScoreResult:
    score: float
    summary: str
    reasons: list[str]


TOKEN_RE = re.compile(r"[a-zа-яё0-9]{4,}", flags=re.IGNORECASE)
STOP_WORDS = {
    "with",
    "from",
    "this",
    "that",
    "для",
    "или",
    "как",
    "что",
    "это",
    "надо",
    "нужно",
    "сделать",
    "заказ",
    "проект",
    "работа",
    "есть",
    "будет",
    "можно",
    "требуется",
}


def apply_hide_similar_penalty(
    project: Project,
    rule_result: ScoreResult,
    hidden_projects: list[Project],
    penalty: float = 25.0,
) -> ScoreResult:
    hidden_project_id = find_similar_hidden_project(project, hidden_projects)
    if hidden_project_id is None:
        return rule_result

    reason = f"похож на скрытый ранее заказ #{hidden_project_id}"
    reasons = [reason, *rule_result.reasons]
    score = clamp_score(rule_result.score - penalty)
    summary = "; ".join(reasons[:3])
    return ScoreResult(score=score, summary=summary, reasons=reasons)


def find_similar_hidden_project(project: Project, hidden_projects: list[Project]) -> int | None:
    project_tokens = _tokens(project.searchable_text)
    project_title_tokens = _tokens(project.title)
    if not project_tokens:
        return None

    for hidden_project in hidden_projects:
        if hidden_project.id == project.id:
            continue

        hidden_tokens = _tokens(hidden_project.searchable_text)
        hidden_title_tokens = _tokens(hidden_project.title)
        if not hidden_tokens:
            continue

        common_tokens = project_tokens & hidden_tokens
        common_title_tokens = project_title_tokens & hidden_title_tokens
        category_matches = (
            project.category_id is not None
            and hidden_project.category_id is not None
            and project.category_id == hidden_project.category_id
        )
        title_similarity = _jaccard(project_title_tokens, hidden_title_tokens)

        if category_matches and (len(common_title_tokens) >= 2 or len(common_tokens) >= 4):
            return hidden_project.id
        if title_similarity >= 0.5 and len(common_title_tokens) >= 2:
            return hidden_project.id

    return None


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(text)
        if token.lower() not in STOP_WORDS
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


class RuleScorer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def score(self, project: Project) -> ScoreResult:
        score = 50.0
        reasons: list[str] = []
        text = project.searchable_text

        include_hits = [kw for kw in self.settings.include_keywords if kw in text]
        exclude_hits = [kw for kw in self.settings.exclude_keywords if kw in text]

        if self.settings.category_ids:
            if project.category_id in self.settings.category_ids:
                score += 18
                reasons.append(f"рубрика {project.category_id} входит в whitelist")
            else:
                score -= 30
                reasons.append(f"рубрика {project.category_id} вне whitelist")

        if include_hits:
            score += min(25, 8 + 5 * len(include_hits))
            reasons.append("совпали ключевые слова: " + ", ".join(include_hits[:4]))
        missing_required_include = bool(self.settings.include_keywords and not include_hits)
        if missing_required_include:
            score -= 18
            reasons.append("нет совпадений по include keywords")

        if exclude_hits:
            score -= min(45, 15 + 8 * len(exclude_hits))
            reasons.append("сработали стоп-слова: " + ", ".join(exclude_hits[:4]))

        budget = project.budget_rub or project.possible_budget_rub
        if self.settings.min_price is not None:
            if budget is None:
                score -= 10
                reasons.append("бюджет не указан")
            elif budget < self.settings.min_price:
                score -= 25
                reasons.append(f"бюджет {budget} ниже минимума {self.settings.min_price}")
            else:
                score += 12
                reasons.append(f"бюджет {budget} проходит по минимуму")
        elif budget is not None:
            if budget >= 30000:
                score += 15
                reasons.append("высокий бюджет")
            elif budget >= 10000:
                score += 10
                reasons.append("хороший бюджет")
            elif budget >= 3000:
                score += 5
                reasons.append("нормальный бюджет")

        if self.settings.max_price is not None and budget is not None and budget > self.settings.max_price:
            score -= 5
            reasons.append(f"бюджет {budget} выше комфортного потолка {self.settings.max_price}")

        if self.settings.min_hiring_percent is not None:
            hiring = project.user_hired_percent
            if hiring is None:
                score -= 5
                reasons.append("нет данных по hiring percent")
            elif hiring >= self.settings.min_hiring_percent:
                score += 12
                reasons.append(f"hiring percent {hiring}% проходит порог")
            else:
                score -= 12
                reasons.append(f"hiring percent {hiring}% ниже порога")
        elif project.user_hired_percent is not None:
            if project.user_hired_percent >= 40:
                score += 10
                reasons.append(f"хороший hiring percent: {project.user_hired_percent}%")
            elif project.user_hired_percent == 0:
                score -= 8
                reasons.append("у заказчика пока нет наймов")

        if project.kwork_count is not None:
            if project.kwork_count <= 3:
                score += 8
                reasons.append("низкая конкуренция по откликам")
            elif project.kwork_count >= 15:
                score -= 10
                reasons.append("высокая конкуренция по откликам")

        if project.max_days is not None and project.max_days <= 3:
            score += 4
            reasons.append("короткий дедлайн")

        if project.has_portfolio_available:
            score += 3
            reasons.append("можно приложить портфолио")

        if missing_required_include:
            score = min(score, self.settings.min_rule_score - 1)
            reasons.append("без include keywords не проходит rule-порог")

        score = clamp_score(score)
        summary = "; ".join(reasons[:3]) if reasons else "Явных сигналов не найдено."
        return ScoreResult(score=score, summary=summary, reasons=reasons)


class OpenRouterScorer:
    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()

    def score(self, project: Project, rule_result: ScoreResult) -> ScoreResult:
        data = self._request_score(project, rule_result)
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        parsed = self._extract_json(content)
        return self._score_from_parsed(parsed)

    def _request_score(self, project: Project, rule_result: ScoreResult) -> dict:
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.openrouter_site_url:
            headers["HTTP-Referer"] = self.settings.openrouter_site_url
        if self.settings.openrouter_site_name:
            headers["X-Title"] = self.settings.openrouter_site_name

        prompt_payload = {
            "profile": self.settings.ai_profile_brief,
            "extra_instructions": self.settings.ai_extra_instructions,
            "rule_score": rule_result.score,
            "rule_summary": rule_result.summary,
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

        request_body = {
            "model": self.settings.openrouter_model,
            "temperature": 0.2,
            "max_tokens": 300,
            "messages": [
                {
                    "role": "system",
                    "content": load_system_prompt(),
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
                    self.API_URL,
                    headers=headers,
                    json=request_body,
                    timeout=self.settings.request_timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("OpenRouter response JSON must be an object")
                return data
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt >= self.settings.request_retries:
                    raise
                time.sleep(self.settings.retry_backoff_seconds)

        raise RuntimeError(f"OpenRouter request failed: {last_error}")

    def _extract_json(self, text: str) -> dict:
        clean_text = self._strip_code_fence(text.strip())
        decoder = json.JSONDecoder()

        for match in re.finditer(r"\{", clean_text):
            try:
                parsed, _ = decoder.raw_decode(clean_text[match.start() :])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        raise ValueError(f"Could not parse OpenRouter JSON response: {text!r}")

    def _strip_code_fence(self, text: str) -> str:
        if not text.startswith("```"):
            return text
        text = re.sub(r"^```(?:json)?", "", text).strip()
        return re.sub(r"```$", "", text).strip()

    def _score_from_parsed(self, parsed: dict) -> ScoreResult:
        score = clamp_score(self._parse_score(parsed.get("score")))
        is_relevant = self._parse_relevance(parsed.get("is_relevant"))
        if is_relevant is False:
            score = min(score, 39.0)
        return ScoreResult(
            score=score,
            summary=self._build_summary(parsed),
            reasons=self._parse_reasons(parsed.get("reasons")),
        )

    def _parse_score(self, value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"OpenRouter score is missing or invalid: {value!r}") from None

    def _parse_relevance(self, value: object) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        return bool(value)

    def _parse_reasons(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _build_summary(self, parsed: dict) -> str:
        summary = str(parsed.get("summary", "AI summary is empty")).strip()
        category = str(parsed.get("category", "")).strip()
        is_relevant = self._parse_relevance(parsed.get("is_relevant"))

        parts = []
        if is_relevant is not None:
            parts.append("relevant" if bool(is_relevant) else "non-relevant")
        if category:
            parts.append(category)
        if summary:
            parts.append(summary)
        return " | ".join(parts) if parts else "AI summary is empty"


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    prompt_path = Path(__file__).with_name("prompts") / "development_filter_system_prompt.txt"
    return prompt_path.read_text(encoding="utf-8").strip()
