"""
app/ai/rag — Retrieval-Augmented Generation for hospital FAQ / policies / documents.

Public entry: RagFaqService (called from FaqRetrievalService.answer).

Pipeline: query cache → embed → Top-5 retrieve → confidence gate → OpenAI MATCH
on Top-5 only → FAQ memory + analytics.

Does not modify booking, Twilio webhooks, Gemini, or Phase 6 conversation logic.
"""

from app.ai.rag.analytics import RagAnalytics
from app.ai.rag.openai_selector import OpenAITop5Selector, SelectorResult
from app.ai.rag.rag_service import RagFaqResult, RagFaqService
from app.ai.rag.retriever import KnowledgeRetriever, RetrievedChunk

__all__ = [
    "KnowledgeRetriever",
    "RetrievedChunk",
    "OpenAITop5Selector",
    "SelectorResult",
    "RagFaqService",
    "RagFaqResult",
    "RagAnalytics",
]
