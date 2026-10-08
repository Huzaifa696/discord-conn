"""Tests for deterministic data pipeline (Zero AI)."""

import unittest
from discord_conn.pipeline.cleaner import MessageCleaner
from discord_conn.pipeline.threader import ConversationClusterer
from discord_conn.pipeline.context import ContextBuilder


class TestDeterministicPipeline(unittest.TestCase):
    def setUp(self):
        self.cleaner = MessageCleaner()
        self.clusterer = ConversationClusterer(session_gap_minutes=30)
        self.builder = ContextBuilder(cleaner=self.cleaner, clusterer=self.clusterer)

    def test_cleaner_bot_commands(self):
        self.assertTrue(self.cleaner.is_bot_command("!play song"))
        self.assertTrue(self.cleaner.is_bot_command("/help"))
        self.assertTrue(self.cleaner.is_bot_command("?rank"))
        self.assertTrue(self.cleaner.is_bot_command("$balance"))
        self.assertFalse(self.cleaner.is_bot_command("Hello everyone!"))
        self.assertFalse(self.cleaner.is_bot_command("Is that so?"))

    def test_cleaner_mentions_and_emojis(self):
        content = "Hey <@12345>, check out <:pepe:9999> in <#67890>!"
        user_map = {"12345": "Alice"}
        chan_map = {"67890": "announcements"}
        cleaned = self.cleaner.clean_text(content, user_id_map=user_map, channel_id_map=chan_map)
        self.assertEqual(cleaned, "Hey @Alice, check out :pepe: in #announcements!")

    def test_temporal_clustering(self):
        # 3 messages in morning burst, 2 messages in afternoon burst (gap > 30 mins)
        messages = [
            {"id": "1", "created_at": "2026-10-08T09:00:00Z", "content": "Morning standup", "author": {"username": "alice"}},
            {"id": "2", "created_at": "2026-10-08T09:05:00Z", "content": "Working on PR #12", "author": {"username": "bob"}},
            {"id": "3", "created_at": "2026-10-08T09:10:00Z", "content": "I will review it", "author": {"username": "charlie"}},
            # 4 hours gap
            {"id": "4", "created_at": "2026-10-08T13:15:00Z", "content": "PR is merged!", "author": {"username": "bob"}},
            {"id": "5", "created_at": "2026-10-08T13:16:00Z", "content": "Awesome job team", "author": {"username": "alice"}},
        ]

        sessions = self.clusterer.cluster_into_sessions(messages)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(len(sessions[0]), 3)
        self.assertEqual(len(sessions[1]), 2)

    def test_reply_tree_hierarchy(self):
        messages = [
            {"id": "root", "created_at": "2026-10-08T10:00:00Z", "content": "Question here"},
            {"id": "rep1", "reply_to_id": "root", "created_at": "2026-10-08T10:02:00Z", "content": "Answer 1"},
            {"id": "rep2", "reply_to_id": "rep1", "created_at": "2026-10-08T10:04:00Z", "content": "Follow up to answer 1"},
            {"id": "other", "created_at": "2026-10-08T10:05:00Z", "content": "Unrelated root"},
        ]

        trees = self.clusterer.build_trees(messages)
        self.assertEqual(len(trees), 2)  # root and other

        root_node = trees[0]
        self.assertEqual(root_node.id, "root")
        self.assertEqual(len(root_node.replies), 1)
        self.assertEqual(root_node.replies[0].id, "rep1")
        self.assertEqual(len(root_node.replies[0].replies), 1)
        self.assertEqual(root_node.replies[0].replies[0].id, "rep2")

    def test_context_builder_output(self):
        messages = [
            {
                "id": "1",
                "author_id": "u1",
                "username": "alice",
                "global_name": "Alice",
                "content": "Check out this documentation: https://docs.discord.com",
                "created_at": "2026-10-08T14:00:00Z",
            },
            {
                "id": "2",
                "author_id": "u2",
                "username": "bob",
                "global_name": "Bob",
                "content": "Thanks Alice!",
                "reply_to_id": "1",
                "created_at": "2026-10-08T14:02:00Z",
            },
        ]

        ctx = self.builder.build_channel_context(messages, channel_name="general")
        self.assertEqual(ctx["message_count"], 2)
        self.assertIn("Alice", ctx["participants"])
        self.assertIn("https://docs.discord.com", ctx["shared_links"])
        self.assertIn("# Conversation Transcript: #general", ctx["formatted_text"])
        self.assertIn("└──", ctx["formatted_text"])  # Reply tree branch rendering


if __name__ == "__main__":
    unittest.main()
