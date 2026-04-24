from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str | os.PathLike[str] = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(value)


def _parse_float(value: str | None, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    return float(value)


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_int_csv(value: str | None) -> list[int]:
    return [int(item) for item in _parse_csv(value)]


@dataclass(slots=True)
class Settings:
    poll_interval_seconds: int
    request_timeout_seconds: int
    request_retries: int
    retry_backoff_seconds: int
    max_pages: int
    database_path: Path
    skip_existing_on_first_run: bool
    min_rule_score: float
    min_ai_score: float
    min_price: int | None
    max_price: int | None
    min_hiring_percent: int | None
    category_ids: list[int]
    include_keywords: list[str]
    exclude_keywords: list[str]
    dry_run: bool
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    openrouter_api_key: str | None
    openrouter_model: str | None
    openrouter_site_url: str | None
    openrouter_site_name: str | None
    response_draft_api_key: str | None
    response_draft_model: str | None
    response_draft_base_url: str | None
    response_draft_timeout_seconds: int | None
    ai_profile_brief: str
    ai_extra_instructions: str

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_model)

    @property
    def response_draft_enabled(self) -> bool:
        api_key = self.response_draft_api_key or self.openrouter_api_key
        model = self.response_draft_model or self.openrouter_model
        return bool(api_key and model)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id and not self.dry_run)

    @classmethod
    def from_env(cls) -> "Settings":
        load_env_file()
        return cls(
            poll_interval_seconds=int(os.getenv("KWORK_POLL_INTERVAL_SECONDS", "45")),
            request_timeout_seconds=int(os.getenv("KWORK_REQUEST_TIMEOUT_SECONDS", "20")),
            request_retries=max(1, int(os.getenv("KWORK_REQUEST_RETRIES", "3"))),
            retry_backoff_seconds=max(1, int(os.getenv("KWORK_RETRY_BACKOFF_SECONDS", "2"))),
            max_pages=max(1, int(os.getenv("KWORK_MAX_PAGES", "2"))),
            database_path=Path(os.getenv("KWORK_DATABASE_PATH", "data/kwork_parser.db")),
            skip_existing_on_first_run=_parse_bool(os.getenv("KWORK_SKIP_EXISTING_ON_FIRST_RUN"), True),
            min_rule_score=_parse_float(os.getenv("KWORK_MIN_RULE_SCORE"), 55.0),
            min_ai_score=_parse_float(os.getenv("KWORK_MIN_AI_SCORE"), 70.0),
            min_price=_parse_int(os.getenv("KWORK_MIN_PRICE")),
            max_price=_parse_int(os.getenv("KWORK_MAX_PRICE")),
            min_hiring_percent=_parse_int(os.getenv("KWORK_MIN_HIRING_PERCENT")),
            category_ids=_parse_int_csv(os.getenv("KWORK_CATEGORY_IDS")),
            include_keywords=[item.lower() for item in _parse_csv(os.getenv("KWORK_INCLUDE_KEYWORDS"))],
            exclude_keywords=[item.lower() for item in _parse_csv(os.getenv("KWORK_EXCLUDE_KEYWORDS"))],
            dry_run=_parse_bool(os.getenv("KWORK_DRY_RUN"), True),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
            openrouter_model=os.getenv("OPENROUTER_MODEL") or None,
            openrouter_site_url=os.getenv("OPENROUTER_SITE_URL") or None,
            openrouter_site_name=os.getenv("OPENROUTER_SITE_NAME") or None,
            response_draft_api_key=os.getenv("RESPONSE_DRAFT_API_KEY") or None,
            response_draft_model=os.getenv("RESPONSE_DRAFT_MODEL") or None,
            response_draft_base_url=os.getenv("RESPONSE_DRAFT_BASE_URL") or None,
            response_draft_timeout_seconds=_parse_int(os.getenv("RESPONSE_DRAFT_TIMEOUT_SECONDS")),
            ai_profile_brief=os.getenv(
                "AI_PROFILE_BRIEF",
                "Ищу интересные проекты по разработке ПО: backend, frontend, fullstack, mobile, боты, API, интеграции, автоматизация, DevOps, data и AI.",
            ),
            ai_extra_instructions=os.getenv(
                "AI_EXTRA_INSTRUCTIONS",
                "Считай релевантными любые задачи, где нужна реальная разработка, код, интеграции или техническая логика, а не только Python-заказы.",
            ),
        )
