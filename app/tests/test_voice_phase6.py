"""Phase 6 conversation enhancement unit tests (Flow B agent router helpers)."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.agent.conversation import (
    ConversationIntent,
    booking_lock_redirect_message,
    booking_steps,
    check_conversation_limits,
    detect_yes_no,
    faq_continue_prompt,
    goodbye_message,
    is_booking_lock_active,
    is_phase6_enabled,
    route_intent,
    should_allow_intent_switch,
    update_memory,
)
from app.agent.session_store import _empty_state


def _state(**kwargs):
    base = _empty_state("CA123", "+919999999999", "http://localhost:8000")
    base.update(kwargs)
    return base


class TestPhase6FeatureFlag:
    def test_default_off(self):
        os.environ.pop("VOICE_PHASE6_ENABLED", None)
        from app.core.config import get_settings

        get_settings.cache_clear()
        assert is_phase6_enabled() is False


class TestIntentRouter:
    def test_faq_parking_marathi(self):
        state = _state(language="mr")
        assert route_intent("Char chaki parking aahe ka?", state) == ConversationIntent.FAQ

    def test_faq_hospital_timing(self):
        state = _state(language="mr")
        assert route_intent("Hospital kiti vajeyparyant suru aste?", state) == ConversationIntent.FAQ

    def test_booking_marathi(self):
        state = _state(language="mr")
        assert route_intent("Mala udya appointment book karaychi aahe", state) == ConversationIntent.BOOKING

    def test_transfer_reception(self):
        state = _state(language="en")
        assert route_intent("Connect me to reception", state) == ConversationIntent.TRANSFER

    def test_goodbye_english(self):
        state = _state(language="en")
        assert route_intent("Thanks, goodbye", state) == ConversationIntent.GOODBYE

    def test_unknown_greeting(self):
        state = _state(language="en")
        assert route_intent("hello there", state) == ConversationIntent.UNKNOWN

    def test_priority_transfer_over_faq(self):
        state = _state(language="en")
        assert route_intent("reception hours", state) == ConversationIntent.TRANSFER


class TestBookingLock:
    def test_lock_active_on_booking_steps(self):
        for step in booking_steps():
            assert is_booking_lock_active(_state(step=step)) is True

    def test_lock_inactive_outside_booking(self):
        for step in ("faq_question", "faq_continue", "post_booking_continue", "greeting"):
            assert is_booking_lock_active(_state(step=step)) is False

    def test_faq_denied_during_booking_lock(self):
        for step in booking_steps():
            state = _state(step=step, service="book")
            assert should_allow_intent_switch(state, ConversationIntent.FAQ) is False

    def test_transfer_allowed_during_booking_lock(self):
        state = _state(step="collect_name", service="book")
        assert should_allow_intent_switch(state, ConversationIntent.TRANSFER) is True

    def test_goodbye_allowed_during_booking_lock(self):
        state = _state(step="collect_problem", service="book")
        assert should_allow_intent_switch(state, ConversationIntent.GOODBYE) is True

    def test_booking_intent_blocked_during_lock(self):
        state = _state(step="select_slot", service="book")
        assert should_allow_intent_switch(state, ConversationIntent.BOOKING) is False

    def test_faq_allowed_outside_booking_lock(self):
        for step in ("faq_continue", "post_booking_continue", "faq_question"):
            state = _state(step=step, service="faq")
            assert should_allow_intent_switch(state, ConversationIntent.FAQ) is True

    def test_classifier_still_returns_faq_during_lock(self):
        """Lock enforces routing; classifier still labels parking as FAQ."""
        state = _state(language="mr", step="collect_name", service="book")
        assert is_booking_lock_active(state) is True
        assert route_intent("Parking aahe ka?", state) == ConversationIntent.FAQ
        assert should_allow_intent_switch(state, ConversationIntent.FAQ) is False

    def test_redirect_messages_en_hi_mr(self):
        en = booking_lock_redirect_message("en")
        hi = booking_lock_redirect_message("hi")
        mr = booking_lock_redirect_message("mr")
        assert "complete your appointment booking first" in en.lower()
        assert "अपॉइंटमेंट" in hi
        assert "अपॉइंटमेंट बुकिंग पूर्ण" in mr
        assert booking_lock_redirect_message("xx") == en


class TestYesNoDetection:
    def test_marathi_yes(self):
        assert detect_yes_no("होय", "mr") == "yes"
        assert detect_yes_no("आणखी आहे", "mr") == "yes"

    def test_marathi_no(self):
        assert detect_yes_no("नाही", "mr") == "no"
        assert detect_yes_no("झाले", "mr") == "no"

    def test_hindi_yes_no(self):
        assert detect_yes_no("हाँ", "hi") == "yes"
        assert detect_yes_no("नहीं", "hi") == "no"

    def test_english_yes_no(self):
        assert detect_yes_no("Yes", "en") == "yes"
        assert detect_yes_no("No thanks", "en") == "no"

    def test_dtmf_digits(self):
        assert detect_yes_no("1", "en") == "yes"
        assert detect_yes_no("2", "en") == "no"


class TestConversationMemory:
    def test_update_memory_increments_question_count(self):
        state = _state(question_count=2)
        update_memory(state, question="test?", answer="answer", increment_question=True)
        assert state["question_count"] == 3
        assert state["last_question"] == "test?"
        assert state["last_answer"] == "answer"


class TestConversationLimits:
    def test_question_limit(self):
        state = _state(question_count=11)
        assert check_conversation_limits(state) is True

    def test_duration_limit(self):
        started = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
        state = _state(question_count=1, call_started_at=started)
        assert check_conversation_limits(state) is True

    def test_within_limits(self):
        started = datetime.now(timezone.utc).isoformat()
        state = _state(question_count=3, call_started_at=started)
        assert check_conversation_limits(state) is False


class TestLocalizedPrompts:
    def test_goodbye_messages(self):
        assert "NexaCare" in goodbye_message("en")
        assert goodbye_message("mr").startswith("धन्यवाद")

    def test_faq_continue_prompts(self):
        assert "anything else" in faq_continue_prompt("en").lower()


class TestRollbackCompatibility:
    """When flag is OFF, legacy terminal behavior helpers remain available."""

    def test_phase6_helpers_do_not_require_flag(self):
        state = _state(language="en")
        assert route_intent("parking", state) == ConversationIntent.FAQ
        assert goodbye_message("en")


class TestFaqSttUnclear:
    """STT unclear speech must not reach FAQ/RAG (Flow B agent router)."""

    def test_is_unclear_stt_empty_transcript(self):
        from app.agent.router import _is_unclear_stt

        assert _is_unclear_stt("", -1.0) is True
        assert _is_unclear_stt("   ", 0.9) is True

    def test_is_unclear_stt_low_confidence(self):
        from app.agent.router import _is_unclear_stt

        assert _is_unclear_stt("आणि", 0.0) is True
        assert _is_unclear_stt("आणि", 0.39) is True

    def test_is_unclear_stt_valid_speech(self):
        from app.agent.router import _is_unclear_stt

        question = "आपल्या हॉस्पिटल किती वाजता उघडते?"
        assert _is_unclear_stt(question, 0.85) is False
        assert _is_unclear_stt(question, -1.0) is False

    def test_is_unclear_stt_short_valid_answer_unknown_confidence(self):
        from app.agent.router import _is_unclear_stt

        # Short Marathi yes/no must not be blocked when confidence is unknown.
        assert _is_unclear_stt("हो", -1.0) is False
        assert _is_unclear_stt("नाही", -1.0) is False

    @pytest.mark.asyncio
    async def test_faq_stt_retry_does_not_call_retrieval(self):
        from unittest.mock import AsyncMock, patch

        from app.agent.router import _process_faq_transcript

        state = _state(
            language="mr",
            twilio_language="mr-IN",
            step="faq_question",
            service="faq",
            hospital_id=1,
            retry_count=0,
        )
        db = AsyncMock()

        with patch(
            "app.agent.router.FaqRetrievalService"
        ) as mock_faq_cls:
            mock_faq_cls.return_value.answer = AsyncMock()
            with patch(
                "app.agent.router.session_store.update_session",
                new=AsyncMock(),
            ):
                with patch(
                    "app.agent.router.session_store.get_session",
                    new=AsyncMock(return_value=state),
                ):
                    twiml = await _process_faq_transcript(
                        db,
                        "CA123",
                        state,
                        "आणि",
                        phase6=False,
                        confidence=0.0,
                    )

        mock_faq_cls.return_value.answer.assert_not_called()
        assert "Gather" in twiml
        assert "नीट ऐकू आले नाही" in twiml

    @pytest.mark.asyncio
    async def test_faq_stt_retry_limit_transfers(self):
        from unittest.mock import AsyncMock, patch

        from app.agent.router import _process_faq_transcript

        state = _state(
            language="mr",
            twilio_language="mr-IN",
            step="faq_question",
            service="faq",
            hospital_id=1,
            retry_count=2,
            reception_number="+911234567890",
        )
        db = AsyncMock()

        with patch(
            "app.agent.router.FaqRetrievalService"
        ) as mock_faq_cls:
            mock_faq_cls.return_value.answer = AsyncMock()
            with patch(
                "app.agent.router._do_reception_transfer",
                new=AsyncMock(return_value="<Response><Dial>+911234567890</Dial></Response>"),
            ) as mock_transfer:
                with patch(
                    "app.agent.router.session_store.delete_session",
                    new=AsyncMock(),
                ):
                    with patch(
                        "app.agent.router.session_store.update_session",
                        new=AsyncMock(),
                    ):
                        twiml = await _process_faq_transcript(
                            db,
                            "CA123",
                            state,
                            "",
                            phase6=False,
                            confidence=-1.0,
                        )

        mock_faq_cls.return_value.answer.assert_not_called()
        mock_transfer.assert_awaited_once()
        assert mock_transfer.await_args.kwargs["reason"] == "stt_unclear"
        assert "Dial" in twiml

    @pytest.mark.asyncio
    async def test_faq_resolves_hospital_when_missing_from_state(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.agent.router import _process_faq_transcript
        from app.services.faq_retrieval_service import FaqAnswer
        from app.services.hospital_voice_config_service import (
            HospitalResolutionResult,
            HospitalResolutionSource,
        )

        state = _state(
            language="mr",
            twilio_language="mr-IN",
            step="faq_question",
            service="faq",
            hospital_id=None,
            to_number="+15551234567",
            retry_count=0,
        )
        db = AsyncMock()
        mock_config = MagicMock()
        mock_config.hospital_id = 1
        mock_config.reception_number = "+911234567890"
        faq_answer = FaqAnswer(
            found=True,
            answer="आमचे हॉस्पिटल सकाळी ८ ते रात्री ८ वाजेपर्यंत उघडे असते.",
            source="faq",
            confidence=0.95,
            faq_hit=True,
        )

        with patch(
            "app.agent.router.HospitalVoiceConfigService"
        ) as mock_config_cls:
            mock_config_cls.return_value.resolve_inbound_hospital = AsyncMock(
                return_value=HospitalResolutionResult(
                    hospital_id=1,
                    config=mock_config,
                    source=HospitalResolutionSource.DID_MATCH,
                    matched_count=1,
                )
            )
            with patch(
                "app.agent.router.FaqRetrievalService"
            ) as mock_faq_cls:
                mock_faq_cls.return_value.answer = AsyncMock(return_value=faq_answer)
                with patch(
                    "app.agent.router._do_reception_transfer",
                    new=AsyncMock(),
                ) as mock_transfer:
                    with patch(
                        "app.agent.router.session_store.update_session",
                        new=AsyncMock(),
                    ):
                        with patch(
                            "app.agent.router.session_store.delete_session",
                            new=AsyncMock(),
                        ):
                            twiml = await _process_faq_transcript(
                                db,
                                "CA123",
                                state,
                                "आपल्या हॉस्पिटल किती वाजता ओपन होते",
                                phase6=False,
                                confidence=0.86,
                            )

        mock_config_cls.return_value.resolve_inbound_hospital.assert_awaited_once()
        mock_faq_cls.return_value.answer.assert_awaited_once_with(
            1,
            "आपल्या हॉस्पिटल किती वाजता ओपन होते",
            "mr",
            session_id="CA123",
        )
        mock_transfer.assert_not_awaited()
        assert "Hangup" in twiml


class TestHospitalResolutionSafety:
    def test_mask_inbound_did(self):
        from app.services.hospital_voice_config_service import mask_inbound_did

        assert mask_inbound_did("+15551234567") == "***4567"
        assert mask_inbound_did("") == "***"

    @pytest.mark.asyncio
    async def test_exact_did_match(self):
        from unittest.mock import AsyncMock, MagicMock

        from app.services.hospital_voice_config_service import (
            HospitalResolutionSource,
            HospitalVoiceConfigService,
        )

        db = AsyncMock()
        cfg = MagicMock()
        cfg.hospital_id = 1
        cfg.is_active = True
        cfg.is_deleted = False
        svc = HospitalVoiceConfigService(db)
        svc.repo.find_active_by_inbound_did = AsyncMock(return_value=[cfg])

        result = await svc.resolve_inbound_hospital(to_number="+15551111111")

        assert result.hospital_id == 1
        assert result.source == HospitalResolutionSource.DID_MATCH

    @pytest.mark.asyncio
    async def test_unknown_did_unresolved_without_dev_fallback(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.hospital_voice_config_service import (
            HospitalResolutionSource,
            HospitalVoiceConfigService,
        )

        db = AsyncMock()
        svc = HospitalVoiceConfigService(db)
        svc.repo.find_active_by_inbound_did = AsyncMock(return_value=[])
        svc.repo.list_active = AsyncMock(return_value=[MagicMock(), MagicMock()])

        with patch(
            "app.services.hospital_voice_config_service.is_dev_single_hospital_fallback_enabled",
            return_value=False,
        ):
            result = await svc.resolve_inbound_hospital(to_number="+19999999999")

        assert result.hospital_id is None
        assert result.source == HospitalResolutionSource.UNRESOLVED

    @pytest.mark.asyncio
    async def test_ambiguous_did_unresolved(self):
        from unittest.mock import AsyncMock, MagicMock

        from app.services.hospital_voice_config_service import (
            HospitalResolutionSource,
            HospitalVoiceConfigService,
        )

        db = AsyncMock()
        svc = HospitalVoiceConfigService(db)
        svc.repo.find_active_by_inbound_did = AsyncMock(
            return_value=[MagicMock(hospital_id=1), MagicMock(hospital_id=2)]
        )

        result = await svc.resolve_inbound_hospital(to_number="+15550000000")

        assert result.hospital_id is None
        assert result.source == HospitalResolutionSource.UNRESOLVED
        assert result.matched_count == 2

    @pytest.mark.asyncio
    async def test_dev_single_hospital_fallback(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.hospital_voice_config_service import (
            HospitalResolutionSource,
            HospitalVoiceConfigService,
        )

        db = AsyncMock()
        cfg = MagicMock()
        cfg.hospital_id = 42
        svc = HospitalVoiceConfigService(db)
        svc.repo.find_active_by_inbound_did = AsyncMock(return_value=[])
        svc.repo.list_active = AsyncMock(return_value=[cfg])

        with patch(
            "app.services.hospital_voice_config_service.is_dev_single_hospital_fallback_enabled",
            return_value=True,
        ):
            result = await svc.resolve_inbound_hospital(to_number="+19999999999")

        assert result.hospital_id == 42
        assert result.source == HospitalResolutionSource.DEV_SINGLE_HOSPITAL_FALLBACK

    @pytest.mark.asyncio
    async def test_faq_unknown_did_transfers_without_retrieval(self):
        from unittest.mock import AsyncMock, patch

        from app.agent.router import _process_faq_transcript
        from app.services.hospital_voice_config_service import (
            HospitalResolutionResult,
            HospitalResolutionSource,
        )

        state = _state(
            language="mr",
            step="faq_question",
            service="faq",
            hospital_id=None,
            to_number="+19999999999",
        )
        db = AsyncMock()

        with patch(
            "app.agent.router.HospitalVoiceConfigService"
        ) as mock_config_cls:
            mock_config_cls.return_value.resolve_inbound_hospital = AsyncMock(
                return_value=HospitalResolutionResult(
                    hospital_id=None,
                    config=None,
                    source=HospitalResolutionSource.UNRESOLVED,
                    matched_count=0,
                )
            )
            with patch("app.agent.router.FaqRetrievalService") as mock_faq_cls:
                with patch(
                    "app.agent.router._do_reception_transfer",
                    new=AsyncMock(return_value="<Response><Dial/></Response>"),
                ) as mock_transfer:
                    with patch(
                        "app.agent.router.session_store.delete_session",
                        new=AsyncMock(),
                    ):
                        twiml = await _process_faq_transcript(
                            db,
                            "CA123",
                            state,
                            "hospital hours",
                            phase6=False,
                            confidence=0.9,
                        )

        mock_faq_cls.return_value.answer.assert_not_called()
        mock_transfer.assert_awaited_once()
        assert mock_transfer.await_args.kwargs["reason"] == "faq_no_hospital"
        assert "Dial" in twiml

    @pytest.mark.asyncio
    async def test_faq_hospital1_not_hospital2(self):
        from unittest.mock import AsyncMock, patch

        from app.agent.router import _process_faq_transcript
        from app.services.faq_retrieval_service import FaqAnswer

        state = _state(
            language="en",
            step="faq_question",
            service="faq",
            hospital_id=1,
        )
        db = AsyncMock()

        with patch(
            "app.agent.router.FaqRetrievalService"
        ) as mock_faq_cls:
            mock_faq_cls.return_value.answer = AsyncMock(
                return_value=FaqAnswer(found=True, answer="H1 hours", confidence=0.95)
            )
            with patch(
                "app.agent.router.session_store.delete_session",
                new=AsyncMock(),
            ):
                await _process_faq_transcript(
                    db,
                    "CA123",
                    state,
                    "hours?",
                    phase6=False,
                    confidence=0.9,
                )

        mock_faq_cls.return_value.answer.assert_awaited_once_with(
            1, "hours?", "en", session_id="CA123"
        )

    @pytest.mark.asyncio
    async def test_session_retains_hospital_id_across_updates(self):
        from unittest.mock import AsyncMock, patch

        from app.agent import session_store

        with patch("app.agent.session_store.cache_set", new=AsyncMock(return_value=False)):
            with patch("app.agent.session_store.cache_get", new=AsyncMock(return_value=None)):
                state = await session_store.create_session(
                    "CA999",
                    "+919999999999",
                    "http://localhost:8000",
                    hospital_id=7,
                    to_number="+15551111111",
                    hospital_resolution_source="did_match",
                )
                await session_store.update_session("CA999", {"step": "faq_question"})
                reloaded = await session_store.get_session("CA999")

        assert reloaded is not None
        assert reloaded["hospital_id"] == 7
        assert reloaded["to_number"] == "+15551111111"
        assert reloaded["hospital_resolution_source"] == "did_match"

    @pytest.mark.asyncio
    async def test_doctor_belongs_to_hospital_blocks_cross_hospital(self):
        from unittest.mock import AsyncMock, MagicMock

        from app.agent.nodes.booking import doctor_belongs_to_hospital

        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=2))
        )

        assert await doctor_belongs_to_hospital(10, 1, db) is False

    @pytest.mark.asyncio
    async def test_confirm_and_book_blocks_cross_hospital_doctor(self):
        from unittest.mock import AsyncMock, patch

        from app.agent.nodes import booking as book_node

        state = _state(
            step="select_slot",
            hospital_id=1,
            selected_doctor_id=99,
            selected_slot={"date": "2026-08-25", "time": "10:00:00"},
            patient_name="Test",
        )
        db = AsyncMock()

        with patch.object(
            book_node,
            "doctor_belongs_to_hospital",
            new=AsyncMock(return_value=False),
        ):
            result = await book_node.confirm_and_book(state, db)

        assert result["step"] == "error"


class TestInboundDidNormalization:
    def test_us_twilio_e164_match(self):
        from app.utils.phone_utils import inbound_dids_match, normalize_inbound_did

        twilio = "+17372508034"
        stored = "+17372508034"
        assert normalize_inbound_did(twilio) == "+17372508034"
        assert inbound_dids_match(stored, twilio)

    def test_us_twilio_formatted_match(self):
        from app.utils.phone_utils import inbound_dids_match

        assert inbound_dids_match("+1 (737) 250-8034", "+17372508034")

    def test_mismatch_different_numbers(self):
        from app.utils.phone_utils import inbound_dids_match

        assert inbound_dids_match("+14787588435", "+17372508034") is False


class TestBookingIdempotency:
    @pytest.mark.asyncio
    async def test_confirm_and_book_returns_existing_on_duplicate(self):
        from unittest.mock import AsyncMock, patch

        from app.agent.nodes import booking as book_node

        state = _state(
            step="confirm",
            hospital_id=1,
            selected_doctor_id=5,
            selected_doctor_name="Dr Test",
            selected_slot={"date": "2026-08-25", "time": "10:00:00"},
            appointment_id=99,
            appointment_number="APT-EXISTING",
            booking_attempt_id="abc123",
        )
        db = AsyncMock()

        with patch.object(book_node, "doctor_belongs_to_hospital", new=AsyncMock(return_value=True)):
            result = await book_node.confirm_and_book(state, db)

        assert result["step"] == "booked"
        assert result["appointment_id"] == 99
        assert result["appointment_number"] == "APT-EXISTING"
        db.commit.assert_not_called()

    def test_booking_attempt_id_is_deterministic(self):
        from app.agent.nodes.booking import _booking_attempt_id

        state = _state(
            call_sid="CA123",
            selected_doctor_id=7,
        )
        slot = {"date": "2026-08-25", "time": "10:00:00"}
        assert _booking_attempt_id(state, slot) == _booking_attempt_id(state, slot)
