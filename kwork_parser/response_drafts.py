from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from pathlib import PurePosixPath

import requests

from .config import Settings
from .models import Project
from .scoring import ScoreResult


@dataclass(slots=True)
class ResponseDraftResult:
    text: str
    demo_available: bool
    demo_summary: str


@dataclass(slots=True)
class GeneratedDemoProject:
    name: str
    summary: str
    output_dir: Path
    archive_path: Path


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
    ) -> ResponseDraftResult:
        prompt_payload = self._build_base_payload(project, rule_result, ai_result, variant)
        if variant == "short":
            prompt_payload["extra_instructions"] += "\nСделай отклик заметно короче: 3-5 предложений."
        elif variant == "questions":
            prompt_payload["extra_instructions"] += "\nДобавь отдельный короткий блок уточняющих вопросов."

        parsed = self._request_json(
            load_response_draft_prompt(),
            prompt_payload,
            temperature=0.35,
            max_tokens=700,
        )

        draft_text = self._clean_text(parsed.get("draft_text"))
        if not draft_text:
            raise ValueError("Response draft is empty")

        demo_available = self._parse_bool(parsed.get("demo_available"))
        demo_summary = self._clean_text(parsed.get("demo_summary")) if demo_available else ""
        return ResponseDraftResult(
            text=draft_text,
            demo_available=demo_available,
            demo_summary=demo_summary,
        )

    def generate_demo_project(
        self,
        project: Project,
        rule_result: ScoreResult,
        ai_result: ScoreResult | None,
        demo_summary: str,
    ) -> GeneratedDemoProject:
        prompt_payload = self._build_base_payload(project, rule_result, ai_result, variant="demo")
        prompt_payload["demo_summary"] = demo_summary
        parsed = self._request_json(
            load_demo_project_prompt(),
            prompt_payload,
            temperature=0.25,
            max_tokens=2400,
        )
        return self._write_demo_project(project, parsed, demo_summary)

    def _build_base_payload(
        self,
        project: Project,
        rule_result: ScoreResult,
        ai_result: ScoreResult | None,
        variant: str,
    ) -> dict:
        return {
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

    def _request_json(
        self,
        system_prompt: str,
        prompt_payload: dict,
        *,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        content = self._request_content(
            system_prompt,
            prompt_payload,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        parsed = self._extract_json(content)
        if not isinstance(parsed, dict):
            raise ValueError("Response draft JSON must be an object")
        return parsed

    def _request_content(
        self,
        system_prompt: str,
        prompt_payload: dict,
        *,
        temperature: float,
        max_tokens: int,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.openrouter_site_url:
            headers["HTTP-Referer"] = self.settings.openrouter_site_url
        if self.settings.openrouter_site_name:
            headers["X-Title"] = self.settings.openrouter_site_name

        request_body = {
            "model": self._model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
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
                content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
                if not content:
                    raise ValueError("Response draft model returned empty content")
                return content
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

    def _clean_text(self, value: object) -> str:
        text = str(value or "").strip()
        if text.startswith("```"):
            text = self._strip_code_fence(text)
        return text.strip()

    def _extract_json(self, text: str) -> dict:
        clean_text = self._clean_text(text)
        decoder = json.JSONDecoder()

        for match in re.finditer(r"\{", clean_text):
            try:
                parsed, _ = decoder.raw_decode(clean_text[match.start() :])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        raise ValueError(f"Could not parse response-draft JSON response: {text!r}")

    def _parse_bool(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        text = str(value or "").strip().lower()
        return text in {"1", "true", "yes", "on"}

    def _write_demo_project(
        self,
        project: Project,
        parsed: dict,
        demo_summary: str,
    ) -> GeneratedDemoProject:
        raw_files = parsed.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("Demo project response must include files")

        demo_root = self.settings.database_path.parent / "demo_projects"
        output_dir = demo_root / f"project_{project.id}"
        archive_path = demo_root / f"project_{project.id}.zip"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if archive_path.exists():
            archive_path.unlink()

        written_paths: list[str] = []
        for item in raw_files[:12]:
            if not isinstance(item, dict):
                continue
            relative_path = self._safe_relative_path(item.get("path"))
            content = self._clean_text(item.get("content"))
            if not relative_path or not content:
                continue

            full_path = output_dir / relative_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content + "\n", encoding="utf-8")
            written_paths.append(relative_path.as_posix())

        if not written_paths:
            raise ValueError("Demo project response produced no valid files")

        if "README.md" not in written_paths:
            readme_path = output_dir / "README.md"
            readme_path.write_text(
                self._build_demo_readme(parsed, demo_summary, written_paths),
                encoding="utf-8",
            )
            written_paths.append("README.md")

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(output_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(output_dir))

        name = self._clean_text(parsed.get("project_name")) or f"kwork-demo-{project.id}"
        summary = self._clean_text(parsed.get("summary")) or demo_summary or project.title
        return GeneratedDemoProject(
            name=name,
            summary=summary,
            output_dir=output_dir,
            archive_path=archive_path,
        )

    def _safe_relative_path(self, value: object) -> Path | None:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw:
            return None
        posix_path = PurePosixPath(raw)
        if posix_path.is_absolute():
            return None
        if any(part in {"", ".", ".."} for part in posix_path.parts):
            return None
        return Path(*posix_path.parts)

    def _build_demo_readme(self, parsed: dict, demo_summary: str, written_paths: list[str]) -> str:
        stack = parsed.get("stack")
        run_steps = parsed.get("run_steps")
        lines = [
            "# Demo project",
            "",
            self._clean_text(parsed.get("summary")) or demo_summary or "Минимальный демо-проект по задаче.",
            "",
        ]
        if isinstance(stack, list) and stack:
            lines.extend(["## Stack", "", *[f"- {self._clean_text(item)}" for item in stack if self._clean_text(item)], ""])
        if isinstance(run_steps, list) and run_steps:
            lines.extend(
                ["## Run", "", *[f"{index}. {self._clean_text(item)}" for index, item in enumerate(run_steps, start=1) if self._clean_text(item)], ""]
            )
        lines.extend(["## Files", "", *[f"- `{path}`" for path in written_paths], ""])
        return "\n".join(lines).strip() + "\n"

    def _strip_code_fence(self, text: str) -> str:
        text = re.sub(r"^```(?:json)?", "", text).strip()
        return re.sub(r"```$", "", text).strip()


@lru_cache(maxsize=1)
def load_response_draft_prompt() -> str:
    prompt_path = Path(__file__).with_name("prompts") / "response_draft_system_prompt.txt"
    return prompt_path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def load_demo_project_prompt() -> str:
    prompt_path = Path(__file__).with_name("prompts") / "demo_project_system_prompt.txt"
    return prompt_path.read_text(encoding="utf-8").strip()
