from __future__ import annotations

import time
from datetime import datetime

from .config import Settings
from .kwork import KworkClient
from .models import Project
from .notifier import TelegramNotifier
from .scoring import OpenRouterScorer, RuleScorer, ScoreResult
from .storage import Storage


class Application:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = KworkClient(settings)
        self.storage = Storage(settings.database_path)
        self.rule_scorer = RuleScorer(settings)
        self.ai_scorer = OpenRouterScorer(settings) if settings.ai_enabled else None
        self.notifier = TelegramNotifier(settings)

    def run_once(self) -> int:
        bootstrap_mode = self.settings.skip_existing_on_first_run and self.storage.is_empty()
        new_candidates: list[tuple[Project, ScoreResult]] = []

        for page in range(1, self.settings.max_pages + 1):
            projects = self.client.fetch_projects(page=page)
            if not projects:
                break

            for project in projects:
                if self.storage.is_known(project.id):
                    continue
                rule_result = self.rule_scorer.score(project)
                self.storage.save_project(project, rule_result)
                new_candidates.append((project, rule_result))

        new_candidates.sort(key=lambda item: item[0].created_at or datetime.min)

        if bootstrap_mode:
            print(f"[bootstrap] saved {len(new_candidates)} current projects without notifications")
            return 0

        sent = 0
        for project, rule_result in new_candidates:
            if rule_result.score < self.settings.min_rule_score:
                continue

            ai_result = self._score_with_ai(project, rule_result)
            if ai_result and ai_result.score < self.settings.min_ai_score:
                continue

            self.notifier.send(project, rule_result, ai_result)
            self.storage.mark_notified(project.id, ai_result)
            sent += 1

        return sent

    def run_forever(self) -> None:
        while True:
            try:
                sent = self.run_once()
                print(f"[loop] sent {sent} notifications")
            except Exception as exc:
                print(f"[loop] error: {exc}")
            time.sleep(self.settings.poll_interval_seconds)

    def _score_with_ai(self, project: Project, rule_result: ScoreResult) -> ScoreResult | None:
        if not self.ai_scorer:
            return None
        return self.ai_scorer.score(project, rule_result)
