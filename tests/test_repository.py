"""Tests for SQLite Schema and Repository operations."""

import os
import tempfile
import unittest
from pathlib import Path

from discord_conn.db.repository import Repository


class TestRepository(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.repo = Repository(self.db_path)

    def tearDown(self):
        self.repo.close()
        self.temp_dir.cleanup()

    def test_upsert_channel_and_guild(self):
        self.repo.upsert_guild("guild_1", "Engineering Guild", "icon_hash")
        guilds = self.repo.list_guilds()
        self.assertEqual(len(guilds), 1)
        self.assertEqual(guilds[0]["name"], "Engineering Guild")

        self.repo.upsert_channel("chan_1", "general", guild_id="guild_1", topic="General discussion")
        channels = self.repo.list_channels(guild_id="guild_1")
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]["name"], "general")
        self.assertEqual(channels[0]["topic"], "General discussion")

    def test_upsert_messages_and_threads(self):
        self.repo.upsert_channel("chan_1", "dev")

        # Insert 3 messages: Root -> Reply 1 -> Reply 2
        messages = [
            {
                "id": "msg_1",
                "channel_id": "chan_1",
                "content": "Does anyone know the status of the release?",
                "timestamp": "2026-10-08T10:00:00Z",
                "author": {"id": "user_alice", "username": "alice", "global_name": "Alice"},
            },
            {
                "id": "msg_2",
                "channel_id": "chan_1",
                "content": "Release is blocked on QA testing.",
                "timestamp": "2026-10-08T10:05:00Z",
                "message_reference": {"message_id": "msg_1"},
                "author": {"id": "user_bob", "username": "bob", "global_name": "Bob"},
            },
            {
                "id": "msg_3",
                "channel_id": "chan_1",
                "content": "I just approved the QA tests! Ready to ship.",
                "timestamp": "2026-10-08T10:10:00Z",
                "message_reference": {"message_id": "msg_2"},
                "author": {"id": "user_charlie", "username": "charlie", "global_name": "Charlie"},
            },
        ]

        synced_count = self.repo.upsert_messages_batch(messages)
        self.assertEqual(synced_count, 3)

        # Retrieve messages
        stored = self.repo.get_messages_for_channel("chan_1")
        self.assertEqual(len(stored), 3)

        # Verify thread reconstruction context
        thread_context = self.repo.get_thread_context("msg_3")
        self.assertEqual(len(thread_context), 3)
        self.assertEqual([m["id"] for m in thread_context], ["msg_1", "msg_2", "msg_3"])

    def test_save_and_get_summary(self):
        self.repo.upsert_channel("chan_1", "general")
        summary_id = self.repo.save_summary(
            channel_id="chan_1",
            window_start="2026-10-08T00:00:00Z",
            window_end="2026-10-08T12:00:00Z",
            summary_markdown="## Test Summary\nAll tasks completed.",
            channel_name="general",
            message_count=10,
            model_used="gemini-2.5-flash",
        )
        self.assertGreater(summary_id, 0)

        latest = self.repo.get_latest_summary("chan_1")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["message_count"], 10)
        self.assertIn("All tasks completed", latest["summary_markdown"])


if __name__ == "__main__":
    unittest.main()
