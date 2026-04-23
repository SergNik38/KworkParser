from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None

    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def _parse_int(value: object) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    text = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _parse_required_int(value: object, field_name: str) -> int:
    parsed = _parse_int(value)
    if parsed is None:
        raise ValueError(f"Required integer field {field_name!r} is missing or invalid")
    return parsed


def _parse_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"", "0", "false", "no", "off"}:
            return False
    return bool(value)


def _parse_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


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
        if not isinstance(payload, dict):
            raise ValueError("Project payload must be a dict")

        user = _parse_dict(payload.get("user"))
        user_data = _parse_dict(user.get("data"))
        project_id = _parse_required_int(payload.get("id"), "id")
        return cls(
            id=project_id,
            title=_parse_str(payload.get("name")),
            description=_parse_str(payload.get("description")),
            url=f"https://kwork.ru/projects/{project_id}",
            category_id=_parse_int(payload.get("category_id")),
            budget_rub=_parse_int(payload.get("priceLimit")),
            possible_budget_rub=_parse_int(payload.get("possiblePriceLimit")),
            max_days=_parse_int(payload.get("max_days")),
            username=_parse_str(user.get("username")),
            user_profile_url=_parse_str(payload.get("wantUserGetProfileUrl")),
            user_wants_count=_parse_int(user_data.get("wants_count")),
            user_hired_percent=_parse_int(user_data.get("wants_hired_percent")),
            kwork_count=_parse_int(payload.get("kwork_count")),
            views=_parse_int(payload.get("views_dirty")),
            created_at=_parse_datetime(payload.get("date_create")),
            active_at=_parse_datetime(payload.get("date_active")),
            expires_at=_parse_datetime(payload.get("date_expire")),
            has_portfolio_available=_parse_bool(payload.get("hasPortfolioAvailable")),
            raw=payload,
        )

    @property
    def searchable_text(self) -> str:
        return f"{self.title}\n{self.description}".lower()
