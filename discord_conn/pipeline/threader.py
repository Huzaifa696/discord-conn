"""Conversation tree reconstruction and temporal clustering (Deterministic, Zero AI)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def parse_iso_datetime(dt_str: str) -> datetime:
    """Parse Discord ISO-8601 timestamp string into timezone-aware datetime."""
    if not dt_str:
        return datetime.now(timezone.utc)
    try:
        # Replace trailing 'Z' with UTC offset
        normalized = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except Exception:
        return datetime.now(timezone.utc)


@dataclass
class MessageNode:
    message: Dict[str, Any]
    replies: List["MessageNode"] = field(default_factory=list)
    depth: int = 0

    @property
    def id(self) -> str:
        return str(self.message.get("id"))

    @property
    def author(self) -> str:
        return str(self.message.get("global_name") or self.message.get("username") or "User")

    @property
    def timestamp(self) -> datetime:
        return parse_iso_datetime(self.message.get("created_at", ""))

    @property
    def content(self) -> str:
        return str(self.message.get("clean_content") or self.message.get("content") or "")


@dataclass
class ConversationSession:
    start_time: datetime
    end_time: datetime
    nodes: List[MessageNode]
    total_messages: int
    participants: List[str]


class ConversationClusterer:
    def __init__(self, session_gap_minutes: int = 30):
        self.session_gap_seconds = session_gap_minutes * 60

    def cluster_into_sessions(self, messages: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        Split chronological message list into temporal bursts (sessions)
        when time gap between consecutive messages exceeds session_gap.
        """
        if not messages:
            return []

        # Sort chronologically
        sorted_msgs = sorted(messages, key=lambda m: parse_iso_datetime(m.get("created_at", "")))

        sessions: List[List[Dict[str, Any]]] = []
        current_session: List[Dict[str, Any]] = [sorted_msgs[0]]

        for i in range(1, len(sorted_msgs)):
            prev_dt = parse_iso_datetime(sorted_msgs[i - 1].get("created_at", ""))
            curr_dt = parse_iso_datetime(sorted_msgs[i].get("created_at", ""))

            delta = (curr_dt - prev_dt).total_seconds()
            if delta > self.session_gap_seconds:
                # Gap exceeded: finish current session and start a new one
                sessions.append(current_session)
                current_session = [sorted_msgs[i]]
            else:
                current_session.append(sorted_msgs[i])

        if current_session:
            sessions.append(current_session)

        return sessions

    def build_trees(self, messages: List[Dict[str, Any]]) -> List[MessageNode]:
        """
        Reconstruct reply trees within a list of messages.
        Messages that reply to another message in this batch become children nodes.
        Independent messages become root nodes.
        """
        if not messages:
            return []

        # Map msg_id -> node
        node_map: Dict[str, MessageNode] = {}
        for m in messages:
            msg_id = str(m.get("id"))
            node_map[msg_id] = MessageNode(message=m)

        roots: List[MessageNode] = []

        for m in messages:
            msg_id = str(m.get("id"))
            node = node_map[msg_id]
            reply_to_id = m.get("reply_to_id")

            if reply_to_id and str(reply_to_id) in node_map:
                parent_node = node_map[str(reply_to_id)]
                node.depth = parent_node.depth + 1
                parent_node.replies.append(node)
            else:
                roots.append(node)

        # Sort roots chronologically
        roots.sort(key=lambda n: n.timestamp)
        return roots

    def process(self, messages: List[Dict[str, Any]]) -> List[ConversationSession]:
        """
        Complete processing: temporal clustering + reply tree building per session.
        """
        raw_sessions = self.cluster_into_sessions(messages)
        conversation_sessions: List[ConversationSession] = []

        for sess_msgs in raw_sessions:
            if not sess_msgs:
                continue

            trees = self.build_trees(sess_msgs)
            start_dt = parse_iso_datetime(sess_msgs[0].get("created_at", ""))
            end_dt = parse_iso_datetime(sess_msgs[-1].get("created_at", ""))

            # Unique participants
            participants = list(dict.fromkeys(
                (m.get("global_name") or m.get("username") or "User") for m in sess_msgs
            ))

            conversation_sessions.append(
                ConversationSession(
                    start_time=start_dt,
                    end_time=end_dt,
                    nodes=trees,
                    total_messages=len(sess_msgs),
                    participants=participants,
                )
            )

        return conversation_sessions
