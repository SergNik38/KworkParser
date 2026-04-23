from __future__ import annotations

import unittest

from kwork_parser.kwork import KworkClient
from kwork_parser.models import Project


class ProjectParsingTests(unittest.TestCase):
    def test_from_api_keeps_required_id_but_tolerates_bad_optional_fields(self) -> None:
        project = Project.from_api(
            {
                "id": "42",
                "name": 123,
                "description": None,
                "category_id": "not-a-number",
                "priceLimit": "10 500",
                "possiblePriceLimit": "bad",
                "max_days": "",
                "user": {
                    "username": 456,
                    "data": {
                        "wants_count": "n/a",
                        "wants_hired_percent": "25.9",
                    },
                },
                "wantUserGetProfileUrl": None,
                "kwork_count": "2.0",
                "views_dirty": "1,5",
                "date_create": "bad date",
                "date_active": "2026-04-23T10:00:00",
                "date_expire": "",
                "hasPortfolioAvailable": "0",
            }
        )

        self.assertEqual(project.id, 42)
        self.assertEqual(project.title, "123")
        self.assertEqual(project.description, "")
        self.assertIsNone(project.category_id)
        self.assertEqual(project.budget_rub, 10500)
        self.assertIsNone(project.possible_budget_rub)
        self.assertIsNone(project.max_days)
        self.assertEqual(project.username, "456")
        self.assertIsNone(project.user_wants_count)
        self.assertEqual(project.user_hired_percent, 25)
        self.assertEqual(project.kwork_count, 2)
        self.assertEqual(project.views, 1)
        self.assertIsNone(project.created_at)
        self.assertIsNotNone(project.active_at)
        self.assertIsNone(project.expires_at)
        self.assertFalse(project.has_portfolio_available)

    def test_from_api_rejects_payload_without_valid_id(self) -> None:
        with self.assertRaises(ValueError):
            Project.from_api({"id": "missing"})


class KworkClientParsingTests(unittest.TestCase):
    def test_parse_projects_skips_malformed_items_only(self) -> None:
        client = KworkClient.__new__(KworkClient)

        projects = client._parse_projects(
            [
                {"id": "bad"},
                {
                    "id": "100",
                    "name": "Python task",
                    "description": "Build parser",
                    "user": {},
                },
                "not a dict",
            ]
        )

        self.assertEqual([project.id for project in projects], [100])

    def test_parse_projects_returns_empty_list_for_unexpected_rows_shape(self) -> None:
        client = KworkClient.__new__(KworkClient)

        self.assertEqual(client._parse_projects({"id": 1}), [])


if __name__ == "__main__":
    unittest.main()
