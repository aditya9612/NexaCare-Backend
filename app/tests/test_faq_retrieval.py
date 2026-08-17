"""
Tests for FAQ RAG Phase 1 — confidence gates, cosine Top-5, selector, facade.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.confidence.scorer import ConfidenceAction, ConfidenceScorer
from app.ai.rag.openai_selector import OpenAITop5Selector
from app.ai.embeddings.service import EmbeddingUnavailableError
from app.ai.rag.rag_service import RagFaqResult, RagFaqService
from app.ai.rag.retriever import RetrievedChunk, cosine_similarity
from app.services.faq_retrieval_service import FaqRetrievalService


def test_cosine_similarity_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_empty():
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test_confidence_scorer_bands():
    scorer = ConfidenceScorer(answer_threshold=0.90, clarify_threshold=0.70)
    assert scorer.score(0.95).action == ConfidenceAction.ANSWER
    assert scorer.score(0.80).action == ConfidenceAction.CLARIFY
    assert scorer.score(0.50).action == ConfidenceAction.TRANSFER


def test_confidence_scorer_selector_boost():
    scorer = ConfidenceScorer(answer_threshold=0.90, clarify_threshold=0.70)
    boosted = scorer.score(0.88, selector_agreed=True)
    assert boosted.confidence == pytest.approx(0.93)
    assert boosted.action == ConfidenceAction.ANSWER


def _chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            source="faq",
            id=1,
            text="We are open Monday to Saturday, 8 AM to 8 PM.",
            label="[faq:1] Q: What are the hospital visiting hours?\nA: We are open Monday to Saturday, 8 AM to 8 PM.",
            score=0.95,
        ),
        RetrievedChunk(
            source="policy",
            id=2,
            text="Free parking is available in the basement for all visitors.",
            label="[policy:2] Title: Parking Policy\nCategory: parking\nBody: Free parking is available in the basement for all visitors.",
            score=0.40,
        ),
    ]


@pytest.mark.asyncio
async def test_openai_top5_selector_returns_verbatim_match():
    selector = OpenAITop5Selector()

    async def _fake_create(**_kwargs):
        msg = MagicMock()
        msg.choices = [MagicMock(message=MagicMock(content="MATCH:faq:1"))]
        return msg

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=_fake_create)

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        with patch("app.ai.rag.openai_selector.settings.OPENAI_API_KEY", "test-key"):
            result = await selector.select("What are your hours?", _chunks(), "en")

    assert result.kind == "match"
    assert result.text == "We are open Monday to Saturday, 8 AM to 8 PM."
    assert result.source == "faq"
    assert result.entry_id == 1


@pytest.mark.asyncio
async def test_openai_top5_selector_rejects_id_not_in_top5():
    selector = OpenAITop5Selector()

    async def _fake_create(**_kwargs):
        msg = MagicMock()
        msg.choices = [MagicMock(message=MagicMock(content="MATCH:faq:999"))]
        return msg

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=_fake_create)

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        with patch("app.ai.rag.openai_selector.settings.OPENAI_API_KEY", "test-key"):
            result = await selector.select("hours?", _chunks(), "en")

    assert result.kind == "no_answer"


@pytest.mark.asyncio
async def test_openai_top5_catalog_contains_only_provided_chunks():
    selector = OpenAITop5Selector()
    captured = {}

    async def _fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        msg = MagicMock()
        msg.choices = [MagicMock(message=MagicMock(content="NO_ANSWER"))]
        return msg

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=_fake_create)

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        with patch("app.ai.rag.openai_selector.settings.OPENAI_API_KEY", "test-key"):
            await selector.select("hours?", _chunks()[:1], "en")

    user_msg = captured["messages"][1]["content"]
    assert "[faq:1]" in user_msg
    assert "[policy:2]" not in user_msg


@pytest.mark.asyncio
async def test_rag_service_clarify_band():
    db = MagicMock()
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        return_value=[
            RetrievedChunk(
                source="faq",
                id=1,
                text="Hours answer",
                label="[faq:1] Q: Visiting hours?\nA: Hours answer",
                score=0.80,
            )
        ]
    )
    svc = RagFaqService(db, retriever=retriever, selector=MagicMock(), memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "hours?", "en")

    assert result.needs_clarification is True
    assert result.should_transfer is False
    assert result.found is True
    assert "Visiting hours" in result.answer or "hours" in result.answer.lower()


@pytest.mark.asyncio
async def test_rag_service_transfer_band():
    db = MagicMock()
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        return_value=[
            RetrievedChunk(
                source="faq",
                id=1,
                text="Hours",
                label="[faq:1] Q: Hours\nA: Hours",
                score=0.40,
            )
        ]
    )
    svc = RagFaqService(db, retriever=retriever, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "unrelated?", "en")

    assert result.should_transfer is True
    assert result.found is False


@pytest.mark.asyncio
async def test_rag_service_high_confidence_uses_selector():
    db = MagicMock()
    retriever = MagicMock()
    chunks = _chunks()
    retriever.retrieve = AsyncMock(return_value=chunks)
    selector = MagicMock()
    selector.select = AsyncMock(
        return_value=MagicMock(
            kind="match",
            source="faq",
            entry_id=1,
            text=chunks[0].text,
            clarify_question="",
        )
    )
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "What are your hours?", "en")

    assert result.found is True
    assert result.answer == chunks[0].text
    assert result.ai_fallback is True
    selector.select.assert_awaited_once()
    call_args = selector.select.await_args
    assert len(call_args.args[1]) <= 5


@pytest.mark.asyncio
async def test_rag_service_embedding_failure_not_low_confidence():
    db = MagicMock()
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(side_effect=EmbeddingUnavailableError("403 model access"))
    svc = RagFaqService(db, retriever=retriever, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "hours?", "en")

    assert result.should_transfer is True
    assert result.transfer_reason == "embedding_error"
    assert result.source == "embedding_error"


@pytest.mark.asyncio
async def test_faq_retrieval_transfers_on_medical_advice():
    svc = FaqRetrievalService(MagicMock())
    result = await svc.answer(1, "Which medicine should I take for fever?", "en")
    assert result.should_transfer is True
    assert result.found is False


@pytest.mark.asyncio
async def test_faq_retrieval_delegates_to_rag_without_session_id():
    svc = FaqRetrievalService(MagicMock())
    fake = RagFaqResult(
        found=True,
        answer="We are open Monday to Saturday, 8 AM to 8 PM.",
        source="faq",
        confidence=0.95,
        faq_hit=True,
        ai_fallback=True,
    )
    svc._rag.answer = AsyncMock(return_value=fake)
    result = await svc.answer(1, "hours?", "en")
    assert result.found is True
    assert result.answer == fake.answer
    assert result.needs_clarification is False
    svc._rag.answer.assert_awaited_once_with(1, "hours?", "en", session_id=None)


@pytest.mark.asyncio
async def test_faq_retrieval_passes_session_id():
    svc = FaqRetrievalService(MagicMock())
    svc._rag.answer = AsyncMock(
        return_value=RagFaqResult(found=True, answer="ok", source="faq", confidence=0.95)
    )
    await svc.answer(1, "hours?", "en", session_id="CA123")
    svc._rag.answer.assert_awaited_once_with(1, "hours?", "en", session_id="CA123")


@pytest.mark.asyncio
async def test_faq_memory_update_fields():
    from app.ai.memory.faq_memory import FaqMemory

    mem = FaqMemory()
    with patch(
        "app.ai.memory.faq_memory.cache_get",
        new=AsyncMock(return_value={"question_count": 1, "language": "en"}),
    ):
        with patch("app.ai.memory.faq_memory.cache_set", new=AsyncMock(return_value=True)) as setter:
            state = await mem.update(
                "CA1",
                question="hours?",
                answer="8-8",
                language="hi",
                topic="visiting hours",
            )

    assert state.question_count == 2
    assert state.last_question == "hours?"
    assert state.last_answer == "8-8"
    assert state.language == "hi"
    assert state.last_topic == "visiting hours"
    setter.assert_awaited()
