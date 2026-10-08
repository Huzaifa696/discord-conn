"""Google Gemini client for interpretation and summarization."""

import logging
import os
import time
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


class GeminiAPIError(Exception):
    pass


class GeminiClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-3.8-flash",
        fallback_model: str = "gemini-3.7-flash",
        fallback_candidates: Optional[List[str]] = None,
        temperature: float = 0.3,
        max_retries_per_model: int = 2,
        retry_delay_seconds: float = 2.0,
    ):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        self.model_name = model_name
        self.fallback_model = fallback_model
        self.fallback_candidates = fallback_candidates if fallback_candidates is not None else [
            "gemini-3.7-flash",
            "gemini-3.5-flash",
            "gemini-flash-latest",
        ]
        self.temperature = temperature
        self.max_retries_per_model = max_retries_per_model
        self.retry_delay_seconds = retry_delay_seconds
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        if not self.api_key:
            return

        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        except Exception as e:
            logger.warning("Failed to initialize google.genai Client: %s", e)
            self._client = None

    def generate(self, prompt: str, system_instruction: Optional[str] = None, model: Optional[str] = None) -> str:
        """
        Generate content using Google Gemini.
        Falls back to alternative models and retries with exponential backoff on transient errors (503/429).
        """
        if not self.api_key:
            raise GeminiAPIError(
                "GEMINI_API_KEY is not configured. Please set GEMINI_API_KEY in your environment or .env file."
            )

        if not self._client:
            self._init_client()
            if not self._client:
                raise GeminiAPIError("Gemini client initialization failed. Please verify your GEMINI_API_KEY.")

        selected_model = model or self.model_name
        models_to_try: List[str] = [selected_model]
        if self.fallback_model and self.fallback_model not in models_to_try:
            models_to_try.append(self.fallback_model)
        for cand in self.fallback_candidates:
            if cand not in models_to_try:
                models_to_try.append(cand)

        last_error = None
        for m in models_to_try:
            for attempt in range(self.max_retries_per_model + 1):
                try:
                    from google.genai import types

                    config = types.GenerateContentConfig(
                        temperature=self.temperature,
                        system_instruction=system_instruction if system_instruction else None,
                    )

                    response = self._client.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=config,
                    )

                    if response and hasattr(response, "text") and response.text:
                        return response.text
                    elif response and hasattr(response, "candidates") and response.candidates:
                        candidate = response.candidates[0]
                        parts = candidate.content.parts
                        text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
                        if text_parts:
                            return "\n".join(text_parts)

                    raise GeminiAPIError(f"Empty response returned from model {m}.")
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    is_transient = any(
                        code in err_str
                        for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "500", "temporar")
                    )
                    if is_transient and attempt < self.max_retries_per_model:
                        delay = self.retry_delay_seconds * (2 ** attempt)
                        logger.warning(
                            "Model %s experiencing temporary demand spike. Retrying in %.1fs (attempt %d/%d)...",
                            m,
                            delay,
                            attempt + 1,
                            self.max_retries_per_model,
                        )
                        time.sleep(delay)
                        continue

                    # When not transient or retries exhausted on this model, try next model in fallback list
                    logger.warning("Generation with %s failed. Trying fallback model if available...", m)
                    break

        raise GeminiAPIError(f"Gemini API request failed across models {models_to_try}: {last_error}")
