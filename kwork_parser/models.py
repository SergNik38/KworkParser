from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _parse_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


@dataclass(slots=True)
class Project:
    id: int
    title: str
    description: str
    url: str
    category_id: int | None
    budget_rub: int | None
    possible_budget_rub: int | None
    max_days: int | None
    username: str
    user_profile_url: str
    user_wants_count: int | None
    user_hired_percent: int | None
    kwork_count: int | None
    views: int | None
    created_at: datetime | None
    active_at: datetime | None
    expires_at: datetime | None
    has_portfolio_available: bool
    raw: dict

    @classmethod
    def from_api(cls, payload: dict) -> "Project":
        user = payload.get("user") or {}
        user_data = user.get("data") or {}
        project_id = int(payload["id"])
        return cls(
            id=project_id,
            title=(payload.get("name") or "").strip(),
            description=(payload.get("description") or "").strip(),
            url=f"https://kwork.ru/projects/{project_id}",
            category_id=_parse_int(payload.get("category_id")),
            budget_rub=_parse_int(payload.get("priceLimit")),
            possible_budget_rub=_parse_int(payload.get("possiblePriceLimit")),
            max_days=_parse_int(payload.get("max_days")),
            username=(user.get("username") or "").strip(),
            user_profile_url=(payload.get("wantUserGetProfileUrl") or "").strip(),
            user_wants_count=_parse_int(user_data.get("wants_count")),
            user_hired_percent=_parse_int(user_data.get("wants_hired_percent")),
            kwork_count=_parse_int(payload.get("kwork_count")),
            views=_parse_int(payload.get("views_dirty")),
            created_at=_parse_datetime(payload.get("date_create")),
            active_at=_parse_datetime(payload.get("date_active")),
            expires_at=_parse_datetime(payload.get("date_expire")),
            has_portfolio_available=bool(payload.get("hasPortfolioAvailable")),
            raw=payload,
        )

    @property
    def searchable_text(self) -> str:
        return f"{self.title}\n{self.description}".lower()
