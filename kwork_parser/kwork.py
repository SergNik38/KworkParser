from __future__ import annotations

import time

import requests

from .config import Settings
from .models import Project


class KworkClient:
    BASE_URL = "https://kwork.ru"
    PROJECTS_URL = f"{BASE_URL}/projects"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/135.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": self.PROJECTS_URL,
            }
        )

    def fetch_projects(self, page: int = 1) -> list[Project]:
        payload = {}
        if page > 1:
            payload["page"] = str(page)

        last_error: Exception | None = None
        for attempt in range(1, self.settings.request_retries + 1):
            try:
                response = self.session.post(
                    self.PROJECTS_URL,
                    data=payload,
                    timeout=self.settings.request_timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                break
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt >= self.settings.request_retries:
                    raise
                time.sleep(self.settings.retry_backoff_seconds)
        else:
            raise RuntimeError(f"Kwork request failed: {last_error}")

        if not data.get("success"):
            raise RuntimeError(f"Kwork returned unsuccessful response: {data!r}")

        rows = (((data.get("data") or {}).get("pagination") or {}).get("data") or [])
        return [Project.from_api(item) for item in rows]
