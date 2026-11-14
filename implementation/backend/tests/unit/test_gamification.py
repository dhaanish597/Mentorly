"""Unit tests for gamification, daily quizzes, leaderboards, and teachers."""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from backend.app.coaching.teachers import TEACHERS, get_teacher_for_subject
from backend.app.core.config import Settings
from backend.app.db.repository import SQLiteRepository
from backend.app.main import create_app


class GamificationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_gamification.sqlite3"
        repo = SQLiteRepository(self.db_path)
        repo.initialize()

        self.settings = Settings(
            database_path=self.db_path,
            secret_key="test-key-32-bytes-minimum-required!!",
            env="test",
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_teachers_resolution(self) -> None:
        self.assertEqual(get_teacher_for_subject("dsa").id, "astra")
        self.assertEqual(get_teacher_for_subject("Quantitative Aptitude").id, "veda")
        self.assertEqual(get_teacher_for_subject("system design").id, "nexus")
        self.assertEqual(get_teacher_for_subject("Operating Systems").id, "corel")
        self.assertEqual(get_teacher_for_subject(None).id, "astra")

    def test_get_teachers_endpoint(self) -> None:
        res = self.client.get("/api/v1/gamification/teachers")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 4)
        names = [t["name"] for t in data]
        self.assertIn("Astra", names)
        self.assertIn("Veda", names)
        self.assertIn("Nexus", names)
        self.assertIn("Corel", names)

    def test_get_learning_paths_endpoint(self) -> None:
        res = self.client.get("/api/v1/gamification/learning-paths")
        self.assertEqual(res.status_code, 200)
        paths = res.json()
        self.assertEqual(len(paths), 5)
        slugs = [p["slug"] for p in paths]
        self.assertEqual(slugs, ["dsa", "aptitude", "system_design", "cs_fundamentals", "verbal"])

    def test_dashboard_endpoint(self) -> None:
        res = self.client.get("/api/v1/gamification/dashboard")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("daily_quiz", data)
        self.assertIn("leaderboard", data)
        self.assertIn("graphs", data)
        self.assertIn("achievements", data)
        self.assertIn("weekly_missions", data)
        self.assertEqual(len(data["achievements"]), 10)
        self.assertGreaterEqual(len(data["leaderboard"]), 1)

    def test_quiz_submit_and_duplicate_prevention(self) -> None:
        dash_res = self.client.get("/api/v1/gamification/dashboard?user_id=test-student-1")
        dash_data = dash_res.json()
        quiz = dash_data["daily_quiz"]
        self.assertIsNotNone(quiz)

        # Submit answer
        submit_res = self.client.post(
            "/api/v1/gamification/quiz/submit",
            json={"quiz_id": quiz["id"], "selected_option_index": 0, "user_id": "test-student-1"},
        )
        self.assertEqual(submit_res.status_code, 200)
        result = submit_res.json()
        self.assertFalse(result["already_completed"])
        self.assertIn("is_correct", result)
        self.assertIn("explanation", result)

        # Duplicate submit
        dup_res = self.client.post(
            "/api/v1/gamification/quiz/submit",
            json={"quiz_id": quiz["id"], "selected_option_index": 0, "user_id": "test-student-1"},
        )
        self.assertEqual(dup_res.status_code, 200)
        dup_result = dup_res.json()
        self.assertTrue(dup_result["already_completed"])
        self.assertEqual(dup_result["xp_awarded"], 0)

    def test_leaderboard_periods(self) -> None:
        for period in ("daily", "weekly", "all_time"):
            res = self.client.get(f"/api/v1/gamification/leaderboard?period={period}")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["period"], period)
            self.assertIsInstance(data["rankings"], list)


if __name__ == "__main__":
    unittest.main()
