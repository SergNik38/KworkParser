from __future__ import annotations

import json
import re
from dataclasses import dataclass

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
        elif self.settings.include_keywords:
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

        score = clamp_score(score)
        summary = "; ".join(reasons[:3]) if reasons else "Явных сигналов не найдено."
        return ScoreResult(score=score, summary=summary, reasons=reasons)


class OpenRouterScorer:
    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()

    def score(self, project: Project, rule_result: ScoreResult) -> ScoreResult:
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

        response = self.session.post(
            self.API_URL,
            headers=headers,
            json={
                "model": self.settings.openrouter_model,
                "temperature": 0.2,
                "max_tokens": 300,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Ты анализируешь новые заказы с фриланс-биржи и определяешь, "
                            "насколько они релевантны разработчику программного обеспечения. "
                            "Считай релевантными любые задачи, связанные с backend, frontend, "
                            "fullstack, mobile, Telegram-ботами, чат-ботами, API, интеграциями, "
                            "CRM, парсингом, автоматизацией, DevOps, базами данных, AI/LLM, "
                            "исправлением багов, рефакторингом, поддержкой и доработкой кода "
                            "на любых языках и стеках, включая Python, JavaScript, TypeScript, "
                            "Node.js, React, Vue, PHP, Laravel, Symfony, WordPress с кастомной "
                            "разработкой, Go, Java, Kotlin, Spring, C#, .NET, C++, Rust, Ruby, "
                            "Rails, Swift, Objective-C, Dart, Flutter, React Native, Android, "
                            "iOS, SQL, PostgreSQL, MySQL, MongoDB, Redis, Docker, Kubernetes, "
                            "Bash и Linux. Не считай релевантными чистый дизайн, логотипы, "
                            "баннеры, тексты, переводы, SEO без разработки, озвучку, монтаж, "
                            "SMM, лидогенерацию, размещение рекламы и наполнение контентом без "
                            "программирования. Если задача на WordPress, Tilda, Bitrix, Shopify, "
                            "Webflow, OpenCart, Wix или похожей платформе включает код, "
                            "интеграции, API, модули, нестандартную логику или автоматизацию, "
                            "считай её релевантной. Отдавай приоритет проектам с понятным ТЗ, "
                            "реалистичным бюджетом и реальной технической задачей. "
                            "Верни строго JSON без markdown в формате "
                            '{"is_relevant": true, "score": 0-100, "summary": "краткий вывод", '
                            '"reasons": ["...", "..."], '
                            '"category": "backend|frontend|fullstack|bot|automation|integration|mobile|devops|data|ai|other-dev|non-dev"}.'
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(prompt_payload, ensure_ascii=False),
                    },
                ],
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        parsed = self._extract_json(content)
        score = clamp_score(float(parsed.get("score", 0)))
        if parsed.get("is_relevant") is False:
            score = min(score, 39.0)
        return ScoreResult(
            score=score,
            summary=self._build_summary(parsed),
            reasons=[str(item).strip() for item in parsed.get("reasons", []) if str(item).strip()],
        )

    def _extract_json(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError(f"Could not parse OpenRouter JSON response: {text!r}")
        return json.loads(match.group(0))

    def _build_summary(self, parsed: dict) -> str:
        summary = str(parsed.get("summary", "AI summary is empty")).strip()
        category = str(parsed.get("category", "")).strip()
        is_relevant = parsed.get("is_relevant")

        parts = []
        if is_relevant is not None:
            parts.append("relevant" if bool(is_relevant) else "non-relevant")
        if category:
            parts.append(category)
        if summary:
            parts.append(summary)
        return " | ".join(parts) if parts else "AI summary is empty"
