"""Message cleaner and normalizer (Deterministic, Zero AI)."""

import json
import re
from typing import Any, Dict, List, Optional, Set


class MessageCleaner:
    def __init__(
        self,
        bot_prefixes: Optional[List[str]] = None,
        prune_repeated: bool = True,
    ):
        self.bot_prefixes = bot_prefixes or ["!", "/", "$", "?", "-", ".", ">"]
        self.prune_repeated = prune_repeated

        # Regex patterns
        self.user_mention_regex = re.compile(r"<@!?(\d+)>")
        self.role_mention_regex = re.compile(r"<@&(\d+)>")
        self.channel_mention_regex = re.compile(r"<#(\d+)>")
        self.custom_emoji_regex = re.compile(r"<a?:([a-zA-Z0-9_]+):\d+>")
        self.url_regex = re.compile(r"https?://[^\s]+")

    def is_bot_command(self, content: str) -> bool:
        """Identify if a message is likely a bot command invocation."""
        stripped = content.strip()
        if not stripped:
            return False
        for prefix in self.bot_prefixes:
            if stripped.startswith(prefix) and len(stripped) > 1 and not stripped[1].isspace():
                return True
        return False

    def clean_text(
        self,
        content: str,
        user_id_map: Optional[Dict[str, str]] = None,
        channel_id_map: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Normalize Discord markup, mentions, and custom emojis to readable text.
        """
        if not content:
            return ""

        text = content

        # Replace custom emojis <:name:12345> with :name:
        text = self.custom_emoji_regex.sub(r":\1:", text)

        # Resolve user mentions <@12345678> -> @Username
        if user_id_map:
            def replace_user(match: re.Match) -> str:
                uid = match.group(1)
                name = user_id_map.get(uid, f"user_{uid}")
                return f"@{name}"
            text = self.user_mention_regex.sub(replace_user, text)
        else:
            text = self.user_mention_regex.sub(r"@user_\1", text)

        # Resolve channel mentions <#12345678> -> #channel_id
        if channel_id_map:
            def replace_chan(match: re.Match) -> str:
                cid = match.group(1)
                cname = channel_id_map.get(cid, cid)
                return f"#{cname}"
            text = self.channel_mention_regex.sub(replace_chan, text)
        else:
            text = self.channel_mention_regex.sub(r"#chan_\1", text)

        # Normalize role mentions <@&12345678> -> @role_id
        text = self.role_mention_regex.sub(r"@role_\1", text)

        # Collapse excess blank lines while preserving paragraphs
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def extract_links(self, content: str) -> List[str]:
        """Extract URLs shared in the message."""
        return self.url_regex.findall(content or "")

    def format_attachments(self, attachments_raw: Any) -> str:
        """Extract attachment summaries (e.g. image name, file link)."""
        if not attachments_raw:
            return ""
        try:
            if isinstance(attachments_raw, str):
                attachments = json.loads(attachments_raw)
            else:
                attachments = attachments_raw

            if not attachments:
                return ""

            parts = []
            for att in attachments:
                filename = att.get("filename", "file")
                content_type = att.get("content_type", "")
                url = att.get("url", "")
                parts.append(f"[File: {filename} ({content_type}) - {url}]")
            return " ".join(parts)
        except Exception:
            return ""

    def filter_messages(
        self,
        messages: List[Dict[str, Any]],
        user_id_map: Optional[Dict[str, str]] = None,
        channel_id_map: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Filter out bot commands, empty noise, and duplicate spam.
        Returns cleaned message dicts with enriched 'clean_content' and 'links'.
        """
        filtered: List[Dict[str, Any]] = []
        seen_recent: Set[str] = set()

        for msg in messages:
            content = msg.get("content", "") or ""
            author_is_bot = bool(msg.get("is_bot", False))

            # Skip bot commands
            if self.is_bot_command(content):
                continue

            # Attachments string
            att_str = self.format_attachments(msg.get("attachments_json"))
            clean_content = self.clean_text(content, user_id_map, channel_id_map)

            # Skip messages with no text and no attachments
            if not clean_content and not att_str:
                continue

            # Simple anti-spam: prune consecutive identical messages from same user
            if self.prune_repeated:
                spam_key = f"{msg.get('author_id')}:{clean_content}"
                if clean_content and spam_key in seen_recent:
                    continue
                seen_recent.add(spam_key)
                if len(seen_recent) > 50:
                    seen_recent.pop()

            msg_copy = dict(msg)
            msg_copy["clean_content"] = clean_content
            if att_str:
                msg_copy["clean_content"] = (clean_content + f" {att_str}").strip()
            msg_copy["links"] = self.extract_links(content)
            filtered.append(msg_copy)

        return filtered
