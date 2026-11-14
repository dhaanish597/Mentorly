"""Retired personalization routes and retained public teacher/path contracts."""
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from backend.app.coaching.teachers import get_teacher_for_subject
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

    def test_legacy_dashboard_is_retired_without_personalized_data(self) -> None:
        for query in ("", "?user_id=test-student-1"):
            with self.subTest(query=query):
                res = self.client.get(f"/api/v1/gamification/dashboard{query}")
                self.assertEqual(res.status_code, 410)
                self.assertEqual(res.headers["Cache-Control"], "no-store")
                data = res.json()
                self.assertIn("learning", data["detail"])
                for field in ("daily_quiz", "leaderboard", "graphs", "achievements", "weekly_missions"):
                    self.assertNotIn(field, data)

    def test_legacy_quiz_submission_and_replay_are_retired(self) -> None:
        submission = {
            "quiz_id": "quiz-2026-11-15",
            "selected_option_index": 0,
            "user_id": "test-student-1",
        }
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                res = self.client.post("/api/v1/gamification/quiz/submit", json=submission)
                self.assertEqual(res.status_code, 410)
                self.assertEqual(res.headers["Cache-Control"], "no-store")
                data = res.json()
                self.assertIn("learning", data["detail"])
                for field in ("already_completed", "is_correct", "explanation", "xp_awarded"):
                    self.assertNotIn(field, data)

    def test_legacy_leaderboard_periods_are_retired(self) -> None:
        for period in ("daily", "weekly", "all_time"):
            with self.subTest(period=period):
                res = self.client.get(f"/api/v1/gamification/leaderboard?period={period}")
                self.assertEqual(res.status_code, 410)
                self.assertEqual(res.headers["Cache-Control"], "no-store")
                data = res.json()
                self.assertIn("learning", data["detail"])
                self.assertNotIn("rankings", data)
                self.assertNotIn("user_rank", data)


if __name__ == "__main__":
    unittest.main()
