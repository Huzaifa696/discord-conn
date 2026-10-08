"""Tests for Discord API client and Summarizer service with mocks."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from discord_conn.ai.gemini import GeminiClient
from discord_conn.ai.summarizer import Summarizer
from discord_conn.client.discord_api import DiscordAPIClient
from discord_conn.config import Config
from discord_conn.db.repository import Repository


class TestDiscordAPIClient(unittest.TestCase):
    def test_client_headers_and_initialization(self):
        client = DiscordAPIClient(token="test_user_token_123")
        self.assertEqual(client.session.headers["Authorization"], "test_user_token_123")
        self.assertIn("Mozilla", client.session.headers["User-Agent"])

    @patch("requests.Session.request")
    def test_fetch_channel_messages(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"id": "m1", "content": "Hello", "author": {"id": "u1", "username": "alice"}},
            {"id": "m2", "content": "World", "author": {"id": "u2", "username": "bob"}},
        ]
        mock_request.return_value = mock_resp

        client = DiscordAPIClient(token="dummy_token", request_delay=0.0)
        messages = client.get_channel_messages("chan_123", limit=50)

        self.assertEqual(len(messages), 2)
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertIn("channels/chan_123/messages", kwargs["url"])
        self.assertEqual(kwargs["params"]["limit"], 50)

    @patch("requests.Session.request")
    def test_send_message_reply(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "sent_123", "content": "My reply"}
        mock_request.return_value = mock_resp

        client = DiscordAPIClient(token="dummy_token", request_delay=0.0)
        res = client.send_message("chan_123", "My reply", reply_to_message_id="parent_999")

        self.assertEqual(res["id"], "sent_123")
        args, kwargs = mock_request.call_args
        self.assertEqual(kwargs["json"]["content"], "My reply")
        self.assertEqual(kwargs["json"]["message_reference"]["message_id"], "parent_999")


class TestSummarizerEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.db_path = self.temp_path / "test.db"
        self.reports_path = self.temp_path / "reports"
        self.repo = Repository(self.db_path)

        # Mock Gemini
        self.mock_gemini = MagicMock(spec=GeminiClient)
        self.mock_gemini.generate.return_value = (
            "### Executive Summary\nThe team finalized the v2 release plan.\n"
            "### Key Topics\n- QA tests passed.\n"
            "### Decisions\n- Ship to production at 18:00 UTC."
        )

        # Config mock
        self.mock_cfg = MagicMock(spec=Config)
        self.mock_cfg.ai_model = "gemini-3.8-flash"
        self.mock_cfg.ai_fallback_model = "gemini-flash-latest"
        self.mock_cfg.ai_temperature = 0.3
        self.mock_cfg.max_context_tokens = 50000
        self.mock_cfg.reports_dir = self.reports_path
        self.mock_cfg.gemini_api_key = "test_key"

    def tearDown(self):
        self.repo.close()
        self.temp_dir.cleanup()

    def test_summarize_channel_flow(self):
        # 1. Setup channel and messages
        self.repo.upsert_channel("chan_1", "engineering")
        self.repo.upsert_messages_batch([
            {
                "id": "1",
                "channel_id": "chan_1",
                "content": "Release review starting.",
                "timestamp": "2026-10-08T10:00:00Z",
                "author": {"id": "u1", "username": "alice"},
            },
            {
                "id": "2",
                "channel_id": "chan_1",
                "content": "All tests green.",
                "timestamp": "2026-10-08T10:05:00Z",
                "reply_to_id": "1",
                "author": {"id": "u2", "username": "bob"},
            },
        ])

        summarizer = Summarizer(
            repository=self.repo,
            gemini_client=self.mock_gemini,
            cfg=self.mock_cfg,
        )

        result = summarizer.summarize_channel("chan_1", limit=100)

        self.assertTrue(result["success"])
        self.assertEqual(result["message_count"], 2)
        self.mock_gemini.generate.assert_called_once()

        # Check markdown file was saved
        report_file = Path(result["report_path"])
        self.assertTrue(report_file.exists())
        content = report_file.read_text(encoding="utf-8")
        self.assertIn("The team finalized the v2 release plan", content)

        # Check DB summary was saved
        db_summary = self.repo.get_latest_summary("chan_1")
        self.assertIsNotNone(db_summary)
        self.assertEqual(db_summary["message_count"], 2)

    def test_summarize_channel_all_time(self):
        self.repo.upsert_channel("chan_old", "archive")
        self.repo.upsert_messages_batch([
            {
                "id": "old_1",
                "channel_id": "chan_old",
                "content": "Message from months ago.",
                "timestamp": "2025-01-01T00:00:00Z",
                "author": {"id": "u1", "username": "alice"},
            }
        ])

        summarizer = Summarizer(
            repository=self.repo,
            gemini_client=self.mock_gemini,
            cfg=self.mock_cfg,
        )

        result = summarizer.summarize_channel("chan_old", all_time=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["message_count"], 1)

    def test_summarize_server(self):
        self.repo.upsert_guild("guild_1", "Engineering Guild")
        self.repo.upsert_channel("c1", "frontend", guild_id="guild_1")
        self.repo.upsert_channel("c2", "backend", guild_id="guild_1")
        self.repo.upsert_messages_batch([
            {
                "id": "m1",
                "channel_id": "c1",
                "content": "UI migration done.",
                "timestamp": "2026-10-08T10:00:00Z",
                "author": {"id": "u1", "username": "alice"},
            },
            {
                "id": "m2",
                "channel_id": "c2",
                "content": "API endpoints updated.",
                "timestamp": "2026-10-08T10:30:00Z",
                "author": {"id": "u2", "username": "bob"},
            },
        ])

        summarizer = Summarizer(
            repository=self.repo,
            gemini_client=self.mock_gemini,
            cfg=self.mock_cfg,
        )

        result = summarizer.summarize_server("guild_1", all_time=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["message_count"], 2)
        self.assertEqual(result["channel_count"], 2)
        self.assertTrue(Path(result["report_path"]).exists())


if __name__ == "__main__":
    unittest.main()
