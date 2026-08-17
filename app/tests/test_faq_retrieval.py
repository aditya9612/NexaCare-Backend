from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.faq_retrieval_service import FaqRetrievalService


def _service() -> FaqRetrievalService:
    return FaqRetrievalService(MagicMock())


def _snapshot() -> dict:
    return {
        "faqs": [
            {
                "id": 1,
                "question": "What are the hospital visiting hours?",
                "answer": "We are open Monday to Saturday, 8 AM to 8 PM.",
                "tags": "hours,timing,open",
            }
        ],
        "policies": [
            {
                "id": 2,
                "title": "Parking Policy",
                "body": "Free parking is available in the basement for all visitors.",
                "category": "parking",
            }
        ],
        "documents": [
            {
                "id": 3,
                "title": "Insurance Guide",
                "content": "We accept cashless insurance from major providers.",
            }
        ],
    }


def test_keyword_search_matches_answer_text_not_only_question():
    svc = _service()
    hit = svc._keyword_search("Are you open on Saturday?", _snapshot())
    assert hit is not None
    assert hit.source == "faq"
    assert "Saturday" in hit.answer
    assert hit.faq_hit is True


def test_keyword_search_synonym_timing_matches_hours_faq():
    svc = _service()
    hit = svc._keyword_search("What are your timings?", _snapshot())
    assert hit is not None
    assert hit.source == "faq"


def test_keyword_search_prefers_faq_over_policy_on_tie():
    svc = _service()
    snap = {
        "faqs": [
            {
                "id": 1,
                "question": "Parking information",
                "answer": "Visitor parking is on level B1.",
                "tags": "parking",
            }
        ],
        "policies": [
            {
                "id": 2,
                "title": "Parking Policy",
                "body": "Visitor parking is on level B1.",
                "category": "parking",
            }
        ],
        "documents": [],
    }
    hit = svc._keyword_search("Tell me about parking", snap)
    assert hit is not None
    assert hit.source == "faq"


def test_lookup_kb_entry_returns_verbatim_text():
    svc = _service()
    resolved = svc._lookup_kb_entry(_snapshot(), "policy", 2)
    assert resolved is not None
    assert resolved["text"] == "Free parking is available in the basement for all visitors."


def test_ground_to_kb_rejects_unrelated_generated_text():
    svc = _service()
    grounded = svc._ground_to_kb("The hospital fee is 5000 rupees for all services.", _snapshot())
    assert grounded is None


def test_merge_snapshots_deduplicates_by_id():
    svc = _service()
    primary = {"faqs": [{"id": 1, "question": "Q", "answer": "A", "tags": ""}], "policies": [], "documents": []}
    secondary = {
        "faqs": [{"id": 1, "question": "Q", "answer": "A", "tags": ""}, {"id": 2, "question": "Q2", "answer": "A2", "tags": ""}],
        "policies": [],
        "documents": [],
    }
    merged = svc._merge_snapshots(primary, secondary)
    assert len(merged["faqs"]) == 2


@pytest.mark.asyncio
async def test_answer_transfers_on_medical_advice():
    svc = _service()
    with patch.object(svc, "_load_snapshot", new=AsyncMock(return_value=_snapshot())):
        result = await svc.answer(1, "Which medicine should I take for fever?", "en")
    assert result.should_transfer is True
    assert result.found is False


@pytest.mark.asyncio
async def test_openai_fallback_returns_verbatim_kb_on_structured_match():
    svc = _service()

    async def _fake_create(**_kwargs):
        msg = MagicMock()
        msg.choices = [MagicMock(message=MagicMock(content="MATCH:faq:1"))]
        return msg

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=_fake_create)

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        with patch("app.services.faq_retrieval_service.settings.OPENAI_API_KEY", "test-key"):
            result = await svc._openai_fallback("What are your hours?", "en", _snapshot())

    assert result.found is True
    assert result.answer == "We are open Monday to Saturday, 8 AM to 8 PM."
    assert result.ai_fallback is True
    assert result.confidence >= 0.85


@pytest.mark.asyncio
async def test_openai_fallback_transfers_on_no_answer():
    svc = _service()

    async def _fake_create(**_kwargs):
        msg = MagicMock()
        msg.choices = [MagicMock(message=MagicMock(content="NO_ANSWER"))]
        return msg

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=_fake_create)

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        with patch("app.services.faq_retrieval_service.settings.OPENAI_API_KEY", "test-key"):
            result = await svc._openai_fallback("Do you have a space program?", "en", _snapshot())

    assert result.should_transfer is True
    assert result.found is False
