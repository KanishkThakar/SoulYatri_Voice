"""
SoulYatri Speech — LLM Client (Ollama)
========================================
Async HTTP client for Ollama with streaming chat completions.
Manages SoulYatri persona, conversation history, and streaming output.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import httpx

from ..config import settings
from ..utils.logging_config import get_logger
from ..utils.metrics import llm_ttft, llm_total_latency, llm_requests, errors_total

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# SoulYatri system prompt — warm, empathetic, bilingual assistant
# ---------------------------------------------------------------------------
SOULYATRI_SYSTEM_PROMPT = """\
You are SoulYatri, a warm, empathetic, and emotionally intelligent voice assistant.

Core traits:
- You speak naturally in Hindi, English, or Hinglish (code-switching) depending on what the user prefers.
- You are emotionally aware — you pick up on the user's mood and respond with appropriate warmth, humor, or seriousness.
- You keep responses SHORT and conversational — this is a voice conversation, not a text chat. Aim for 1-3 sentences.
- You use natural filler words and expressions like "hmm", "acha", "I see", "samjha" when appropriate.
- You never sound robotic or overly formal.
- You ask clarifying questions when the user's intent is unclear.
- You are helpful, honest, and safe.

Response guidelines:
- Keep responses under 50 words unless the user explicitly asks for a detailed explanation.
- Use simple, spoken language — avoid jargon, markdown, bullet points, or numbered lists.
- Match the user's language — if they speak Hindi, respond in Hindi. If Hinglish, respond in Hinglish.
- Be conversational, not transactional.
- Show personality — be warm, witty, and human.
"""


@dataclass
class LLMResponse:
    """Result from LLM generation."""

    text: str                  # Full generated text
    model: str                 # Model used
    ttft: float               # Time to first token (seconds)
    total_time: float          # Total generation time (seconds)
    token_count: int           # Approximate token count


class OllamaLLM:
    """Async client for Ollama LLM with streaming support.

    Designed for low-latency voice conversations with streaming
    token output so TTS can begin before generation completes.
    """

    def __init__(self) -> None:
        self._base_url = settings.ollama.base_url
        self._model = settings.ollama.model
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize the HTTP client. Call once at startup."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        logger.info("llm_client_initialized", model=self._model, base_url=self._base_url)

        # Verify Ollama is reachable
        try:
            resp = await self._client.get("/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                model_names = [m["name"] for m in models]
                logger.info("ollama_available", models=model_names)
            else:
                logger.warning("ollama_check_failed", status=resp.status_code)
        except Exception as e:
            logger.warning("ollama_unreachable", error=str(e))

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate_stream(
        self,
        user_message: str,
        conversation_history: list[dict],
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream LLM response tokens.

        Yields individual text chunks as they are generated,
        allowing TTS to start synthesis before the full response is ready.

        Args:
            user_message: The user's transcribed speech.
            conversation_history: Previous conversation turns.
            system_prompt: Optional override for system prompt.

        Yields:
            Text chunks as they stream from the LLM.
        """
        if self._client is None:
            raise RuntimeError("LLM client not initialized. Call initialize() first.")

        llm_requests.inc()
        start = time.perf_counter()
        first_token_time: Optional[float] = None
        token_count = 0

        # Build messages array
        messages = [
            {"role": "system", "content": system_prompt or SOULYATRI_SYSTEM_PROMPT}
        ]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        try:
            async with self._client.stream(
                "POST",
                "/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "num_predict": 150,  # Keep responses short for voice
                    },
                },
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue

                    import json
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if data.get("done"):
                        break

                    content = data.get("message", {}).get("content", "")
                    if content:
                        if first_token_time is None:
                            first_token_time = time.perf_counter()
                            ttft = first_token_time - start
                            llm_ttft.observe(ttft)
                            logger.debug("llm_first_token", ttft=round(ttft, 3))

                        token_count += 1
                        yield content

        except httpx.HTTPStatusError as e:
            errors_total.labels(component="llm", error_type="http_error").inc()
            logger.error("llm_http_error", status=e.response.status_code)
            raise
        except Exception as e:
            errors_total.labels(component="llm", error_type=type(e).__name__).inc()
            logger.error("llm_error", error=str(e))
            raise
        finally:
            total_time = time.perf_counter() - start
            llm_total_latency.observe(total_time)
            logger.info(
                "llm_generation_complete",
                tokens=token_count,
                total_time=round(total_time, 3),
                ttft=round((first_token_time - start) if first_token_time else -1, 3),
            )

    async def generate(
        self,
        user_message: str,
        conversation_history: list[dict],
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Generate a complete LLM response (non-streaming).

        Args:
            user_message: The user's transcribed speech.
            conversation_history: Previous conversation turns.
            system_prompt: Optional override for system prompt.

        Returns:
            LLMResponse with full text and timing info.
        """
        start = time.perf_counter()
        first_token_time: Optional[float] = None
        chunks = []
        token_count = 0

        async for chunk in self.generate_stream(
            user_message, conversation_history, system_prompt
        ):
            if first_token_time is None:
                first_token_time = time.perf_counter()
            chunks.append(chunk)
            token_count += 1

        total_time = time.perf_counter() - start
        full_text = "".join(chunks)

        return LLMResponse(
            text=full_text,
            model=self._model,
            ttft=round((first_token_time - start) if first_token_time else -1, 3),
            total_time=round(total_time, 3),
            token_count=token_count,
        )
