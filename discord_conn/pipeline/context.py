"""Structured Context Document Builder for AI consumption (Deterministic, Zero AI)."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .cleaner import MessageCleaner
from .threader import ConversationClusterer, ConversationSession, MessageNode


class ContextBuilder:
    def __init__(
        self,
        cleaner: Optional[MessageCleaner] = None,
        clusterer: Optional[ConversationClusterer] = None,
        max_context_tokens: int = 50000,
    ):
        self.cleaner = cleaner or MessageCleaner()
        self.clusterer = clusterer or ConversationClusterer()
        self.max_context_tokens = max_context_tokens

    def estimate_tokens(self, text: str) -> int:
        """Rough deterministic token estimation (approx 4 chars per token)."""
        return max(1, len(text) // 4)

    def _render_node(self, node: MessageNode, prefix: str = "", is_reply: bool = False, parent_author: str = "") -> List[str]:
        lines = []
        time_str = node.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        reply_indicator = f" (in reply to @{parent_author})" if is_reply and parent_author else ""
        header = f"{prefix}[ID: {node.id} | {time_str}] <{node.author}>{reply_indicator}:"

        content_lines = node.content.splitlines() or [""]
        lines.append(f"{header} {content_lines[0]}")
        for cl in content_lines[1:]:
            lines.append(f"{prefix}  {cl}")

        # Render children replies
        for idx, reply in enumerate(node.replies):
            is_last = (idx == len(node.replies) - 1)
            connector = "  └── " if is_last else "  ├── "
            child_prefix = prefix + ("      " if is_last else "  │   ")
            
            reply_time = reply.timestamp.strftime("%H:%M:%S")
            reply_head = f"{prefix}{connector}[ID: {reply.id} | {reply_time}] <{reply.author}> (reply to @{node.author}):"
            reply_lines = reply.content.splitlines() or [""]
            lines.append(f"{reply_head} {reply_lines[0]}")
            for rl in reply_lines[1:]:
                lines.append(f"{child_prefix}{rl}")

            # Recurse for deeper replies if any
            for deep_reply in reply.replies:
                lines.extend(self._render_node(deep_reply, prefix=child_prefix, is_reply=True, parent_author=reply.author))

        return lines

    def build_channel_context(
        self,
        messages: List[Dict[str, Any]],
        channel_name: str = "unknown-channel",
        guild_name: Optional[str] = None,
        user_id_map: Optional[Dict[str, str]] = None,
        channel_id_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Builds a high-structure transcript from raw database messages.
        Returns a dictionary containing:
        - formatted_text: Complete structured string for LLM prompt
        - session_count: Number of conversation bursts
        - message_count: Total cleaned messages
        - participants: List of active users
        - shared_links: List of unique URLs extracted
        - token_estimate: Estimated token count
        """
        # Step 1: Deterministic filter & clean
        cleaned = self.cleaner.filter_messages(messages, user_id_map, channel_id_map)
        if not cleaned:
            return {
                "formatted_text": f"No messages recorded for #{channel_name}.",
                "session_count": 0,
                "message_count": 0,
                "participants": [],
                "shared_links": [],
                "token_estimate": 0,
            }

        # Collect shared links
        all_links = []
        for m in cleaned:
            all_links.extend(m.get("links", []))
        unique_links = list(dict.fromkeys(all_links))

        # Step 2: Thread & Sessionize
        sessions = self.clusterer.process(cleaned)

        all_participants = list(dict.fromkeys(
            p for s in sessions for p in s.participants
        ))

        # Step 3: Build Markdown Transcript
        doc_parts = []
        server_display = f"Server: {guild_name} | " if guild_name else ""
        doc_parts.append(f"# Conversation Transcript: #{channel_name}")
        doc_parts.append(f"**Context Overview**: {server_display}Total Messages: {len(cleaned)} | Active Participants: {', '.join(all_participants[:15])}")
        doc_parts.append("")

        session_texts = []
        for idx, s in enumerate(sessions, 1):
            s_lines = []
            s_time_start = s.start_time.strftime("%Y-%m-%d %H:%M:%S")
            s_time_end = s.end_time.strftime("%H:%M:%S UTC")
            s_lines.append(f"---")
            s_lines.append(f"### Session {idx}: {s_time_start} - {s_time_end}")
            s_lines.append(f"*Participants*: {', '.join(s.participants)} ({s.total_messages} messages)")
            s_lines.append("")

            for root_node in s.nodes:
                s_lines.extend(self._render_node(root_node))
                s_lines.append("")

            session_texts.append("\n".join(s_lines))

        # Check token budget. If too large, keep the most recent sessions
        combined_sessions_text = "\n\n".join(session_texts)
        if self.estimate_tokens(combined_sessions_text) > self.max_context_tokens:
            # Prune older sessions from the front
            while session_texts and self.estimate_tokens("\n\n".join(session_texts)) > self.max_context_tokens:
                session_texts.pop(0)
            doc_parts.append("*(Note: Earlier sessions truncated to fit token budget)*\n")
            doc_parts.append("\n\n".join(session_texts))
        else:
            doc_parts.append(combined_sessions_text)

        # Append Links index if any exist
        if unique_links:
            doc_parts.append("\n### Shared Resources & Links:")
            for l in unique_links[:20]:
                doc_parts.append(f"- {l}")

        formatted_text = "\n".join(doc_parts)
        token_est = self.estimate_tokens(formatted_text)

        return {
            "formatted_text": formatted_text,
            "session_count": len(sessions),
            "message_count": len(cleaned),
            "participants": all_participants,
            "shared_links": unique_links,
            "token_estimate": token_est,
        }

    def build_thread_context_text(
        self,
        thread_messages: List[Dict[str, Any]],
        target_message_id: str,
        channel_name: str = "channel",
    ) -> str:
        """
        Builds focused thread context string for drafting a reply to a specific message.
        """
        cleaned = self.cleaner.filter_messages(thread_messages)
        if not cleaned:
            return "No thread context available."

        lines = [f"# Thread Context for Message ID {target_message_id} in #{channel_name}:\n"]
        for m in cleaned:
            m_id = str(m.get("id"))
            is_target = (m_id == str(target_message_id))
            target_marker = " [TARGET MESSAGE]" if is_target else ""
            author = m.get("global_name") or m.get("username") or "User"
            t_str = m.get("created_at", "")[:19]
            reply_to = m.get("reply_to_id")
            reply_tag = f" (reply to {reply_to})" if reply_to else ""

            lines.append(f"- [{t_str}] <{author}> (ID: {m_id}){reply_tag}{target_marker}:")
            lines.append(f"  {m.get('clean_content', '')}")

        return "\n".join(lines)
