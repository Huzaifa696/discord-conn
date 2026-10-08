# Discord Connector & AI Summarizer

A high-performance Discord connector that syncs server channels, cleans message history, and reconstructs conversation reply trees using a **100% deterministic (Zero-AI) pipeline**. Google Gemini is invoked exclusively at the final interpretation stage for executive digests and contextual human-in-the-loop replies.

---

## Architecture Highlights

- **Zero-AI Data Pipeline**: Ingestion, deduplication, SQLite indexing, bot command filtering, mention resolution, and conversation thread reconstruction are done entirely without LLMs, saving tokens and compute.
- **Deep Context Understanding**: Clusters messages into temporal conversation sessions and reconstructs full reply trees (`parent -> child replies`) so the AI sees true conversational structure rather than a flat stream.
- **AI Interpretation Layer**: Uses Google Gemini (`gemini-2.5-flash` / `gemini-1.5-flash`) to generate structured summaries:
  - Executive Takeaways
  - Key Topics & Discussions (referencing specific reply threads)
  - Finalized Decisions & Consensus
  - Action Items & Open Inquiries
  - Shared Links & Resources Index
- **Human-in-the-Loop Replies**: Evaluates thread context and drafts natural replies with selectable styles (Concise, Casual, Detailed). Messages are only sent to Discord after your explicit interactive terminal confirmation.
- **Rate-Limit & Safety Conscious**: Includes request pacing, backoff on HTTP 429, and user-agent emulation.

---

## Table of Contents

- [Quickstart](#quickstart)
- [Prerequisites & Installation](#prerequisites--installation)
- [Configuration](#configuration)
  - [Environment Variables (`.env`)](#environment-variables-env)
  - [Application Settings (`config/config.yaml`)](#application-settings-configconfigyaml)
- [CLI Usage Guide](#cli-usage-guide)
  - [1. Authentication Check (`auth-check`)](#1-authentication-check-auth-check)
  - [2. List Servers (`servers`)](#2-list-servers-servers)
  - [3. List Channels (`channels`)](#3-list-channels-channels)
  - [4. Sync Message History (`sync`)](#4-sync-message-history-sync)
  - [5. View Recent Conversation Flow (`recent`)](#5-view-recent-conversation-flow-recent)
  - [6. Generate AI Executive Summary (`summarize`)](#6-generate-ai-executive-summary-summarize)
  - [7. Draft & Send Replies (`reply`)](#7-draft--send-replies-reply)
  - [8. Run Scheduled Background Daemon (`daemon`)](#8-run-scheduled-background-daemon-daemon)
- [Testing](#testing)
- [Directory Structure](#directory-structure)
- [Security & Best Practices](#security--best-practices)

---

## Quickstart

Get up and running in under two minutes:

```bash
# 1. Clone the repository
git clone https://github.com/Huzaifa696/discord-conn.git
cd discord-conn

# 2. Set up virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Create .env from template and configure your keys
cp config/.env.example .env
# Edit .env with your DISCORD_USER_TOKEN and GEMINI_API_KEY

# 4. Verify connections
python run.py auth-check

# 5. List servers and channels
python run.py servers
python run.py channels <GUILD_ID>

# 6. Sync channel history and generate an executive digest
python run.py sync <CHANNEL_ID> --max-messages 200
python run.py summarize <CHANNEL_ID> --hours 24
```

---

## Prerequisites & Installation

- **Python**: 3.10 or higher
- **Discord User Token**: Required for accessing Discord channels.
- **Google Gemini API Key**: Free API key available at [Google AI Studio](https://aistudio.google.com/).

### Installation Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Huzaifa696/discord-conn.git
   cd discord-conn
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## Configuration

### Environment Variables (`.env`)

Copy the template configuration file:
```bash
cp config/.env.example .env
```

Configure the following variables in `.env`:

| Variable | Description | Default | Required |
|---|---|---|:---:|
| `DISCORD_USER_TOKEN` | Discord user authorization token. | — | **Yes** |
| `GEMINI_API_KEY` | API key from Google AI Studio. | — | **Yes** (for AI features) |
| `DATABASE_PATH` | Path to local SQLite database file. | `data/discord_conn.db` | No |

> [!WARNING]
> Keep your `DISCORD_USER_TOKEN` and `GEMINI_API_KEY` strictly private. Never commit `.env` or share your tokens publicly.

#### How to obtain your Discord User Token
1. Open Discord in your web browser (Chrome/Firefox/Edge).
2. Press `F12` or `Ctrl+Shift+I` (Mac: `Cmd+Opt+I`) to open Developer Tools.
3. Switch to the **Network** tab and filter by `/api`.
4. Click on any channel or message in Discord to generate network activity.
5. Inspect any `v9` or `v10` request (e.g. `messages` or `@me`) and copy the value of the `Authorization` header.

### Application Settings (`config/config.yaml`)

Application parameters can be fine-tuned in `config/config.yaml`:

```yaml
discord:
  api_base_url: "https://discord.com/api/v10"
  request_delay_seconds: 1.0       # Delay between requests to prevent 429 rate limits
  max_messages_per_sync: 200       # Default batch fetch size
  user_agent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

ai:
  model: "gemini-2.5-flash"        # Primary Gemini model
  fallback_model: "gemini-1.5-flash" # Fallback if primary is unavailable
  temperature: 0.3
  max_output_tokens: 4096

pipeline:
  session_gap_minutes: 30          # Inactivity period splitting temporal conversation bursts
  bot_prefixes: ["!", "/", "$", "?", "-", ".", ">"] # Bot command prefixes to filter out
  prune_repeated_messages: true    # Filter repetitive spam
  max_context_tokens: 50000        # Maximum context window packing limit

watched_channels:                  # Channels to monitor automatically via daemon
  - guild_id: "123456789012345678"
    channel_id: "987654321098765432"
    name: "engineering-chat"
    summary_interval_hours: 24

output:
  reports_dir: "reports"
  save_markdown: true
  print_terminal: true
```

---

## CLI Usage Guide

Run all actions via the CLI entry point `run.py`:

```bash
python run.py [COMMAND] [OPTIONS] [ARGUMENTS]
```

### 1. Authentication Check (`auth-check`)

Validates your `DISCORD_USER_TOKEN` against Discord API `@me` and tests the Gemini API connection.

```bash
python run.py auth-check
```

**Output:**
- Shows connected Discord account (display name, username, ID).
- Shows Gemini model status and test response.

---

### 2. List Servers (`servers`)

Fetches all Discord servers (guilds) your account belongs to, displays them in a rich formatted table, and caches them in the local SQLite database.

```bash
python run.py servers
```

**Output:**
```text
┌────────────────────┬─────────────────────────────┬───────┐
│ Server ID          │ Server Name                 │ Owner │
├────────────────────┼─────────────────────────────┼───────┤
│ 112233445566778899 │ Developer Hub               │ No    │
│ 998877665544332211 │ Solana Governance & Research│ Yes   │
└────────────────────┴─────────────────────────────┴───────┘
```

---

### 3. List Channels (`channels`)

Lists all accessible text and forum channels for a given server ID.

```bash
python run.py channels <GUILD_ID>
```

**Example:**
```bash
python run.py channels 112233445566778899
```

**Output:**
```text
┌────────────────────┬──────────────────────┬──────┬───────────────────────────────┐
│ Channel ID         │ Channel Name         │ Type │ Topic                         │
├────────────────────┼──────────────────────┼──────┼───────────────────────────────┤
│ 123456789012345678 │ #announcements       │ Text │ Official project updates      │
│ 234567890123456789 │ #general-discussion  │ Text │ Community chat                │
│ 345678901234567890 │ #dev-questions       │ Text │ Technical help and discussions│
└────────────────────┴──────────────────────┴──────┴───────────────────────────────┘
```

---

### 4. Sync Message History (`sync`)

Fetches recent message history for a channel, runs deterministic cleaning (filtering bot triggers, resolving user mentions, stripping spam), and stores them in SQLite.

```bash
python run.py sync <CHANNEL_ID> [OPTIONS]
```

**Options:**
- `--max-messages`, `-m`: Maximum number of messages to sync (default: `200`).

**Example:**
```bash
# Sync up to 500 messages
python run.py sync 234567890123456789 --max-messages 500
```

---

### 5. View Recent Conversation Flow (`recent`)

Previews recent conversation history from the local SQLite database. It reconstructs conversation trees and groups messages into temporal bursts.

```bash
python run.py recent <CHANNEL_ID> [OPTIONS]
```

**Options:**
- `--limit`, `-n`: Number of messages to display (default: `20`).

**Example:**
```bash
python run.py recent 234567890123456789 --limit 30
```

**Features displayed:**
- Temporal session headers (e.g. `--- [Session: 2026-10-08 14:00 UTC] ---`).
- Reply trees (`[Root Message]` -> `↳ [Reply from Bob]` -> `↳ [Reply from Alice]`).
- Cleaned usernames, stripped noise, and formatted timestamps.

---

### 6. Generate AI Executive Summary (`summarize`)

Synthesizes channel activity using Google Gemini to produce a structured, actionable executive digest.

```bash
python run.py summarize <CHANNEL_ID> [OPTIONS]
```

**Options:**
- `--hours`, `-h`: Number of hours of history to summarize (default: `24`).
- `--limit`, `-l`: Maximum messages to analyze from that timeframe (default: `500`).

**Example:**
```bash
# Summarize the past 48 hours of discussion
python run.py summarize 234567890123456789 --hours 48
```

**Report Sections Included:**
1. **Executive Summary**: High-level snapshot of key themes and milestones.
2. **Key Discussions & Reply Threads**: Chronological breakdown referencing specific participants and reply chains.
3. **Decisions & Consensus**: Agreed resolutions and confirmed outcomes.
4. **Action Items & Open Questions**: Outstanding bugs, tasks, and inquiries awaiting answers.
5. **Shared Links & Resources**: Curated index of GitHub PRs, documentation, and external links.

> [!NOTE]
> Summaries are rendered in terminal with rich Markdown styling and saved to `reports/digest_<channel>_<timestamp>.md`.

---

### 7. Draft & Send Replies (`reply`)

Contextually replies to a specific Discord message using Gemini with human-in-the-loop review.

```bash
python run.py reply <CHANNEL_ID> <MESSAGE_ID> [OPTIONS]
```

**Options:**
- `--text`, `-t`: Direct reply text (bypasses AI drafting; asks for final confirmation).
- `--instruction`, `-i`: Custom prompt guidance for AI draft generation (e.g., `"Politely confirm the bug fix and provide the PR link"`).

#### Interactive Workflow Mode
When run without `--text`, the interactive CLI assistant launches:
1. Reconstructs the full parent-child reply chain leading up to `<MESSAGE_ID>`.
2. Gemini generates an initial contextual draft.
3. Interactive terminal menu options:
   - **Send**: Send the current draft immediately to Discord.
   - **Regenerate**: Request a new draft with custom guidance or alternate style (Concise, Casual, Detailed).
   - **Edit**: Edit the draft in terminal before sending.
   - **Cancel**: Abort without sending.

**Examples:**
```bash
# Interactive mode
python run.py reply 234567890123456789 987654321012345678

# Interactive mode with specific instruction
python run.py reply 234567890123456789 987654321012345678 --instruction "Let them know we are testing the patch on staging"

# Direct mode with terminal confirmation
python run.py reply 234567890123456789 987654321012345678 --text "Fix is deployed on staging. Please re-test!"
```

---

### 8. Run Scheduled Background Daemon (`daemon`)

Runs an automated background scheduler that periodically synchronizes watched channels and generates scheduled digests.

```bash
python run.py daemon [OPTIONS]
```

**Options:**
- `--interval-minutes`, `-i`: Sync and digest interval in minutes (default: `60`).

**Example:**
```bash
python run.py daemon --interval-minutes 120
```

Configure the watched channels list under `watched_channels` in `config/config.yaml`.

---

## Testing

Run the automated test suite covering SQLite database operations, deterministic data cleaning, temporal clustering, reply-tree building, and Gemini mock interfaces:

```bash
# Run tests with Python's built-in unittest framework
python -m unittest discover tests
```

**Test Coverage Highlights:**
- `tests/test_pipeline.py`: Tests for bot prefix stripping, user/channel mention resolution, session clustering, and reply tree hierarchy.
- `tests/test_repository.py`: Tests for SQLite upserts, message deduplication, sync state tracking, and thread querying.
- `tests/test_summarizer_and_api.py`: Tests for Gemini digest formatting, fallback mechanisms, and markdown persistence.

---

## Directory Structure

```text
discord-conn/
├── config/
│   ├── config.yaml              # Channel watch list, AI models, pipeline settings
│   └── .env.example             # Environment variable template
├── discord_conn/
│   ├── ai/
│   │   ├── drafter.py           # Contextual reply assistant
│   │   ├── gemini.py            # Gemini 2.5 Flash / 1.5 Flash client
│   │   ├── prompts.py           # Prompts for digests and replies
│   │   └── summarizer.py        # Channel digest generation & markdown persistence
│   ├── cli/
│   │   ├── interactive.py       # Human-in-the-loop review modal
│   │   └── main.py              # Click commands (sync, summarize, reply, etc.)
│   ├── client/
│   │   └── discord_api.py       # REST API client with rate-limiting & pagination
│   ├── db/
│   │   ├── repository.py        # Database queries & thread traversal
│   │   └── schema.py            # SQLite schema initialization
│   ├── pipeline/
│   │   ├── cleaner.py           # Bot command stripping, mentions, anti-spam
│   │   ├── context.py           # Structured transcript builder with token guard
│   │   └── threader.py          # Reply-tree building & temporal clustering
│   └── scheduler/
│       └── runner.py            # Periodic sync and summarizer runner
├── reports/                     # Output directory for generated markdown digests
├── tests/                       # Unit & integration test suite
├── .gitignore                   # Git ignore rules
├── requirements.txt             # Python dependencies
├── run.py                       # Main CLI entry point
└── README.md                    # Documentation & Usage Guide
```

---

## Security & Best Practices

- **Never Commit Credentials**: `.env` and SQLite files (`data/*.db`) are ignored by default in `.gitignore`.
- **Human-in-the-Loop Safe Guard**: Outgoing Discord messages are never dispatched automatically without explicit terminal review and confirmation.
- **Rate-Limiting**: Built-in request pacing and automatic backoff on HTTP 429 protect your account from throttling.
- **Deterministic Token Efficiency**: Message filtering and conversation tree structuring occur entirely locally before LLM submission, reducing API usage and token costs.
