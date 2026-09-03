"""
EmbeddingService — OpenAI text-embedding-3-small client.

Integration points:
- Called by EmbeddingStore.upsert_entry / KnowledgeRetriever (query embed)
- Requires settings.OPENAI_API_KEY; returns empty list on missing key / API error
- Must not be used for booking NLU (Gemini path stays untouched)
"""

from __future__ import annotations

from typing import Sequence

from app.core.config import settings
from app.core.logger import logger


class EmbeddingUnavailableError(Exception):
    """Raised when OpenAI embedding API is unavailable for non-empty input."""


class EmbeddingService:
    """Generate dense vectors via OpenAI embeddings API."""

    def __init__(self, model: str | None = None):
        self.model = model or settings.OPENAI_EMBEDDING_MODEL

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single string. Returns [] for blank input; raises on API failure."""
        vectors = await self.embed_texts([text])
        return vectors[0] if vectors else []

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Batch-embed texts. Blank inputs become []. API/key failures raise."""
        cleaned = [(t or "").strip() for t in texts]
        if not cleaned:
            return []
        needs_embed = [i for i, t in enumerate(cleaned) if t]
        if not needs_embed:
            return [[] for _ in cleaned]
        if not settings.OPENAI_API_KEY:
            logger.warning("EmbeddingService: OPENAI_API_KEY empty — embedding unavailable")
            raise EmbeddingUnavailableError("OPENAI_API_KEY not configured")

        try:
            from openai import AsyncOpenAI
            import time

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            # OpenAI rejects empty strings; use a single space placeholder
            payload = [t if t else " " for t in cleaned]
            
            start_time = time.perf_counter()
            response = await client.embeddings.create(model=self.model, input=payload)
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            total_tokens = getattr(usage, "total_tokens", None) if usage else None
            
            logger.info(
                "faq_ai_openai_usage",
                extra={
                    "event": "faq_ai_openai_usage",
                    "operation": "embedding",
                    "model": self.model,
                    "prompt_tokens": prompt_tokens,
                    "total_tokens": total_tokens,
                    "latency_ms": round(latency_ms, 2),
                    "status": "success",
                }
            )
            
            by_index = {item.index: list(item.embedding) for item in response.data}
            return [by_index[i] for i in range(len(payload))]
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000 if 'start_time' in locals() else None
            
            from openai import RateLimitError, AuthenticationError, APIConnectionError, APITimeoutError, BadRequestError, OpenAIError
            
            error_type = "unexpected_error"
            client_msg = "AI service unavailable"
            
            if isinstance(exc, RateLimitError):
                error_type = "rate_limit"
                client_msg = "temporary AI service limitation"
            elif isinstance(exc, AuthenticationError):
                error_type = "authentication"
                client_msg = "AI service configuration unavailable"
            elif isinstance(exc, APIConnectionError):
                error_type = "connection"
                client_msg = "AI service temporarily unavailable"
            elif isinstance(exc, APITimeoutError):
                error_type = "timeout"
                client_msg = "AI service temporarily unavailable"
            elif isinstance(exc, BadRequestError):
                error_type = "bad_request"
                client_msg = "AI request could not be processed"
            elif isinstance(exc, OpenAIError):
                error_type = "openai_error"
                client_msg = "AI service unavailable"

            logger.warning(
                "EmbeddingService failed [%s]: %s", error_type, type(exc).__name__,
                extra={
                    "event": "faq_ai_openai_error",
                    "operation": "embedding",
                    "model": self.model,
                    "error_type": error_type,
                    "latency_ms": round(latency_ms, 2) if latency_ms else None,
                    "status": "error"
                }
            )
            raise EmbeddingUnavailableError(client_msg) from exc
