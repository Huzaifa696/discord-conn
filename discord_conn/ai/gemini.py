"""Google Gemini client for interpretation and summarization."""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class GeminiAPIError(Exception):
    pass


class GeminiClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.5-flash",
        fallback_model: str = "gemini-1.5-flash",
        temperature: float = 0.3,
    ):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        self.model_name = model_name
        self.fallback_model = fallback_model
        self.temperature = temperature
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
        Falls back to alternative model if the primary fails.
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
        models_to_try = [selected_model]
        if self.fallback_model and self.fallback_model != selected_model:
            models_to_try.append(self.fallback_model)

        last_error = None
        for m in models_to_try:
            try:
                # Use google.genai client
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
                    # Extract text from parts
                    candidate = response.candidates[0]
                    parts = candidate.content.parts
                    text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
                    if text_parts:
                        return "\n".join(text_parts)

                raise GeminiAPIError(f"Empty response returned from model {m}.")
            except Exception as e:
                logger.warning("Generation with %s failed: %s. Trying fallback if available...", m, e)
                last_error = e

        raise GeminiAPIError(f"Gemini API request failed across models {models_to_try}: {last_error}")
