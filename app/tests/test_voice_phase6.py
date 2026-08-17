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
