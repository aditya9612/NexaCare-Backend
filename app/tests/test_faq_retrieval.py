"""
Tests for FAQ RAG Phase 1 — confidence gates, cosine Top-5, selector, facade.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.chatbot.handler import ChatbotHandler
from app.ai.confidence.scorer import ConfidenceAction, ConfidenceScorer
from app.ai.rag.openai_selector import OpenAITop5Selector
from app.ai.embeddings.service import EmbeddingUnavailableError
from app.ai.rag.rag_service import (
    RagFaqResult,
    RagFaqService,
    TRANSFER_PHRASES,
)
from app.ai.rag.retriever import (
    KnowledgeRetriever,
    RetrievedChunk,
    _apply_controlled_tag_boost,
    _entity_match_score,
    _exact_match_score,
    _keyword_score,
    _normalize_query,
    _phrase_match_score,
    _retrieval_query_variants,
    _tag_match_score,
    build_faq_retrieval_embed_text,
    compute_retrieval_confidence,
    fuse_retrieval_score,
)
from app.ai.voice_appointment_assistant.language import detect_language
from app.core.constants import VoiceLanguage
from app.services.faq_retrieval_service import FaqRetrievalService


def test_cosine_similarity_identical_vectors():
    from app.ai.rag.retriever import cosine_similarity

    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    from app.ai.rag.retriever import cosine_similarity

    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_empty():
    from app.ai.rag.retriever import cosine_similarity

    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test_confidence_scorer_bands():
    scorer = ConfidenceScorer(answer_threshold=0.90, clarify_threshold=0.70)
    assert scorer.score(0.95).action == ConfidenceAction.ANSWER
    assert scorer.score(0.80).action == ConfidenceAction.CLARIFY
    assert scorer.score(0.60).action == ConfidenceAction.TRANSFER


def test_confidence_scorer_selector_boost():
    scorer = ConfidenceScorer(answer_threshold=0.90, clarify_threshold=0.70)
    boosted = scorer.score(0.88, selector_agreed=True)
    assert boosted.confidence == pytest.approx(0.93)
    assert boosted.action == ConfidenceAction.ANSWER


def test_keyword_score_exact_question_match():
    label = "[faq:1] Q: What are the hospital visiting hours?\nA: 8-8"
    score = _keyword_score("What are the hospital visiting hours?", "", label)
    assert score >= 0.90


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

    assert result.kind == "invalid_id"


@pytest.mark.asyncio
async def test_openai_top5_selector_no_answer():
    selector = OpenAITop5Selector()

    async def _fake_create(**_kwargs):
        msg = MagicMock()
        msg.choices = [MagicMock(message=MagicMock(content="NO_ANSWER"))]
        return msg

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=_fake_create)

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        with patch("app.ai.rag.openai_selector.settings.OPENAI_API_KEY", "test-key"):
            result = await selector.select("hours?", _chunks(), "en")

    assert result.kind == "no_answer"


@pytest.mark.asyncio
async def test_openai_top5_selector_error_without_api_key():
    selector = OpenAITop5Selector()
    with patch("app.ai.rag.openai_selector.settings.OPENAI_API_KEY", ""):
        result = await selector.select("hours?", _chunks(), "en")
    assert result.kind == "error"


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
    selector = MagicMock()
    selector.select = AsyncMock()
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "hours?", "en")

    assert result.needs_clarification is True
    assert result.should_transfer is False
    assert result.found is True
    assert "visiting hours" in result.answer.lower()
    selector.select.assert_not_awaited()


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
    selector = MagicMock()
    selector.select = AsyncMock()
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "unrelated?", "en")

    assert result.should_transfer is True
    assert result.found is False
    assert result.transfer_reason == "faq_low_confidence"
    selector.select.assert_not_awaited()


@pytest.mark.asyncio
async def test_rag_service_low_confidence_does_not_use_selector():
    db = MagicMock()
    retriever = MagicMock()
    chunks = [
        RetrievedChunk(
            source="faq",
            id=2,
            text="आमचे रुग्णालय सोमवार ते शनिवार, सकाळी 8 ते रात्री 8 वाजेपर्यंत उघडे असते.",
            label="[faq:2] Q: हॉस्पिटल किती वाजता उघडते?\nA: आमचे रुग्णालय सोमवार ते शनिवार, सकाळी 8 ते रात्री 8 वाजेपर्यंत उघडे असते.",
            score=0.548,
        )
    ]
    retriever.retrieve = AsyncMock(return_value=chunks)
    selector = MagicMock()
    selector.select = AsyncMock()
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(
                1, "आपल्या हॉस्पिटल किती वाजता उघडते?", "mr"
            )

    assert result.should_transfer is True
    assert result.found is False
    assert result.transfer_reason == "faq_low_confidence"
    selector.select.assert_not_awaited()


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
    assert result.ai_fallback is False
    selector.select.assert_awaited_once()
    call_args = selector.select.await_args
    assert len(call_args.args[1]) <= 5


@pytest.mark.asyncio
async def test_rag_service_selector_invalid_id_transfers():
    db = MagicMock()
    retriever = MagicMock()
    chunks = _chunks()
    retriever.retrieve = AsyncMock(return_value=chunks)
    selector = MagicMock()
    selector.select = AsyncMock(return_value=MagicMock(kind="invalid_id", text=""))
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "What are your hours?", "en")

    assert result.should_transfer is True
    assert result.transfer_reason == "selector_invalid_id"


@pytest.mark.asyncio
async def test_rag_service_selector_error_transfers():
    db = MagicMock()
    retriever = MagicMock()
    chunks = _chunks()
    retriever.retrieve = AsyncMock(return_value=chunks)
    selector = MagicMock()
    selector.select = AsyncMock(return_value=MagicMock(kind="error", text="api down"))
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "What are your hours?", "en")

    assert result.should_transfer is True
    assert result.transfer_reason == "selector_error"


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
async def test_rag_service_conflict_in_answer_band_clarifies():
    db = MagicMock()
    retriever = MagicMock()
    chunks = [
        RetrievedChunk(
            source="faq",
            id=1,
            text="OPD starts at 9 AM.",
            label="[faq:1] Q: OPD time?\nA: OPD starts at 9 AM.",
            score=0.92,
        ),
        RetrievedChunk(
            source="faq",
            id=2,
            text="OPD starts at 10 AM.",
            label="[faq:2] Q: OPD time?\nA: OPD starts at 10 AM.",
            score=0.91,
        ),
    ]
    retriever.retrieve = AsyncMock(return_value=chunks)
    selector = MagicMock()
    selector.select = AsyncMock()
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "What time does OPD start?", "en")

    assert result.needs_clarification is True
    assert result.should_transfer is False
    selector.select.assert_not_awaited()


@pytest.mark.asyncio
async def test_rag_service_language_clarify_phrases():
    db = MagicMock()
    retriever = MagicMock()
    chunks = [
        RetrievedChunk(
            source="faq",
            id=1,
            text="8-8",
            label="[faq:1] Q: वेळ?\nA: 8-8",
            score=0.80,
        )
    ]
    retriever.retrieve = AsyncMock(return_value=chunks)
    selector = MagicMock()
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result_hi = await svc.answer(1, "samay?", "hi")
            result_mr = await svc.answer(1, "vel?", "mr")

    assert result_hi.needs_clarification is True
    assert result_mr.needs_clarification is True
    assert "topics" not in result_hi.answer
    assert "विचारत" in result_mr.answer or "वेळ" in result_mr.answer


@pytest.mark.asyncio
async def test_retriever_scopes_by_hospital_id():
    db = MagicMock()
    retriever = KnowledgeRetriever(db)
    retriever.faq_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.policy_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.doc_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.store = MagicMock()
    retriever.store.list_active_vectors = AsyncMock(return_value=[])
    retriever.embedder = MagicMock()
    retriever.embedder.embed_text = AsyncMock(return_value=[1.0, 0.0])

    await retriever.retrieve(7, "OPD time?", "en", top_k=5)

    faq_calls = retriever.faq_repo.list_for_hospital.await_args_list
    assert all(c.args[0] == 7 for c in faq_calls)
    assert any(c.args == (7, "en") for c in faq_calls)
    assert any(c.args == (7, "mr") for c in faq_calls)
    policy_calls = retriever.policy_repo.list_for_hospital.await_args_list
    assert all(c.args[0] == 7 for c in policy_calls)
    assert any(c.args == (7, "en") for c in policy_calls)
    assert any(c.args == (7, "mr") for c in policy_calls)


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
        ai_fallback=False,
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
async def test_faq_retrieval_invalidate_cache():
    svc = FaqRetrievalService(MagicMock())
    with patch("app.services.faq_retrieval_service.cache_delete", new=AsyncMock()) as delete:
        with patch(
            "app.services.faq_retrieval_service.cache_delete_pattern",
            new=AsyncMock(),
        ) as delete_pattern:
            with patch(
                "app.services.faq_retrieval_service.RagFaqService.invalidate_query_cache",
                new=AsyncMock(),
            ) as invalidate_query:
                with patch(
                    "app.services.faq_retrieval_service.EmbeddingStore"
                ) as store_cls:
                    store_cls.return_value.invalidate_vector_cache = AsyncMock()
                    await svc.invalidate_cache(3)

    assert delete.await_count == 9
    delete_pattern.assert_awaited()
    invalidate_query.assert_awaited_once_with(3)


@pytest.mark.asyncio
async def test_chat_handler_faq_uses_rag_not_generate_response():
    db = MagicMock()
    handler = ChatbotHandler(db)
    session = MagicMock()
    session.session_id = "chat-1"
    fake = MagicMock(
        answer="OPD starts at 9 AM.",
        confidence=0.95,
        source="faq",
        should_transfer=False,
        needs_clarification=False,
        transfer_reason="",
        faq_hit=True,
    )
    handler.faq_service.answer = AsyncMock(return_value=fake)

    with patch("app.ai.chatbot.handler.llm_service.generate_response", new=AsyncMock()) as gen:
        result = await handler.respond(
            session,
            "What time does OPD start?",
            language="en",
            intent_name="faq",
            hospital_id=1,
        )

    assert result["response_text"] == "OPD starts at 9 AM."
    assert result["source"] == "faq"
    handler.faq_service.answer.assert_awaited_once_with(
        1, "What time does OPD start?", "en", session_id="chat-1"
    )
    gen.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_handler_faq_missing_hospital_transfers():
    db = MagicMock()
    handler = ChatbotHandler(db)
    session = MagicMock()
    session.session_id = "chat-1"
    handler.faq_service.answer = AsyncMock()

    with patch("app.ai.chatbot.handler.llm_service.generate_response", new=AsyncMock()) as gen:
        result = await handler.respond(
            session,
            "What time does OPD start?",
            language="en",
            intent_name="faq",
            hospital_id=None,
        )

    assert result["should_transfer"] is True
    assert result["response_text"] == TRANSFER_PHRASES["en"]
    handler.faq_service.answer.assert_not_awaited()
    gen.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_handler_faq_medical_advice_transfers():
    db = MagicMock()
    handler = ChatbotHandler(db)
    session = MagicMock()
    session.session_id = "chat-1"

    with patch("app.ai.chatbot.handler.llm_service.generate_response", new=AsyncMock()) as gen:
        result = await handler.respond(
            session,
            "Which medicine should I take for fever?",
            language="en",
            intent_name="faq",
            hospital_id=1,
        )

    assert result["should_transfer"] is True
    gen.assert_not_awaited()


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


# --- Marathi-first retrieval normalization ---


@pytest.mark.parametrize(
    ("roman", "expected_fragment"),
    [
        ("OPD kiti vajta suru hote?", "OPD किती वाजता सुरू होते"),
        ("doctor udya available aahet ka?", "doctor उद्या available आहेत का"),
        ("cashless insurance aahe ka?", "cashless insurance आहे का"),
        ("Sunday la hospital open aahe ka?", "Sunday ला hospital open आहे का"),
        ("ambulance number kay aahe?", "ambulance number काय आहे"),
    ],
)
def test_roman_marathi_normalization_matches_native_concepts(roman, expected_fragment):
    normalized = _normalize_query(roman)
    assert expected_fragment.lower() in normalized.lower()


def test_code_mixed_marathi_preserves_entities():
    normalized = _normalize_query("Doctor Patil udya available aahet ka?")
    assert "Doctor" in normalized
    assert "Patil" in normalized
    assert "available" in normalized
    assert "उद्या" in normalized
    assert "आहेत" in normalized


def test_code_mixed_marathi_english_hospital_terms():
    normalized = _normalize_query("OPD chi timing kay aahe?")
    assert "OPD" in normalized
    assert "timing" in normalized
    assert "काय" in normalized
    assert "आहे" in normalized


def test_native_marathi_query_unchanged_semantics():
    native = "OPD किती वाजता सुरू होते?"
    normalized = _normalize_query(native)
    assert "किती" in normalized
    assert "वाजता" in normalized
    assert "OPD" in normalized


def test_colloquial_short_marathi_normalization():
    normalized = _normalize_query("parking aahe ka?")
    assert "parking" in normalized
    assert "आहे का" in normalized


def test_keyword_score_roman_marathi_against_devanagari_faq():
    label = "[faq:1] Q: OPD किती वाजता सुरू होते?\nA: आमची OPD सकाळी ९ वाजता सुरू होते."
    roman_query = _normalize_query("OPD kiti vajta suru hote?")
    score = _keyword_score(roman_query, "", label)
    assert score >= 0.85


def test_fusion_keyword_only_cannot_reach_answer_band():
    fused = fuse_retrieval_score(cosine=0.10, keyword=0.95, source="faq")
    assert fused < 0.70


def test_fusion_semantic_plus_keyword_can_reach_answer_band():
    fused = fuse_retrieval_score(cosine=0.88, keyword=0.95, source="faq")
    assert fused >= 0.90


def test_fusion_weak_semantic_cannot_reach_answer_band_without_deterministic():
    fused = fuse_retrieval_score(cosine=0.45, keyword=0.95, source="faq")
    assert fused < 0.90


def test_fusion_weak_semantic_with_exact_match_reaches_answer_band():
    result = compute_retrieval_confidence(
        semantic=0.429,
        keyword=0.93,
        tag=0.95,
        entity=0.84,
        language=1.0,
        authority=1.0,
        exact_match=0.96,
        phrase_match=0.92,
        source="faq",
    )
    assert result.fused >= 0.90
    assert result.decision_reason == "strong_deterministic_match"
    assert ConfidenceScorer().score(result.fused).action == ConfidenceAction.ANSWER


def test_production_opd_failure_case_multi_signal_agreement():
    """Regression: strong keyword/tag/entity must reach ANSWER despite weak semantic."""
    result = compute_retrieval_confidence(
        semantic=0.429,
        keyword=0.93,
        tag=0.95,
        entity=0.84,
        language=1.0,
        authority=0.02,
        exact_match=0.42,
        phrase_match=0.72,
        source="faq",
    )
    assert result.fused >= 0.90
    assert result.decision_reason == "multi_signal_agreement"
    assert ConfidenceScorer().score(result.fused).action == ConfidenceAction.ANSWER


def test_stt_opidi_variant_entity_alignment():
    """STT spelling ओपिडी must align with OPD entity for retrieval scoring."""
    label = "[faq:1] Q: OPD किती वाजता सुरू होते?\nA: OPD hours."
    embed = build_faq_retrieval_embed_text(
        "OPD किती वाजता सुरू होते?",
        "opd,timing,What time does OPD start",
        "OPD hours.",
    )
    query = _normalize_query("ओपिडी किती वाजता सुरू होते")
    entity = _entity_match_score(query, embed, label)
    assert entity >= 0.80
    result = compute_retrieval_confidence(
        semantic=0.429,
        keyword=_keyword_score(query, embed, label),
        tag=_tag_match_score(query, embed),
        entity=entity,
        language=1.0,
        authority=0.02,
        exact_match=_exact_match_score(query, label),
        phrase_match=_phrase_match_score(query, label, embed),
        source="faq",
    )
    assert result.fused >= 0.90
    assert ConfidenceScorer().score(result.fused).action == ConfidenceAction.ANSWER


def test_vague_timing_query_stays_below_answer_band():
    """Ambiguous timing-only queries must not auto-answer OPD."""
    opd_label = "[faq:1] Q: OPD किती वाजता सुरू होते?\nA: OPD hours."
    opd_embed = build_faq_retrieval_embed_text(
        "OPD किती वाजता सुरू होते?",
        "opd,timing,ओपीडी",
        "OPD hours.",
    )
    query = _normalize_query("किती वाजता उघडते?")
    result = compute_retrieval_confidence(
        semantic=0.55,
        keyword=_keyword_score(query, opd_embed, opd_label),
        tag=_tag_match_score(query, opd_embed),
        entity=_entity_match_score(query, opd_embed, opd_label),
        language=1.0,
        authority=1.0,
        exact_match=_exact_match_score(query, opd_label),
        phrase_match=_phrase_match_score(query, opd_label, opd_embed),
        source="faq",
    )
    assert result.fused < 0.90
    assert result.decision_reason == "entity_mismatch"
    assert ConfidenceScorer().score(result.fused).action != ConfidenceAction.ANSWER


# --- Language detection ---


def test_detect_language_native_marathi():
    assert detect_language("OPD किती वाजता सुरू होते?") == VoiceLanguage.MR


def test_detect_language_roman_marathi():
    assert detect_language("OPD kiti vajta suru hote?") == VoiceLanguage.MR


def test_detect_language_hindi():
    assert detect_language("अस्पताल कब खुलता है?") == VoiceLanguage.HI


def test_detect_language_english():
    assert detect_language("What time does OPD open?") == VoiceLanguage.EN


def test_detect_language_mixed_marathi_dominant():
    assert detect_language("OPD chi timing kay aahe?") == VoiceLanguage.MR


# --- Security / conflict ---


@pytest.mark.asyncio
async def test_cross_hospital_faq_repos_called_with_distinct_ids():
    db = MagicMock()
    retriever = KnowledgeRetriever(db)
    retriever.faq_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.policy_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.doc_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.store = MagicMock()
    retriever.store.list_active_vectors = AsyncMock(return_value=[])
    retriever.embedder = MagicMock()
    retriever.embedder.embed_text = AsyncMock(return_value=[1.0, 0.0])

    await retriever.retrieve(1, "OPD time?", "en", top_k=5)
    await retriever.retrieve(2, "OPD time?", "en", top_k=5)

    hospital_ids = [c.args[0] for c in retriever.faq_repo.list_for_hospital.await_args_list]
    assert 1 in hospital_ids and 2 in hospital_ids
    assert all(h in (1, 2) for h in hospital_ids)


@pytest.mark.asyncio
async def test_en_query_merges_mr_canonical_kb():
    db = MagicMock()
    retriever = KnowledgeRetriever(db)
    mr_item = {
        "source": "faq",
        "id": 104,
        "embedding": [1.0, 0.0],
        "embed_text": "OPD किती वाजता सुरू होते?\nWhat time does OPD start\nanswer",
        "label": "[faq:104] Q: OPD\nA: hours",
        "text": "hours",
    }

    async def _load(hospital_id: int, language: str):
        assert hospital_id == 1
        if language == "mr":
            return [mr_item]
        return []

    retriever._load_enriched_vectors = AsyncMock(side_effect=_load)
    retriever.embedder = MagicMock()
    retriever.embedder.embed_text = AsyncMock(return_value=[1.0, 0.0])

    chunks = await retriever.retrieve(1, "What time does OPD start?", "en", top_k=5)
    assert chunks
    assert chunks[0].id == 104
    loaded_langs = [c.args[1] for c in retriever._load_enriched_vectors.await_args_list]
    assert "en" in loaded_langs
    assert "mr" in loaded_langs


@pytest.mark.asyncio
async def test_hi_query_merges_mr_canonical_kb():
    db = MagicMock()
    retriever = KnowledgeRetriever(db)
    mr_item = {
        "source": "faq",
        "id": 107,
        "embedding": [0.0, 1.0],
        "embed_text": "insurance tags\nCashless insurance hai kya\nanswer",
        "label": "[faq:107] Q: insurance\nA: yes",
        "text": "yes",
    }

    async def _load(hospital_id: int, language: str):
        assert hospital_id == 1
        if language == "mr":
            return [mr_item]
        return []

    retriever._load_enriched_vectors = AsyncMock(side_effect=_load)
    retriever.embedder = MagicMock()
    retriever.embedder.embed_text = AsyncMock(return_value=[0.0, 1.0])

    chunks = await retriever.retrieve(1, "Cashless insurance hai kya?", "hi", top_k=5)
    assert chunks
    assert chunks[0].id == 107
    loaded_langs = [c.args[1] for c in retriever._load_enriched_vectors.await_args_list]
    assert "hi" in loaded_langs
    assert "mr" in loaded_langs


def test_tag_match_score_english_phrase_in_tags():
    from app.ai.rag.retriever import _tag_match_score, build_faq_retrieval_embed_text

    embed = build_faq_retrieval_embed_text(
        "OPD किती वाजता सुरू होते?",
        "What time does OPD start,When does OPD open",
        "Answer text.",
    )
    score = _tag_match_score("What time does OPD start?", embed)
    assert score >= 0.85


def test_controlled_tag_boost_does_not_create_answer_without_semantic():
    from app.ai.rag.retriever import _apply_controlled_tag_boost

    boosted = _apply_controlled_tag_boost(
        fused=0.80, cosine=0.40, keyword=0.95, tag=0.95
    )
    assert boosted == 0.80


def test_controlled_tag_boost_caps_below_answer_band():
    from app.ai.rag.retriever import _apply_controlled_tag_boost

    boosted = _apply_controlled_tag_boost(
        fused=0.86, cosine=0.72, keyword=0.80, tag=0.95
    )
    assert boosted <= 0.89


def test_opd_production_failure_case_reaches_answer_band():
    """Regression: OPD near-exact Marathi match must not transfer on weak semantic."""
    from app.services.canonical_faq_specs import build_canonical_faq_specs

    opd_spec = next(s for s in build_canonical_faq_specs() if s["topic"] == "opd")
    question = opd_spec["question"]
    tags = opd_spec["tags"]
    answer = "आमची OPD Mon-Sat 8:00 AM - 8:00 PM दरम्यान उपलब्ध आहे."
    label = f"[faq:1] Q: {question}\nA: {answer}"
    embed = build_faq_retrieval_embed_text(question, tags, answer)
    queries = [
        "ओपीडी किती वाजता सुरू होते",
        "ओपीडी किती वाजजता ओपन होते",
        "OPD किती वाजता सुरू होते",
        "OPD chi timing kay aahe",
        "ओपीडीची वेळ काय आहे",
        "opd kiti vajta suru hote",
        "What time does OPD start",
        "OPD kab shuru hota hai",
        "ओपीडी कधी सुरू होते",
        "OPD किती वाजता open होते",
    ]
    scorer = ConfidenceScorer()
    for query in queries:
        normalized = _normalize_query(query)
        exact = _exact_match_score(normalized, label)
        phrase = _phrase_match_score(normalized, label, embed)
        kw = _keyword_score(normalized, embed, label)
        tag = _tag_match_score(normalized, embed)
        entity = _entity_match_score(normalized, embed, label)
        result = compute_retrieval_confidence(
            semantic=0.429,
            keyword=kw,
            tag=tag,
            entity=entity,
            language=1.0,
            authority=1.0,
            exact_match=exact,
            phrase_match=phrase,
            source="faq",
        )
        assert result.fused >= 0.90, f"{query!r} fused={result.fused}"
        assert scorer.score(result.fused).action == ConfidenceAction.ANSWER


@pytest.mark.parametrize(
    ("query", "expected_id"),
    [
        ("फार्मसीची वेळ काय आहे", 13),
        ("pharmacy chi timing kay aahe", 13),
        ("What time is pharmacy open", 13),
        ("लॅबची वेळ काय आहे", 14),
        ("lab chi timing kay aahe", 14),
        ("What time is the lab open", 14),
        ("आपत्कालीन विभाग किती वाजता उघडा असतो", 15),
        ("emergency 24 hours aahe ka", 15),
        ("is emergency open 24 hours", 15),
    ],
)
def test_topic_specific_queries_reach_answer_band(query, expected_id):
    specs = {s["topic"]: s for s in __import__(
        "app.services.canonical_faq_specs", fromlist=["build_canonical_faq_specs"]
    ).build_canonical_faq_specs()}
    topic_map = {
        13: "pharmacy",
        14: "laboratory",
        15: "emergency_dept",
    }
    spec = specs[topic_map[expected_id]]
    faq_id = expected_id
    question = spec["question"]
    tags = spec.get("tags", "")
    answer = f"Verified answer for FAQ {faq_id}."
    embed = build_faq_retrieval_embed_text(question, tags, answer)
    label = f"[faq:{faq_id}] Q: {question}\nA: {answer}"
    normalized = _normalize_query(query)
    exact = _exact_match_score(normalized, label)
    phrase = _phrase_match_score(normalized, label, embed)
    kw = _keyword_score(normalized, embed, label)
    tag = _tag_match_score(normalized, embed)
    entity = _entity_match_score(normalized, embed, label)
    result = compute_retrieval_confidence(
        semantic=0.45,
        keyword=kw,
        tag=tag,
        entity=entity,
        language=1.0,
        authority=1.0,
        exact_match=exact,
        phrase_match=phrase,
        source="faq",
    )
    assert result.fused >= 0.90
    assert ConfidenceScorer().score(result.fused).action == ConfidenceAction.ANSWER


@pytest.mark.parametrize(
    "query",
    [
        "फार्मसी किती वाजता उघडते?",
        "लॅब किती वाजता उघडते?",
        "बिलिंग किती वाजता बंद होते?",
        "इमर्जन्सी किती वाजता सुरू असते?",
        "अॅम्ब्युलन्स कधी मिळते?",
        "डॉक्टर उद्या उपलब्ध आहेत का?",
        "doctor उद्या available आहेत का",
        "pharmacy timing",
        "lab timing",
        "billing timing",
        "insurance available",
        "ambulance number",
    ],
)
def test_opd_negative_queries_do_not_match_opd_faq(query):
    opd_label = "[faq:1] Q: OPD किती वाजता सुरू होते?\nA: OPD hours answer."
    opd_embed = build_faq_retrieval_embed_text(
        "OPD किती वाजता सुरू होते?",
        "opd,timing,ओपीडी",
        "OPD hours answer.",
    )
    normalized = _normalize_query(query)
    entity = _entity_match_score(normalized, opd_embed, opd_label)
    result = compute_retrieval_confidence(
        semantic=0.55,
        keyword=_keyword_score(normalized, opd_embed, opd_label),
        tag=_tag_match_score(normalized, opd_embed),
        entity=entity,
        language=1.0,
        authority=1.0,
        exact_match=_exact_match_score(normalized, opd_label),
        phrase_match=_phrase_match_score(normalized, opd_label, opd_embed),
        source="faq",
    )
    assert result.fused < 0.90, f"{query!r} wrongly reached answer band: {result.fused}"
    assert ConfidenceScorer().score(result.fused).action != ConfidenceAction.ANSWER


def _sunday_opd_faq_16_fixtures():
    """FAQ ID 16 — Sunday OPD availability (production KB row)."""
    question = "रविवारी OPD सुरू असते का?"
    answer = "रविवारी OPD उपलब्धतेसाठी कृपया रिसेप्शनशी संपर्क साधा."
    tags = (
        "sunday opd, ravivari opd aste ka, ravivari hospital open aste ka, "
        "Ravivar ko OPD hota hai kya, Sunday OPD, Sunday hospital timing, "
        "OPD Sunday, Sunday hospital timing, रविवारी ओपीडी, रविवार OPD, "
        "रविवारी डॉक्टर उपलब्ध आहेत का"
    )
    faq_id = 16
    label = f"[faq:{faq_id}] Q: {question}\nA: {answer}"
    embed = build_faq_retrieval_embed_text(question, tags, answer)
    return faq_id, question, tags, answer, label, embed


def _general_opd_faq_1_fixture():
    from app.services.canonical_faq_specs import build_canonical_faq_specs

    opd_spec = next(s for s in build_canonical_faq_specs() if s["topic"] == "opd")
    question = opd_spec["question"]
    tags = opd_spec["tags"]
    answer = opd_spec["answer"]
    faq_id = 1
    label = f"[faq:{faq_id}] Q: {question}\nA: {answer}"
    embed = build_faq_retrieval_embed_text(question, tags, answer)
    return faq_id, question, tags, answer, label, embed


def _score_sunday_opd_candidate(
    query: str,
    *,
    faq_id: int,
    label: str,
    embed: str,
    semantic: float = 0.45,
) -> tuple[float, ConfidenceAction]:
    from app.ai.rag.retriever import _apply_sunday_opd_availability_adjustment

    normalized = _normalize_query(query)
    result = compute_retrieval_confidence(
        semantic=semantic,
        keyword=_keyword_score(normalized, embed, label),
        tag=_tag_match_score(normalized, embed),
        entity=_entity_match_score(normalized, embed, label),
        language=1.0,
        authority=1.0,
        exact_match=_exact_match_score(normalized, label),
        phrase_match=_phrase_match_score(normalized, label, embed),
        source="faq",
    )
    fused, _ = _apply_sunday_opd_availability_adjustment(
        result.fused,
        query=normalized,
        label=label,
        embed_text=embed,
        decision_reason=result.decision_reason,
    )
    return fused, ConfidenceScorer().score(fused).action


def _rank_sunday_opd_faqs(query: str, semantic: float = 0.45) -> list[tuple[int, float, ConfidenceAction]]:
    faq16 = _sunday_opd_faq_16_fixtures()
    faq1 = _general_opd_faq_1_fixture()
    ranked: list[tuple[int, float, ConfidenceAction]] = []
    for faq_id, _question, _tags, _answer, label, embed in (faq1, faq16):
        fused, action = _score_sunday_opd_candidate(
            query, faq_id=faq_id, label=label, embed=embed, semantic=semantic
        )
        ranked.append((faq_id, fused, action))
    ranked.sort(key=lambda row: (row[1], row[0]), reverse=True)
    return ranked


@pytest.mark.parametrize(
    "query",
    [
        "रविवारी OPD सुरू असते का?",
        "रविवारी OPD सुरू आहे का?",
        "रविवारी ओपीडी सुरू आहे का?",
        "रविवारला OPD सुरू असते का?",
        "रविवारी OPD चालू आहे का?",
        "Sunday ला OPD open आहे का?",
        "Ravivari OPD suru ahe ka?",
    ],
)
def test_sunday_opd_positive_queries_answer_faq_16(query):
    """Sunday OPD availability queries must rank FAQ 16 first with ANSWER confidence."""
    ranked = _rank_sunday_opd_faqs(query)
    top_id, top_fused, top_action = ranked[0]
    assert top_id == 16, f"{query!r} top candidate was FAQ {top_id}: {ranked}"
    assert top_fused >= 0.90
    assert top_action == ConfidenceAction.ANSWER


@pytest.mark.parametrize(
    "query",
    [
        "रविवारी फार्मसी सुरू आहे का?",
        "रविवारी लॅब सुरू आहे का?",
        "रविवारी बिलिंग सुरू आहे का?",
        "रविवारी इमर्जन्सी सुरू आहे का?",
        "रविवारी डॉक्टर उपलब्ध आहेत का?",
    ],
)
def test_sunday_opd_negative_queries_do_not_answer_faq_16(query):
    """Non-OPD Sunday queries must not answer FAQ 16."""
    _faq_id, _question, _tags, _answer, label, embed = _sunday_opd_faq_16_fixtures()
    fused, action = _score_sunday_opd_candidate(
        query, faq_id=16, label=label, embed=embed
    )
    assert fused < 0.90, f"{query!r} wrongly reached answer band for FAQ 16: {fused}"
    assert action != ConfidenceAction.ANSWER


def test_sunday_opd_pipeline_trace_regression():
    """Regression trace for रविवारी OPD सुरू आहे का? — FAQ 16 must reach ANSWER."""
    from app.ai.rag.retriever import (
        _entity_group_ids,
        _retrieval_query_variants,
        _retrieval_tokens,
    )

    query = "रविवारी OPD सुरू आहे का?"
    normalized = _normalize_query(query)
    variants = _retrieval_query_variants(normalized)
    tokens = _retrieval_tokens(query)
    entities = _entity_group_ids(tokens)

    _faq_id, question, _tags, _answer, label, embed = _sunday_opd_faq_16_fixtures()
    fused, action = _score_sunday_opd_candidate(
        query, faq_id=16, label=label, embed=embed
    )

    assert normalized == "रविवारी OPD सुरू आहे का?"
    assert variants == ["रविवारी OPD सुरू आहे का?"]
    assert "opd" in tokens
    assert "रविवारी" in tokens or "रविवार" in tokens
    assert 0 in entities  # OPD entity group
    assert fused >= 0.90
    assert action == ConfidenceAction.ANSWER
    assert question.startswith("रविवारी OPD")


@pytest.mark.asyncio
async def test_rag_service_authoritative_faq_wins_over_policy_conflict():
    db = MagicMock()
    retriever = MagicMock()
    chunks = [
        RetrievedChunk(
            source="faq",
            id=1,
            text="OPD starts at 9 AM.",
            label="[faq:1] Q: OPD time?\nA: OPD starts at 9 AM.",
            score=0.92,
        ),
        RetrievedChunk(
            source="policy",
            id=2,
            text="OPD starts at 10 AM.",
            label="[policy:2] Title: OPD Policy\nBody: OPD starts at 10 AM.",
            score=0.91,
        ),
    ]
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
            result = await svc.answer(1, "What time does OPD start?", "en")

    assert result.found is True
    assert result.answer == "OPD starts at 9 AM."
    selector.select.assert_awaited_once()


@pytest.mark.asyncio
async def test_rag_service_same_source_conflict_clarifies_not_guess():
    db = MagicMock()
    retriever = MagicMock()
    chunks = [
        RetrievedChunk(
            source="faq",
            id=1,
            text="OPD starts at 9 AM.",
            label="[faq:1] Q: OPD?\nA: OPD starts at 9 AM.",
            score=0.92,
        ),
        RetrievedChunk(
            source="faq",
            id=2,
            text="OPD starts at 10 AM.",
            label="[faq:2] Q: OPD?\nA: OPD starts at 10 AM.",
            score=0.91,
        ),
    ]
    retriever.retrieve = AsyncMock(return_value=chunks)
    selector = MagicMock()
    selector.select = AsyncMock()
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "OPD time?", "en")

    assert result.needs_clarification is True
    assert result.found is True
    selector.select.assert_not_awaited()


@pytest.mark.asyncio
async def test_rag_service_unknown_question_transfers():
    db = MagicMock()
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[])
    selector = MagicMock()
    selector.select = AsyncMock()
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "quantum flux capacitor warranty?", "en")

    assert result.should_transfer is True
    assert result.found is False
    selector.select.assert_not_awaited()


@pytest.mark.asyncio
async def test_rag_service_selector_no_answer_transfers():
    db = MagicMock()
    retriever = MagicMock()
    chunks = _chunks()
    retriever.retrieve = AsyncMock(return_value=chunks)
    selector = MagicMock()
    selector.select = AsyncMock(return_value=MagicMock(kind="no_answer", text=""))
    svc = RagFaqService(db, retriever=retriever, selector=selector, memory=MagicMock())
    svc.memory.update = AsyncMock()

    with patch("app.ai.rag.rag_service.cache_get", new=AsyncMock(return_value=None)):
        with patch("app.ai.rag.rag_service.cache_set", new=AsyncMock(return_value=True)):
            result = await svc.answer(1, "What are your hours?", "en")

    assert result.should_transfer is True
    assert result.transfer_reason == "faq_no_match"


def test_medical_advice_non_faq_question_still_faq_safe():
    from app.services.medical_safety_guard import MedicalSafetyGuard

    assert MedicalSafetyGuard.check("Which medicine for fever?", "en").is_medical_advice is True
    assert MedicalSafetyGuard.check("OPD kiti vajta suru hote?", "mr").is_medical_advice is False


# --- Evaluation matrix (mock KB, retrieval recall) ---

def _priority_mock_kb() -> list[dict]:
    """Realistic multilingual priority FAQ fixture for offline retrieval eval."""
    from app.services.canonical_faq_specs import build_canonical_faq_specs

    entries = []
    for spec in build_canonical_faq_specs():
        faq_id = TOPIC_TO_MOCK_ID.get(spec["topic"])
        if faq_id is None:
            continue
        question = spec["question"]
        tags = spec.get("tags", "")
        answer = f"Verified answer for FAQ {faq_id} ({spec['topic']})."
        embed = build_faq_retrieval_embed_text(question, tags, answer)
        label = f"[faq:{faq_id}] Q: {question}\nA: {answer}"
        entries.append(
            {"id": faq_id, "embed_text": embed, "label": label, "question": question, "tags": tags}
        )
    return entries


def _rank_mock_kb(query: str, semantic: float = 0.72) -> list[tuple[int, float]]:
    normalized = _normalize_query(query)
    variants = _retrieval_query_variants(normalized)
    ranked: list[tuple[int, float, float, float, float, float]] = []
    for entry in _priority_mock_kb():
        kw = max(_keyword_score(form, entry["embed_text"], entry["label"]) for form in variants)
        tag = max(_tag_match_score(form, entry["embed_text"]) for form in variants)
        entity = max(
            _entity_match_score(form, entry["embed_text"], entry["label"])
            for form in variants
        )
        exact = max(_exact_match_score(form, entry["label"]) for form in variants)
        phrase = max(
            _phrase_match_score(form, entry["label"], entry["embed_text"])
            for form in variants
        )
        result = compute_retrieval_confidence(
            semantic=semantic,
            keyword=kw,
            tag=tag,
            entity=entity,
            language=1.0,
            authority=1.0,
            exact_match=exact,
            phrase_match=phrase,
            source="faq",
        )
        ranked.append((entry["id"], result.fused, exact, phrase, entity, kw))
    ranked.sort(key=lambda x: (x[1], x[2], x[3], x[4], x[5]), reverse=True)
    return [(r[0], r[1]) for r in ranked]


def _recall_at_k(ranked_ids: list[int], expected_id: int, k: int) -> float:
    return 1.0 if expected_id in ranked_ids[:k] else 0.0


def _compute_eval_metrics(cases: list[tuple[str, int]]) -> dict[str, float]:
    recalls = {5: [], 10: [], 15: []}
    hits = []
    mrr_vals = []
    for query, expected_id in cases:
        ranked = _rank_mock_kb(query)
        ids = [r[0] for r in ranked]
        for k in recalls:
            recalls[k].append(_recall_at_k(ids, expected_id, k))
        hits.append(1.0 if ids and ids[0] == expected_id else 0.0)
        mrr = 0.0
        for idx, fid in enumerate(ids, start=1):
            if fid == expected_id:
                mrr = 1.0 / idx
                break
        mrr_vals.append(mrr)
    n = len(cases)
    return {
        "recall_at_5": sum(recalls[5]) / n,
        "recall_at_10": sum(recalls[10]) / n,
        "recall_at_15": sum(recalls[15]) / n,
        "hit_at_1": sum(hits) / n,
        "mrr": sum(mrr_vals) / n,
        "sample_size": n,
    }


from app.tests.faq_eval_dataset import (
    ALL_EVAL_CASES,
    NEGATIVE_EVAL_QUERIES,
    POSITIVE_EVAL_CASES,
    TOPIC_TO_MOCK_ID,
)


@pytest.mark.parametrize(("query", "expected_id"), ALL_EVAL_CASES)
def test_eval_matrix_recall_at_15(query, expected_id):
    ranked = _rank_mock_kb(query)
    ids = [r[0] for r in ranked]
    assert expected_id in ids[:15], f"FAQ {expected_id} not in Top-15 for {query!r}"


def test_eval_matrix_aggregate_metrics():
    metrics = _compute_eval_metrics(ALL_EVAL_CASES)
    assert metrics["sample_size"] == len(ALL_EVAL_CASES)
    assert metrics["sample_size"] >= 100
    assert metrics["recall_at_15"] >= 0.98
    assert metrics["recall_at_5"] >= 0.90
    assert metrics["hit_at_1"] >= 0.95
    assert metrics["mrr"] >= 0.95


def test_eval_dataset_has_minimum_negative_cases():
    assert len(NEGATIVE_EVAL_QUERIES) >= 50


def test_eval_dataset_has_minimum_positive_cases():
    assert len(POSITIVE_EVAL_CASES) >= 100


def test_eval_language_group_coverage():
    groups = {g for _, _, g in POSITIVE_EVAL_CASES}
    assert "marathi" in groups
    assert "roman_marathi" in groups
    assert "english" in groups
    assert "hindi" in groups
    assert "mixed" in groups


@pytest.mark.parametrize("query", NEGATIVE_EVAL_QUERIES)
def test_negative_queries_do_not_force_answer_band(query):
    """Negative queries must not reach ANSWER band via keyword-only fusion."""
    ranked = _rank_mock_kb(query, semantic=0.30)
    top_score = ranked[0][1] if ranked else 0.0
    scorer = ConfidenceScorer()
    assert scorer.score(top_score).action != ConfidenceAction.ANSWER


def test_eval_metrics_by_language_group():
    by_group: dict[str, list[tuple[str, int]]] = {}
    for query, faq_id, group in POSITIVE_EVAL_CASES:
        by_group.setdefault(group, []).append((query, faq_id))
    for group, cases in by_group.items():
        metrics = _compute_eval_metrics(cases)
        assert metrics["recall_at_15"] >= 0.90, f"Low recall for group {group}"


def test_build_faq_retrieval_embed_text_normalizes_question_not_answer():
    embed = build_faq_retrieval_embed_text(
        "OPD kiti vajta suru hote?",
        "opd,timing",
        "Answer stays verbatim Roman: OPD 9 AM.",
    )
    assert "किती" in embed
    assert "Answer stays verbatim Roman: OPD 9 AM." in embed
    assert "kiti vajta" not in embed


def test_retrieval_query_variants_opd_timing():
    normalized = _normalize_query("OPD kiti vajta suru hote?")
    variants = _retrieval_query_variants(normalized)
    assert normalized in variants
    assert len(variants) <= 4
    assert any("timing" in v or "काय" in v for v in variants)


def test_roman_hindi_normalization():
    normalized = _normalize_query("OPD kab shuru hota hai?")
    assert "कब" in normalized or "शुरू" in normalized


def test_roman_marathi_variant_kai_and_availble():
    assert "काय" in _normalize_query("timing kai aahe?")
    assert "available" in _normalize_query("parking availble aahe ka?")


def test_query_cache_key_uses_retrieval_normalization():
    k1 = RagFaqService.query_cache_key(1, "mr", "OPD kiti vajta suru hote?", kb_version=0)
    k2 = RagFaqService.query_cache_key(1, "mr", "OPD किती वाजता सुरू होते?", kb_version=0)
    assert k1 == k2
    k3 = RagFaqService.query_cache_key(1, "mr", "OPD kiti vajta suru hote?", kb_version=1)
    assert k1 != k3


@pytest.mark.asyncio
async def test_diagnose_returns_score_decomposition():
    db = MagicMock()
    retriever = KnowledgeRetriever(db)
    retriever._score_all_items = AsyncMock(
        return_value=[
            {
                "source": "faq",
                "id": 1,
                "text": "OPD 9 AM",
                "label": "[faq:1] Q: OPD\nA: OPD 9 AM",
                "cosine": 0.88,
                "keyword": 0.85,
                "tag": 0.90,
                "entity": 0.90,
                "language": 0.85,
                "authority": 1.0,
                "exact_match": 0.95,
                "phrase_match": 0.90,
                "fused": 0.92,
                "decision_reason": "strong_deterministic_match",
                "normalized_candidate": "opd",
                "candidate_question": "OPD",
                "hospital_id": 1,
                "active": True,
                "deleted": False,
            }
        ]
    )
    diag = await retriever.diagnose(1, "OPD kiti vajta suru hote?", "mr", top_k=5)
    assert diag.normalized_query
    assert diag.candidates[0].semantic_score == pytest.approx(0.88)
    assert diag.candidates[0].keyword_score == pytest.approx(0.85)
    assert diag.candidates[0].tag_score >= 0.0
    assert diag.candidates[0].entity_score == pytest.approx(0.90)
    assert diag.candidates[0].language_score == pytest.approx(0.85)
    assert diag.candidates[0].authority_bonus == pytest.approx(1.0)
    assert diag.candidates[0].exact_match_score == pytest.approx(0.95)
    assert diag.confidence_action == "answer"


@pytest.mark.asyncio
async def test_openai_selector_includes_normalized_question():
    chunks = _chunks()
    selector = OpenAITop5Selector()
    with patch("app.ai.rag.openai_selector.settings") as cfg:
        cfg.OPENAI_API_KEY = "test-key"
        with patch("openai.AsyncOpenAI") as mock_client:
            mock_client.return_value.chat.completions.create = AsyncMock(
                return_value=MagicMock(
                    choices=[MagicMock(message=MagicMock(content="NO_ANSWER"))]
                )
            )
            await selector.select(
                "OPD kiti vajta suru hote?",
                chunks,
                "mr",
                normalized_question="OPD किती वाजता सुरू होते?",
            )
            user_msg = mock_client.return_value.chat.completions.create.await_args.kwargs[
                "messages"
            ][1]["content"]
            assert "Normalized question" in user_msg
            assert "किती" in user_msg


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_hospital_kb_matrix():
    """Optional live KB validation — skipped without DB/API key."""
    import os

    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    try:
        from app.core.database import AsyncSessionLocal
    except Exception:
        pytest.skip("Database not available")

    async with AsyncSessionLocal() as db:
        try:
            retriever = KnowledgeRetriever(db)
            diag = await retriever.diagnose(1, "Is parking available?", "en", top_k=5)
        except Exception as exc:
            pytest.skip(f"Live KB unavailable: {exc}")
        assert diag.candidates is not None
