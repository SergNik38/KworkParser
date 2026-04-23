from __future__ import annotations

import logging
import time

from .config import Settings
from .kwork import KworkClient
from .models import Project
from .notifier import TelegramNotifier
from .scoring import OpenRouterScorer, RuleScorer, ScoreResult
from .storage import Storage


logger = logging.getLogger(__name__)


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
        new_project_ids: list[int] = []

        for page in range(1, self.settings.max_pages + 1):
            projects = self.client.fetch_projects(page=page)
            if not projects:
                break

            for project in projects:
                if self.storage.is_known(project.id):
                    continue
                rule_result = self.rule_scorer.score(project)
                self.storage.save_project(project, rule_result)
                new_project_ids.append(project.id)

        if bootstrap_mode:
            for project_id in new_project_ids:
                self.storage.mark_ignored(project_id, "bootstrap first run")
            logger.info(
                "Bootstrap saved %s current projects without notifications",
                len(new_project_ids),
            )
            return 0

        processed = 0
        include_previewed = not self.settings.dry_run
        for candidate in self.storage.get_notification_candidates(include_previewed=include_previewed):
            project = candidate.project
            rule_result = candidate.rule_result

            if rule_result.score < self.settings.min_rule_score:
                self.storage.mark_ignored(project.id, "rule score below threshold")
                continue

            ai_result = candidate.ai_result
            if ai_result is None:
                try:
                    ai_result = self._score_with_ai(project, rule_result)
                except Exception as exc:
                    self.storage.mark_error(project.id, f"AI scoring failed: {exc}")
                    logger.warning("AI scoring failed for project %s", project.id, exc_info=True)
                    continue
                if ai_result is not None:
                    self.storage.save_ai_result(project.id, ai_result)

            if ai_result and ai_result.score < self.settings.min_ai_score:
                self.storage.mark_ignored(project.id, "AI score below threshold", ai_result)
                continue

            try:
                self.notifier.send(project, rule_result, ai_result)
            except Exception as exc:
                self.storage.mark_error(project.id, f"Telegram notification failed: {exc}")
                logger.warning(
                    "Telegram notification failed for project %s",
                    project.id,
                    exc_info=True,
                )
                continue

            if self.settings.dry_run:
                self.storage.mark_previewed(project.id, ai_result)
            else:
                self.storage.mark_notified(project.id, ai_result)
            processed += 1

        return processed

    def run_forever(self) -> None:
        while True:
            try:
                processed = self.run_once()
                logger.info("Processed %s notification candidates", processed)
            except Exception as exc:
                logger.exception("Polling loop failed: %s", exc)
            time.sleep(self.settings.poll_interval_seconds)

    def _score_with_ai(self, project: Project, rule_result: ScoreResult) -> ScoreResult | None:
        if not self.ai_scorer:
            return None
        return self.ai_scorer.score(project, rule_result)
