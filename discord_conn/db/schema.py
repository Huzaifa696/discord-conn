"""SQLite database schema and initialization."""

import sqlite3
from pathlib import Path
from typing import Union

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS guilds (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    guild_id TEXT,
    name TEXT NOT NULL,
    type INTEGER DEFAULT 0,
    topic TEXT,
    last_message_id TEXT,
    last_synced_at TIMESTAMP,
    FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    discriminator TEXT,
    global_name TEXT,
    avatar TEXT,
    is_bot INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    guild_id TEXT,
    author_id TEXT NOT NULL,
    content TEXT,
    created_at TIMESTAMP NOT NULL,
    edited_at TIMESTAMP,
    reply_to_id TEXT,
    thread_id TEXT,
    attachments_json TEXT,
    reactions_json TEXT,
    mentions_json TEXT,
    is_pinned INTEGER DEFAULT 0,
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT,
    channel_id TEXT,
    channel_name TEXT,
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    message_count INTEGER DEFAULT 0,
    model_used TEXT,
    summary_markdown TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_state (
    channel_id TEXT PRIMARY KEY,
    oldest_message_id TEXT,
    newest_message_id TEXT,
    last_sync_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_messages_synced INTEGER DEFAULT 0,
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
);

-- Indices for performance
CREATE INDEX IF NOT EXISTS idx_messages_channel_created ON messages(channel_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_reply_to ON messages(reply_to_id);
CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_author ON messages(author_id);
CREATE INDEX IF NOT EXISTS idx_summaries_channel ON summaries(channel_id, created_at);
CREATE INDEX IF NOT EXISTS idx_summaries_guild ON summaries(guild_id, created_at);
"""


def init_db(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Initialize the SQLite database with required tables and indexes."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    with conn:
        conn.executescript(SCHEMA_SQL)
        # Migrate summaries if channel_id has NOT NULL
        cursor = conn.execute("PRAGMA table_info(summaries)")
        columns = {row["name"]: dict(row) for row in cursor.fetchall()}
        if columns.get("channel_id", {}).get("notnull") == 1:
            conn.execute("ALTER TABLE summaries RENAME TO summaries_old")
            conn.executescript(SCHEMA_SQL)
            conn.execute("""
                INSERT INTO summaries (id, guild_id, channel_id, channel_name, window_start, window_end, message_count, model_used, summary_markdown, created_at)
                SELECT id, guild_id, channel_id, channel_name, window_start, window_end, message_count, model_used, summary_markdown, created_at FROM summaries_old
            """)
            conn.execute("DROP TABLE summaries_old")
    return conn
