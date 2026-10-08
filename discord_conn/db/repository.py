"""Repository layer for interacting with SQLite database."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .schema import init_db


class Repository:
    def __init__(self, db_path: Union[str, Path]):
        self.db_path = Path(db_path)
        self.conn = init_db(self.db_path)

    def close(self) -> None:
        if self.conn:
            self.conn.close()

    def upsert_guild(self, guild_id: str, name: str, icon: Optional[str] = None) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO guilds (id, name, icon, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    icon = excluded.icon,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (guild_id, name, icon),
            )

    def upsert_channel(
        self,
        channel_id: str,
        name: str,
        guild_id: Optional[str] = None,
        channel_type: int = 0,
        topic: Optional[str] = None,
        last_message_id: Optional[str] = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO channels (id, guild_id, name, type, topic, last_message_id, last_synced_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    guild_id = COALESCE(excluded.guild_id, channels.guild_id),
                    type = excluded.type,
                    topic = COALESCE(excluded.topic, channels.topic),
                    last_message_id = COALESCE(excluded.last_message_id, channels.last_message_id),
                    last_synced_at = CURRENT_TIMESTAMP
                """,
                (channel_id, guild_id, name, channel_type, topic, last_message_id),
            )

    def upsert_user(
        self,
        user_id: str,
        username: str,
        discriminator: Optional[str] = None,
        global_name: Optional[str] = None,
        avatar: Optional[str] = None,
        is_bot: bool = False,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO users (id, username, discriminator, global_name, avatar, is_bot, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    discriminator = excluded.discriminator,
                    global_name = excluded.global_name,
                    avatar = excluded.avatar,
                    is_bot = excluded.is_bot,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, username, discriminator, global_name, avatar, 1 if is_bot else 0),
            )

    def upsert_message(self, msg_data: Dict[str, Any]) -> None:
        """Upsert a single message dictionary into the messages table."""
        author = msg_data.get("author", {})
        if author and "id" in author:
            self.upsert_user(
                user_id=str(author["id"]),
                username=author.get("username", "Unknown"),
                discriminator=author.get("discriminator"),
                global_name=author.get("global_name"),
                avatar=author.get("avatar"),
                is_bot=author.get("bot", False),
            )

        channel_id = str(msg_data["channel_id"])
        msg_id = str(msg_data["id"])
        guild_id = str(msg_data.get("guild_id")) if msg_data.get("guild_id") else None
        if not guild_id:
            ch_row = self.conn.execute("SELECT guild_id FROM channels WHERE id = ?", (channel_id,)).fetchone()
            if ch_row and ch_row["guild_id"]:
                guild_id = str(ch_row["guild_id"])
        author_id = str(author.get("id", "0"))
        content = msg_data.get("content", "")
        created_at = msg_data.get("timestamp")
        edited_at = msg_data.get("edited_timestamp")

        # Reply reference
        reply_to_id = None
        message_reference = msg_data.get("message_reference")
        if message_reference and "message_id" in message_reference:
            reply_to_id = str(message_reference["message_id"])

        thread_id = None
        if "thread" in msg_data and msg_data["thread"]:
            thread_id = str(msg_data["thread"].get("id"))

        attachments_json = json.dumps(msg_data.get("attachments", []))
        reactions_json = json.dumps(msg_data.get("reactions", []))
        mentions_json = json.dumps(msg_data.get("mentions", []))
        is_pinned = 1 if msg_data.get("pinned", False) else 0

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO messages (
                    id, channel_id, guild_id, author_id, content, created_at, edited_at,
                    reply_to_id, thread_id, attachments_json, reactions_json, mentions_json, is_pinned
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    content = excluded.content,
                    edited_at = excluded.edited_at,
                    attachments_json = excluded.attachments_json,
                    reactions_json = excluded.reactions_json,
                    mentions_json = excluded.mentions_json,
                    is_pinned = excluded.is_pinned
                """,
                (
                    msg_id,
                    channel_id,
                    guild_id,
                    author_id,
                    content,
                    created_at,
                    edited_at,
                    reply_to_id,
                    thread_id,
                    attachments_json,
                    reactions_json,
                    mentions_json,
                    is_pinned,
                ),
            )

    def upsert_messages_batch(self, messages: List[Dict[str, Any]]) -> int:
        """Batch upsert multiple message dicts."""
        count = 0
        for m in messages:
            try:
                self.upsert_message(m)
                count += 1
            except Exception as e:
                # Log or skip individual invalid messages without aborting entire batch
                continue
        return count

    def get_messages_for_channel(
        self,
        channel_id: str,
        since_iso: Optional[str] = None,
        until_iso: Optional[str] = None,
        limit: int = 500,
        order_asc: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fetch messages for a channel with author information joined."""
        query = """
            SELECT 
                m.id, m.channel_id, m.guild_id, m.author_id, m.content, m.created_at, m.edited_at,
                m.reply_to_id, m.thread_id, m.attachments_json, m.reactions_json, m.mentions_json, m.is_pinned,
                u.username, u.global_name, u.is_bot
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.channel_id = ?
        """
        params: List[Any] = [str(channel_id)]

        if since_iso:
            query += " AND m.created_at >= ?"
            params.append(since_iso)

        if until_iso:
            query += " AND m.created_at <= ?"
            params.append(until_iso)

        query += " ORDER BY m.created_at " + ("ASC" if order_asc else "DESC")
        query += " LIMIT ?"
        params.append(limit)

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_messages_for_guild(
        self,
        guild_id: str,
        since_iso: Optional[str] = None,
        until_iso: Optional[str] = None,
        limit: int = 1000,
        order_asc: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fetch messages across all channels for a guild with author and channel information joined."""
        query = """
            SELECT 
                m.id, m.channel_id, m.guild_id, m.author_id, m.content, m.created_at, m.edited_at,
                m.reply_to_id, m.thread_id, m.attachments_json, m.reactions_json, m.mentions_json, m.is_pinned,
                u.username, u.global_name, u.is_bot,
                COALESCE(c.name, m.channel_id) as channel_name
            FROM messages m
            JOIN users u ON m.author_id = u.id
            LEFT JOIN channels c ON m.channel_id = c.id
            WHERE (m.guild_id = ? OR c.guild_id = ?)
        """
        params: List[Any] = [str(guild_id), str(guild_id)]

        if since_iso:
            query += " AND m.created_at >= ?"
            params.append(since_iso)

        if until_iso:
            query += " AND m.created_at <= ?"
            params.append(until_iso)

        query += " ORDER BY m.created_at " + ("ASC" if order_asc else "DESC")
        query += " LIMIT ?"
        params.append(limit)

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_guild(self, guild_id: str) -> Optional[Dict[str, Any]]:
        """Fetch single guild record by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM guilds WHERE id = ?", (str(guild_id),))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_channel(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Fetch single channel record by ID with joined guild name."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT c.*, g.name as guild_name FROM channels c LEFT JOIN guilds g ON c.guild_id = g.id WHERE c.id = ?",
            (str(channel_id),),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_message_by_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT 
                m.id, m.channel_id, m.guild_id, m.author_id, m.content, m.created_at, m.edited_at,
                m.reply_to_id, m.thread_id, m.attachments_json, m.reactions_json, m.mentions_json, m.is_pinned,
                u.username, u.global_name, u.is_bot
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.id = ?
        """
        cursor = self.conn.cursor()
        cursor.execute(query, (str(message_id),))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_thread_context(self, message_id: str, max_parent_depth: int = 5, max_children: int = 15) -> List[Dict[str, Any]]:
        """
        Reconstruct conversation context around a target message:
        1. Traverse up reply_to_id chain to root
        2. Get subsequent replies in channel around that thread
        """
        target = self.get_message_by_id(message_id)
        if not target:
            return []

        # Traverse upwards
        parents = []
        curr = target
        depth = 0
        while curr.get("reply_to_id") and depth < max_parent_depth:
            parent = self.get_message_by_id(curr["reply_to_id"])
            if not parent:
                break
            parents.append(parent)
            curr = parent
            depth += 1

        parents.reverse()  # oldest first

        # Fetch child replies directly answering target or in the immediate aftermath
        channel_id = target["channel_id"]
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT 
                m.id, m.channel_id, m.guild_id, m.author_id, m.content, m.created_at, m.edited_at,
                m.reply_to_id, m.thread_id, m.attachments_json, m.reactions_json, m.mentions_json, m.is_pinned,
                u.username, u.global_name, u.is_bot
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.channel_id = ? AND m.reply_to_id = ?
            ORDER BY m.created_at ASC
            LIMIT ?
            """,
            (channel_id, str(message_id), max_children),
        )
        children = [dict(r) for r in cursor.fetchall()]

        # Combined unique list in chronological order
        all_msgs = {m["id"]: m for m in (parents + [target] + children)}
        sorted_msgs = sorted(all_msgs.values(), key=lambda x: x["created_at"])
        return sorted_msgs

    def list_channels(self, guild_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT c.*, g.name as guild_name FROM channels c LEFT JOIN guilds g ON c.guild_id = g.id"
        params = []
        if guild_id:
            query += " WHERE c.guild_id = ?"
            params.append(str(guild_id))
        query += " ORDER BY c.name ASC"
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def list_guilds(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM guilds ORDER BY name ASC")
        return [dict(row) for row in cursor.fetchall()]

    def save_summary(
        self,
        channel_id: Optional[str] = None,
        window_start: str = "",
        window_end: str = "",
        summary_markdown: str = "",
        channel_name: Optional[str] = None,
        guild_id: Optional[str] = None,
        message_count: int = 0,
        model_used: Optional[str] = None,
    ) -> int:
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO summaries (
                    guild_id, channel_id, channel_name, window_start, window_end,
                    message_count, model_used, summary_markdown, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    guild_id,
                    str(channel_id) if channel_id else None,
                    channel_name,
                    window_start,
                    window_end,
                    message_count,
                    model_used,
                    summary_markdown,
                ),
            )
            return cursor.lastrowid

    def get_latest_summary(self, channel_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM summaries
            WHERE channel_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(channel_id),),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_sync_state(
        self,
        channel_id: str,
        new_count: int = 0,
        oldest_id: Optional[str] = None,
        newest_id: Optional[str] = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sync_state (channel_id, oldest_message_id, newest_message_id, last_sync_time, total_messages_synced)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    oldest_message_id = COALESCE(?, sync_state.oldest_message_id),
                    newest_message_id = COALESCE(?, sync_state.newest_message_id),
                    last_sync_time = CURRENT_TIMESTAMP,
                    total_messages_synced = sync_state.total_messages_synced + excluded.total_messages_synced
                """,
                (str(channel_id), oldest_id, newest_id, new_count, oldest_id, newest_id),
            )

    def get_sync_state(self, channel_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM sync_state WHERE channel_id = ?", (str(channel_id),))
        row = cursor.fetchone()
        return dict(row) if row else None
