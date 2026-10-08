"""Summarizer service orchestrating context building, Gemini generation, and report persistence."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import Config, config
from ..db.repository import Repository
from ..pipeline.context import ContextBuilder
from .gemini import GeminiClient
from .prompts import (
    SERVER_SUMMARIZE_SYSTEM_PROMPT,
    SERVER_SUMMARIZE_USER_PROMPT_TEMPLATE,
    SUMMARIZE_SYSTEM_PROMPT,
    SUMMARIZE_USER_PROMPT_TEMPLATE,
)


class Summarizer:
    def __init__(
        self,
        repository: Repository,
        gemini_client: Optional[GeminiClient] = None,
        context_builder: Optional[ContextBuilder] = None,
        cfg: Optional[Config] = None,
    ):
        self.repo = repository
        self.cfg = cfg or config
        self.gemini = gemini_client or GeminiClient(
            api_key=self.cfg.gemini_api_key,
            model_name=self.cfg.ai_model,
            fallback_model=self.cfg.ai_fallback_model,
            fallback_candidates=self.cfg.ai_fallback_candidates,
            temperature=self.cfg.ai_temperature,
            max_retries_per_model=self.cfg.ai_max_retries,
            retry_delay_seconds=self.cfg.ai_retry_delay,
        )
        self.context_builder = context_builder or ContextBuilder(
            max_context_tokens=self.cfg.max_context_tokens
        )

    def summarize_channel(
        self,
        channel_id: str,
        since_iso: Optional[str] = None,
        hours_back: Optional[int] = None,
        limit: int = 500,
        all_time: bool = False,
    ) -> Dict[str, Any]:
        """
        Extracts channel messages, builds thread-aware transcript deterministically,
        and invokes Gemini to generate an executive digest.
        """
        # Determine timeframe
        now = datetime.now(timezone.utc)
        start_time_iso = since_iso
        if hours_back and not start_time_iso and not all_time:
            start_dt = now - timedelta(hours=hours_back)
            start_time_iso = start_dt.isoformat()
        elif all_time:
            start_time_iso = None

        # Step 1: Query raw messages from SQLite
        raw_messages = self.repo.get_messages_for_channel(
            channel_id=channel_id,
            since_iso=start_time_iso,
            limit=limit,
            order_asc=True,
        )

        if not raw_messages:
            time_desc = "across all time" if all_time else f"in the past {hours_back} hours" if hours_back else "in the requested window"
            return {
                "success": False,
                "error": f"No messages found for channel {channel_id} {time_desc}. Run 'sync {channel_id}' first to pull messages from Discord.",
                "message_count": 0,
            }

        # Retrieve channel & guild names
        channel_info = None
        channels = self.repo.list_channels()
        for c in channels:
            if str(c["id"]) == str(channel_id):
                channel_info = c
                break

        channel_name = channel_info["name"] if channel_info else f"channel-{channel_id}"
        guild_name = channel_info.get("guild_name") if channel_info else None
        guild_id = channel_info.get("guild_id") if channel_info else None

        # Build name mappings for cleaner
        user_id_map = {m["author_id"]: (m.get("global_name") or m.get("username") or m["author_id"]) for m in raw_messages}

        # Step 2: Build Structured Context (Deterministic, Zero AI)
        context_result = self.context_builder.build_channel_context(
            messages=raw_messages,
            channel_name=channel_name,
            guild_name=guild_name,
            user_id_map=user_id_map,
        )

        transcript = context_result["formatted_text"]

        # Step 3: Invoke Gemini AI for Interpretation
        prompt = SUMMARIZE_USER_PROMPT_TEMPLATE.format(transcript=transcript)
        summary_text = self.gemini.generate(
            prompt=prompt,
            system_instruction=SUMMARIZE_SYSTEM_PROMPT,
        )

        window_start = raw_messages[0].get("created_at") or now.isoformat()
        window_end = raw_messages[-1].get("created_at") or now.isoformat()

        # Step 4: Persist Summary in SQLite
        summary_id = self.repo.save_summary(
            channel_id=channel_id,
            window_start=window_start,
            window_end=window_end,
            summary_markdown=summary_text,
            channel_name=channel_name,
            guild_id=guild_id,
            message_count=len(raw_messages),
            model_used=self.cfg.ai_model,
        )

        # Step 5: Save Markdown Report to Disk
        reports_dir = self.cfg.reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        date_str = now.strftime("%Y-%m-%d_%H%M%S")
        safe_cname = "".join(c for c in channel_name if c.isalnum() or c in ("-", "_"))
        report_file = reports_dir / f"digest_{safe_cname}_{date_str}.md"

        full_report_content = f"""# Digest Report: #{channel_name}
- **Server**: {guild_name or 'Direct / Unknown'}
- **Window**: {window_start} to {window_end}
- **Messages Analyzed**: {len(raw_messages)}
- **Generated At**: {now.isoformat()}
- **Model**: {self.cfg.ai_model}

---

{summary_text}
"""
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(full_report_content)

        return {
            "success": True,
            "summary_id": summary_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "guild_name": guild_name,
            "message_count": len(raw_messages),
            "report_path": str(report_file),
            "summary_markdown": summary_text,
            "window_start": window_start,
            "window_end": window_end,
            "token_estimate": context_result["token_estimate"],
        }

    def summarize_server(
        self,
        guild_id: str,
        since_iso: Optional[str] = None,
        hours_back: Optional[int] = None,
        limit: int = 1000,
        all_time: bool = False,
    ) -> Dict[str, Any]:
        """
        Extracts messages across all synced channels in a server, groups them by channel,
        builds structured transcripts, and invokes Gemini to generate a server-wide digest.
        """
        now = datetime.now(timezone.utc)
        start_time_iso = since_iso
        if hours_back and not start_time_iso and not all_time:
            start_dt = now - timedelta(hours=hours_back)
            start_time_iso = start_dt.isoformat()
        elif all_time:
            start_time_iso = None

        guild_info = self.repo.get_guild(guild_id)
        guild_name = guild_info["name"] if guild_info else f"Server-{guild_id}"

        raw_messages = self.repo.get_messages_for_guild(
            guild_id=guild_id,
            since_iso=start_time_iso,
            limit=limit,
            order_asc=True,
        )

        if not raw_messages:
            time_desc = "across all time" if all_time else f"in the past {hours_back} hours" if hours_back else "in the requested window"
            return {
                "success": False,
                "error": f"No messages found for server '{guild_name}' (ID: {guild_id}) {time_desc}. "
                         f"Please run 'sync-server {guild_id}' or 'sync <CHANNEL_ID>' to pull messages first.",
                "message_count": 0,
            }

        # Group messages by channel
        channel_messages: Dict[str, List[Dict[str, Any]]] = {}
        for m in raw_messages:
            cid = m["channel_id"]
            channel_messages.setdefault(cid, []).append(m)

        user_id_map = {m["author_id"]: (m.get("global_name") or m.get("username") or m["author_id"]) for m in raw_messages}

        channel_sections = []
        for cid, c_msgs in channel_messages.items():
            cname = c_msgs[0].get("channel_name", cid)
            ctx = self.context_builder.build_channel_context(
                messages=c_msgs,
                channel_name=cname,
                guild_name=guild_name,
                user_id_map=user_id_map,
            )
            channel_sections.append(f"### Channel: #{cname} ({len(c_msgs)} messages)\n{ctx['formatted_text']}\n")

        full_transcript = "\n".join(channel_sections)
        token_estimate = self.context_builder.estimate_tokens(full_transcript)

        prompt = SERVER_SUMMARIZE_USER_PROMPT_TEMPLATE.format(
            server_name=guild_name,
            transcript=full_transcript,
        )
        summary_text = self.gemini.generate(
            prompt=prompt,
            system_instruction=SERVER_SUMMARIZE_SYSTEM_PROMPT,
        )

        window_start = raw_messages[0].get("created_at") or now.isoformat()
        window_end = raw_messages[-1].get("created_at") or now.isoformat()

        summary_id = self.repo.save_summary(
            channel_id=None,
            window_start=window_start,
            window_end=window_end,
            summary_markdown=summary_text,
            channel_name=f"All Channels ({len(channel_messages)} channels)",
            guild_id=guild_id,
            message_count=len(raw_messages),
            model_used=self.cfg.ai_model,
        )

        reports_dir = self.cfg.reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        date_str = now.strftime("%Y-%m-%d_%H%M%S")
        safe_gname = "".join(c for c in guild_name if c.isalnum() or c in ("-", "_"))
        report_file = reports_dir / f"digest_server_{safe_gname}_{date_str}.md"

        full_report_content = f"""# Server Digest: {guild_name}
- **Server ID**: {guild_id}
- **Channels Included**: {len(channel_messages)}
- **Window**: {window_start} to {window_end}
- **Total Messages Analyzed**: {len(raw_messages)}
- **Generated At**: {now.isoformat()}
- **Model**: {self.cfg.ai_model}

---

{summary_text}
"""
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(full_report_content)

        return {
            "success": True,
            "summary_id": summary_id,
            "guild_id": guild_id,
            "guild_name": guild_name,
            "channel_count": len(channel_messages),
            "message_count": len(raw_messages),
            "report_path": str(report_file),
            "summary_markdown": summary_text,
            "window_start": window_start,
            "window_end": window_end,
            "token_estimate": token_estimate,
        }
