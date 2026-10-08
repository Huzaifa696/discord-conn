# Discord Connector & AI Summarizer

A high-performance Discord connector that syncs server channels, cleans message history, and reconstructs conversation reply trees using a **100% deterministic (Zero-AI) pipeline**. Google Gemini is invoked exclusively at the final interpretation stage for executive digests and contextual human-in-the-loop replies.

---

## Architecture Highlights

- **Zero-AI Data Pipeline**: Ingestion, deduplication, SQLite indexing, bot command filtering, mention resolution, and conversation thread reconstruction are done entirely without LLMs, saving tokens and compute.
- **Deep Context Understanding**: Clusters messages into temporal conversation sessions and reconstructs full reply trees (`parent -> child replies`) so the AI sees true conversational structure rather than a flat stream.
- **AI Interpretation Layer**: Uses Google Gemini (`gemini-3.8-flash` / `gemini-flash-latest`) to generate structured summaries:
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
    - [How to Obtain Discord User Token](#how-to-obtain-discord-user-token)
    - [How to Obtain Google Gemini API Key](#how-to-obtain-google-gemini-api-key)
  - [Application Settings (`config/config.yaml`)](#application-settings-configconfigyaml)
- [CLI Usage Guide](#cli-usage-guide)
  - [1. Authentication Check (`auth-check`)](#1-authentication-check-auth-check)
  - [2. List Servers (`servers`)](#2-list-servers-servers)
  - [3. List Channels (`channels`)](#3-list-channels-channels)
  - [4. Sync Message History (`sync` / `sync-server`)](#4-sync-message-history-sync--sync-server)
  - [5. View Recent Conversation Flow (`recent`)](#5-view-recent-conversation-flow-recent)
  - [6. Generate AI Executive Summary (`summarize` / `summarize-server`)](#6-generate-ai-executive-summary-summarize--summarize-server)
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
- **Discord User Token**: Required for accessing Discord channels. Obtainable from [Discord Web](https://discord.com/app) (see [instructions below](#how-to-obtain-discord-user-token)).
- **Google Gemini API Key**: Free API key available at [Google AI Studio](https://aistudio.google.com/app/apikey) (see [instructions below](#how-to-obtain-google-gemini-api-key)).

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

#### How to Obtain Discord User Token

A Discord User Token allows the connector to authenticate requests as your account to read channels and post replies.

1. Open **[Discord Web](https://discord.com/app)** ([https://discord.com/app](https://discord.com/app)) in your web browser (Chrome, Firefox, Edge, or Brave) and sign in.
2. Open Developer Tools:
   - **Windows / Linux**: Press `F12` or `Ctrl + Shift + I`
   - **macOS**: Press `Cmd + Option + I`
3. Switch to the **Network** tab in Developer Tools.
4. In the filter box, type `/api` (or `messages`).
5. Click on any channel or message in Discord to generate API traffic.
6. Click on any request in the list (such as `@me` or a `messages` request).
7. Under the **Headers** tab, scroll to **Request Headers**.
8. Find the **`Authorization`** header and copy its value (without quotes).
9. Paste it into your `.env` file:
   ```env
   DISCORD_USER_TOKEN=your_token_here
   ```

> [!CAUTION]
> Your Discord token gives direct access to your account. **Never share it publicly or commit it to a repository.**

#### How to Obtain Google Gemini API Key

The Gemini API key enables AI summarization, thread analysis, and reply drafting.

1. Visit **[Google AI Studio API Keys](https://aistudio.google.com/app/apikey)** ([https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)).
2. Sign in with your Google account.
3. Click **"Create API key"** (or **"Get API key"**).
4. Select an existing project or create a new Google Cloud project.
5. Copy your newly created API key.
6. Paste it into your `.env` file:
   ```env
   GEMINI_API_KEY=your_api_key_here
   ```

> [!TIP]
> Google AI Studio offers a free tier for Gemini models (`gemini-3.8-flash` / `gemini-flash-latest`), which is plenty for daily summaries and chat digests.

### Application Settings (`config/config.yaml`)

Application parameters can be fine-tuned in `config/config.yaml`:

```yaml
discord:
  api_base_url: "https://discord.com/api/v10"
  request_delay_seconds: 1.0       # Delay between requests to prevent 429 rate limits
  max_messages_per_sync: 200       # Default batch fetch size
  user_agent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

ai:
  model: "gemini-3.8-flash"        # Primary Gemini model
  fallback_model: "gemini-flash-latest" # Fallback if primary is unavailable
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

### 4. Sync Message History (`sync` / `sync-server`)

Fetches message history for a channel or an entire server, runs deterministic cleaning (filtering bot triggers, resolving user mentions, stripping spam), and stores them in SQLite.

```bash
# Sync a single channel
python run.py sync <CHANNEL_ID> [OPTIONS]

# Sync multiple active channels across an entire server
python run.py sync-server <GUILD_ID> [OPTIONS]
# or simply:
python run.py sync <GUILD_ID>
```

**Options for `sync`:**
- `--max-messages`, `-m`: Maximum messages to fetch per channel (default: `200`).
- `--channels`, `-c`: Number of top active channels to sync if targeting a server (default: `5`).
- `--server`, `-s`: Force treat the ID as a server (guild) ID.

**Options for `sync-server`:**
- `--channels`, `-c`: Number of top active channels to sync (default: `5`).
- `--max-messages`, `-m`: Maximum messages to sync per channel (default: `100`).
- `--all-channels`: Sync all accessible text channels in the server.

**Examples:**
```bash
# Sync 500 messages from a specific channel
python run.py sync 234567890123456789 --max-messages 500

# Sync the top 5 most active channels in a server
python run.py sync-server 428295358100013066 --channels 5 --max-messages 100
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

### 6. Generate AI Executive Summary (`summarize` / `summarize-server`)

Synthesizes channel or whole-server activity using Google Gemini to produce a structured, actionable executive digest.

```bash
# Summarize a channel or whole server (auto-detected)
python run.py summarize <CHANNEL_OR_SERVER_ID> [OPTIONS]

# Explicit server-wide summarization across all synced channels
python run.py summarize-server <GUILD_ID> [OPTIONS]
```

**Options:**
- `--all`, `-a`: **Summarize the whole channel or server across all time** (no 24-hour restriction).
- `--hours`, `-h`: Number of hours of history to summarize (default: `24`). Pass `0` to summarize all history.
- `--limit`, `-l`: Maximum messages to analyze (default: `500` for channel, `1000` for server).
- `--server`, `-s`: Force treat the target as a server ID.

**Examples:**
```bash
# Summarize the past 24 hours of a channel
python run.py summarize 234567890123456789 --hours 24

# Summarize the WHOLE channel across its entire history
python run.py summarize 234567890123456789 --all

# Summarize the WHOLE server across all synced channels
python run.py summarize 428295358100013066 --all
# or
python run.py summarize-server 428295358100013066 --all
```

**Report Sections Included:**
1. **Executive Summary / Server Overview**: High-level snapshot of key themes and milestones.
2. **Key Discussions / Channel Highlights**: Organized breakdown referencing specific channels, participants, and reply chains.
3. **Decisions & Consensus**: Agreed resolutions and confirmed outcomes.
4. **Action Items & Active Debates**: Outstanding bugs, tasks, and inquiries awaiting answers.
5. **Shared Links & Resources**: Curated index of GitHub PRs, documentation, and external links.

> [!NOTE]
> Summaries are rendered in terminal with rich Markdown styling and saved to `reports/digest_<target>_<timestamp>.md`.

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
