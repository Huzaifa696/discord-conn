"""Reply Drafter service providing context-aware response variations using Gemini."""

from typing import Any, Dict, List, Optional

from ..config import Config, config
from ..db.repository import Repository
from ..pipeline.context import ContextBuilder
from .gemini import GeminiClient
from .prompts import REPLY_DRAFT_SYSTEM_PROMPT, REPLY_DRAFT_USER_PROMPT_TEMPLATE


class ReplyDrafter:
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
            temperature=0.5,
            max_retries_per_model=self.cfg.ai_max_retries,
            retry_delay_seconds=self.cfg.ai_retry_delay,
        )
        self.context_builder = context_builder or ContextBuilder()

    def draft_reply(
        self,
        channel_id: str,
        message_id: str,
        custom_instruction: str = "Acknowledge and provide a helpful, natural response.",
    ) -> Dict[str, Any]:
        """
        Drafts reply options based on message thread context.
        """
        target_msg = self.repo.get_message_by_id(message_id)
        if not target_msg:
            return {
                "success": False,
                "error": f"Message {message_id} not found in local database. Please sync channel {channel_id} first.",
            }

        thread_messages = self.repo.get_thread_context(message_id)
        channel_name = f"channel-{channel_id}"
        for c in self.repo.list_channels():
            if str(c["id"]) == str(channel_id):
                channel_name = c["name"]
                break

        # Reconstruct focused thread context text deterministically
        context_text = self.context_builder.build_thread_context_text(
            thread_messages=thread_messages,
            target_message_id=message_id,
            channel_name=channel_name,
        )

        prompt = REPLY_DRAFT_USER_PROMPT_TEMPLATE.format(
            context=context_text,
            custom_instruction=custom_instruction,
        )

        raw_drafts = self.gemini.generate(
            prompt=prompt,
            system_instruction=REPLY_DRAFT_SYSTEM_PROMPT,
        )

        return {
            "success": True,
            "target_message": target_msg,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "context_text": context_text,
            "raw_drafts": raw_drafts,
        }
