"""Exotel Voicebot must route DTMF/speech to /lang, /menu, or /turn by session step."""

import base64
import inspect

import pytest
from fastapi import FastAPI, Response, WebSocketDisconnect
from fastapi.testclient import TestClient

from app.agent.exotel_voicebot import (
    _dtmf_digit,
    _existing_input_twiml,
    _existing_turn_twiml,
    _route_for_step,
)
from app.agent.router import _webhook_fields, conversation_turn, router


def test_conversation_turn_accepts_request_and_db_only():
    params = list(inspect.signature(conversation_turn).parameters)
    assert params == ["request", "db"]


def test_route_for_step_matches_http_gather_actions():
    assert _route_for_step("language_select") == (
        "/agent/v1/voice/lang",
        "language_select",
    )
    assert _route_for_step("greeting") == ("/agent/v1/voice/menu", "service_menu")
    assert _route_for_step("service_menu") == ("/agent/v1/voice/menu", "service_menu")
    assert _route_for_step("collect_name") == (
        "/agent/v1/voice/turn",
        "conversation_turn",
    )
    assert _route_for_step("reschedule_select_appointment") == (
        "/agent/v1/voice/turn",
        "conversation_turn",
    )
    assert _route_for_step("select_slot") == (
        "/agent/v1/voice/turn",
        "conversation_turn",
    )
    assert _route_for_step("") == ("/agent/v1/voice/turn", "conversation_turn")


def _session_factory():
    class _Db:
        def __init__(self):
            self.committed = False

        async def commit(self):
            self.committed = True

        async def rollback(self):
            raise AssertionError("adapter should not roll back a successful call")

    class _Session:
        def __init__(self):
            self.db = _Db()

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    return _Session()


async def test_existing_turn_twiml_calls_conversation_turn_with_request(monkeypatch):
    seen: dict = {}
    session = _session_factory()

    async def fake_get_session(call_sid):
        return {"step": "collect_name", "call_sid": call_sid}

    async def fake_turn(request, db):
        seen["args"] = (request, db)
        seen["path"] = request.url.path
        seen["fields"] = await _webhook_fields(request)
        return Response(content=b"<Response><Say>ok</Say></Response>", media_type="application/xml")

    monkeypatch.setattr("app.agent.session_store.get_session", fake_get_session)
    monkeypatch.setattr("app.agent.router.conversation_turn", fake_turn)
    monkeypatch.setattr("app.agent.exotel_voicebot.AsyncSessionLocal", lambda: session)

    twiml = await _existing_turn_twiml("CA_EXOTEL", "book an appointment", "1")

    assert twiml == "<Response><Say>ok</Say></Response>"
    assert seen["path"] == "/agent/v1/voice/turn"
    assert seen["args"][1] is session.db
    assert session.db.committed is True
    assert seen["fields"]["CallSid"] == "CA_EXOTEL"
    assert seen["fields"]["SpeechResult"] == "book an appointment"
    assert seen["fields"]["Digits"] == "1"
    assert seen["fields"]["Confidence"] == "1.0"


async def test_greeting_digit_routes_to_service_menu(monkeypatch):
    seen: dict = {}
    session = _session_factory()

    async def fake_get_session(call_sid):
        return {"step": "greeting", "call_sid": call_sid}

    async def fake_menu(request, db):
        seen["path"] = request.url.path
        seen["fields"] = await _webhook_fields(request)
        return Response(
            content=b"<Response><Say>ask name</Say></Response>",
            media_type="application/xml",
        )

    async def boom_turn(*_a, **_k):
        raise AssertionError("greeting DTMF must not hit /turn")

    monkeypatch.setattr("app.agent.session_store.get_session", fake_get_session)
    monkeypatch.setattr("app.agent.router.service_menu", fake_menu)
    monkeypatch.setattr("app.agent.router.conversation_turn", boom_turn)
    monkeypatch.setattr("app.agent.exotel_voicebot.AsyncSessionLocal", lambda: session)

    twiml = await _existing_input_twiml("CA_EXOTEL", "", "1")

    assert twiml == "<Response><Say>ask name</Say></Response>"
    assert seen["path"] == "/agent/v1/voice/menu"
    assert seen["fields"]["CallSid"] == "CA_EXOTEL"
    assert seen["fields"]["Digits"] == "1"
    assert session.db.committed is True


async def test_service_menu_ignores_speech_without_dtmf(monkeypatch):
    """STT filler must not be treated as Digits or burn menu retries."""
    session = _session_factory()

    async def fake_get_session(call_sid):
        return {"step": "greeting", "call_sid": call_sid}

    async def boom_menu(*_a, **_k):
        raise AssertionError("speech-only input must not hit service_menu")

    async def boom_turn(*_a, **_k):
        raise AssertionError("greeting speech must not hit /turn")

    monkeypatch.setattr("app.agent.session_store.get_session", fake_get_session)
    monkeypatch.setattr("app.agent.router.service_menu", boom_menu)
    monkeypatch.setattr("app.agent.router.conversation_turn", boom_turn)
    monkeypatch.setattr("app.agent.exotel_voicebot.AsyncSessionLocal", lambda: session)

    twiml = await _existing_input_twiml("CA_EXOTEL", "हो.", "")

    assert twiml == ""
    assert session.db.committed is False


async def test_language_select_digit_routes_to_lang(monkeypatch):
    seen: dict = {}
    session = _session_factory()

    async def fake_get_session(call_sid):
        return {"step": "language_select", "call_sid": call_sid}

    async def fake_lang(request, db):
        seen["path"] = request.url.path
        seen["fields"] = await _webhook_fields(request)
        return Response(
            content=b"<Response><Say>greeting</Say></Response>",
            media_type="application/xml",
        )

    async def boom_turn(*_a, **_k):
        raise AssertionError("language DTMF must not hit /turn")

    monkeypatch.setattr("app.agent.session_store.get_session", fake_get_session)
    monkeypatch.setattr("app.agent.router.language_select", fake_lang)
    monkeypatch.setattr("app.agent.router.conversation_turn", boom_turn)
    monkeypatch.setattr("app.agent.exotel_voicebot.AsyncSessionLocal", lambda: session)

    twiml = await _existing_input_twiml("CA_EXOTEL", "", "2")

    assert twiml == "<Response><Say>greeting</Say></Response>"
    assert seen["path"] == "/agent/v1/voice/lang"
    assert seen["fields"]["Digits"] == "2"
    assert session.db.committed is True


@pytest.mark.parametrize("digit", ["1", "2", "3", "4"])
def test_dtmf_digit_reads_nested_and_flat_payloads(digit):
    assert _dtmf_digit({"event": "dtmf", "dtmf": {"digit": digit, "duration": "100"}}) == digit
    assert _dtmf_digit({"event": "dtmf", "digit": digit}) == digit
    assert _dtmf_digit({"event": "dtmf", "dtmf": digit}) == digit


@pytest.mark.parametrize("digit", ["1", "2", "3", "4"])
def test_keypad_dtmf_plays_turn_and_keeps_socket_open(monkeypatch, digit):
    seen: dict = {}

    class _Db:
        async def commit(self):
            return None

        async def rollback(self):
            raise AssertionError("dtmf turn should not roll back")

    class _Session:
        async def __aenter__(self):
            return _Db()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def opening(call_sid, from_number, to_number):
        return "<Response><Say>Hello</Say><Gather><Say>Menu</Say></Gather></Response>"

    async def pcm(twiml, rate):
        if "Hangup" in twiml:
            return b"\x10\x00" * 1600, False, True
        return b"\x10\x00" * 1600, True, False

    async def fake_turn(request, db):
        seen["fields"] = await _webhook_fields(request)
        return Response(content=b"<Response><Say>Next</Say><Hangup/></Response>", media_type="application/xml")

    async def no_session(call_sid):
        return None

    monkeypatch.setattr("app.agent.exotel_voicebot.opening_twiml", opening)
    monkeypatch.setattr("app.agent.exotel_voicebot.speakable_pcm", pcm)
    monkeypatch.setattr("app.agent.router.conversation_turn", fake_turn)
    monkeypatch.setattr("app.agent.exotel_voicebot.AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr("app.agent.session_store.get_session", no_session)

    app = FastAPI()
    app.include_router(router, prefix="/agent/v1/voice")
    client = TestClient(app)
    if digit == "4":
        dtmf_event = {"event": "dtmf", "stream_sid": "MZ1", "digit": digit}
    else:
        dtmf_event = {
            "event": "dtmf",
            "stream_sid": "MZ1",
            "dtmf": {"digit": digit, "duration": "100"},
        }

    with client.websocket_connect("/agent/v1/voice/incoming?sample-rate=8000") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json(
            {
                "event": "start",
                "stream_sid": "MZ1",
                "start": {
                    "stream_sid": "MZ1",
                    "call_sid": "CA_TEST",
                    "from": "08951395076",
                    "to": "02048565100",
                    "media_format": {"encoding": "audio/x-raw", "sample_rate": "8000"},
                },
            }
        )
        opening_media = ws.receive_json()
        assert opening_media["event"] == "media"
        opening_mark = ws.receive_json()
        assert opening_mark["mark"]["name"] == "open-1"

        ws.send_json(dtmf_event)
        # Opening mark not acked yet → still "playing" → clear then next prompt.
        cleared = ws.receive_json()
        assert cleared["event"] == "clear"
        assert cleared["stream_sid"] == "MZ1"
        media = ws.receive_json()
        assert media["event"] == "media"
        assert media["stream_sid"] == "MZ1"
        payload = base64.b64decode(media["media"]["payload"])
        assert len(payload) >= 3200
        assert len(payload) % 320 == 0
        mark = ws.receive_json()
        assert mark["event"] == "mark"
        assert mark["mark"]["name"] == "turn"

        ws.send_json({"event": "mark", "stream_sid": "MZ1", "mark": {"name": "turn"}})
        ws.send_json({"event": "stop", "stop": {"reason": "callended", "call_sid": "CA_TEST"}})

    assert seen["fields"]["CallSid"] == "CA_TEST"
    assert seen["fields"]["SpeechResult"] == ""
    assert seen["fields"]["Digits"] == digit


def test_dtmf_during_menu_playback_clears_then_plays_selection(monkeypatch):
    """Digit mid-prompt must flush Exotel buffer and jump to that digit's flow."""
    seen: dict = {}

    class _Db:
        async def commit(self):
            return None

        async def rollback(self):
            raise AssertionError("dtmf turn should not roll back")

    class _Session:
        async def __aenter__(self):
            return _Db()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def opening(call_sid, from_number, to_number):
        return "<Response><Say>Hello</Say><Gather><Say>Menu</Say></Gather></Response>"

    async def pcm(twiml, rate):
        # Multi-chunk menu so DTMF can arrive before mark is sent.
        if "Next" in twiml or "ask name" in twiml.lower() or "Hangup" in twiml:
            return b"\x10\x00" * 1600, True, False
        return b"\x10\x00" * 1600 * 8, True, False

    async def fake_menu(request, db):
        seen["fields"] = await _webhook_fields(request)
        return Response(
            content=b"<Response><Say>ask name</Say></Response>",
            media_type="application/xml",
        )

    async def fake_get_session(call_sid):
        return {
            "step": "service_menu",
            "call_sid": call_sid,
            "twilio_language": "en-IN",
        }

    monkeypatch.setattr("app.agent.exotel_voicebot.opening_twiml", opening)
    monkeypatch.setattr("app.agent.exotel_voicebot.speakable_pcm", pcm)
    monkeypatch.setattr("app.agent.router.service_menu", fake_menu)
    monkeypatch.setattr("app.agent.exotel_voicebot.AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr("app.agent.session_store.get_session", fake_get_session)

    app = FastAPI()
    app.include_router(router, prefix="/agent/v1/voice")
    client = TestClient(app)

    with client.websocket_connect("/agent/v1/voice/incoming?sample-rate=8000") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json(
            {
                "event": "start",
                "stream_sid": "MZ1",
                "start": {
                    "stream_sid": "MZ1",
                    "call_sid": "CA_BARGE",
                    "from": "08951395076",
                    "to": "02048565100",
                    "media_format": {"encoding": "audio/x-raw", "sample_rate": "8000"},
                },
            }
        )
        first = ws.receive_json()
        assert first["event"] == "media"

        ws.send_json(
            {
                "event": "dtmf",
                "stream_sid": "MZ1",
                "dtmf": {"digit": "1", "duration": "100"},
            }
        )

        # Drain any already-queued menu chunks, then expect clear + next prompt.
        events = []
        for _ in range(20):
            ev = ws.receive_json()
            events.append(ev)
            if ev.get("event") == "clear":
                break
        assert events[-1]["event"] == "clear"
        assert events[-1]["stream_sid"] == "MZ1"

        media = ws.receive_json()
        assert media["event"] == "media"
        mark = ws.receive_json()
        assert mark["event"] == "mark"
        assert mark["mark"]["name"] == "turn"

        ws.send_json({"event": "mark", "stream_sid": "MZ1", "mark": {"name": "turn"}})
        ws.send_json({"event": "stop", "stop": {"reason": "callended", "call_sid": "CA_BARGE"}})

    assert seen["fields"]["Digits"] == "1"
    assert seen["fields"]["CallSid"] == "CA_BARGE"


def test_dtmf_after_playback_ack_skips_clear(monkeypatch):
    """Once Exotel acks the mark, digit should not send a redundant clear."""
    seen: dict = {}

    class _Db:
        async def commit(self):
            return None

        async def rollback(self):
            raise AssertionError("dtmf turn should not roll back")

    class _Session:
        async def __aenter__(self):
            return _Db()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def opening(call_sid, from_number, to_number):
        return "<Response><Say>Hello</Say><Gather><Say>Menu</Say></Gather></Response>"

    async def pcm(twiml, rate):
        return b"\x10\x00" * 1600, True, False

    async def fake_turn(request, db):
        seen["fields"] = await _webhook_fields(request)
        return Response(content=b"<Response><Say>Next</Say></Response>", media_type="application/xml")

    async def no_session(call_sid):
        return None

    monkeypatch.setattr("app.agent.exotel_voicebot.opening_twiml", opening)
    monkeypatch.setattr("app.agent.exotel_voicebot.speakable_pcm", pcm)
    monkeypatch.setattr("app.agent.router.conversation_turn", fake_turn)
    monkeypatch.setattr("app.agent.exotel_voicebot.AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr("app.agent.session_store.get_session", no_session)

    app = FastAPI()
    app.include_router(router, prefix="/agent/v1/voice")
    client = TestClient(app)

    with client.websocket_connect("/agent/v1/voice/incoming?sample-rate=8000") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json(
            {
                "event": "start",
                "stream_sid": "MZ1",
                "start": {
                    "stream_sid": "MZ1",
                    "call_sid": "CA_ACK",
                    "from": "08951395076",
                    "to": "02048565100",
                    "media_format": {"encoding": "audio/x-raw", "sample_rate": "8000"},
                },
            }
        )
        assert ws.receive_json()["event"] == "media"
        assert ws.receive_json()["mark"]["name"] == "open-1"
        ws.send_json({"event": "mark", "stream_sid": "MZ1", "mark": {"name": "open-1"}})

        ws.send_json(
            {
                "event": "dtmf",
                "stream_sid": "MZ1",
                "dtmf": {"digit": "2", "duration": "100"},
            }
        )
        media = ws.receive_json()
        assert media["event"] == "media"
        mark = ws.receive_json()
        assert mark["event"] == "mark"
        assert mark["mark"]["name"] == "turn"
        ws.send_json({"event": "stop", "stop": {"reason": "callended", "call_sid": "CA_ACK"}})

    assert seen["fields"]["Digits"] == "2"


def test_cancel_success_plays_then_waits_mark_sleeps_and_hangs_up(monkeypatch):
    import asyncio

    from app.agent import session_store

    slept: list[float] = []
    seen: dict = {}
    redis: dict = {}

    async def fake_sleep(seconds):
        slept.append(seconds)

    async def cache_get(key):
        value = redis.get(key)
        return dict(value) if isinstance(value, dict) else value

    async def cache_set(key, value, ttl=300):
        redis[key] = dict(value) if isinstance(value, dict) else value
        return True

    class _Db:
        async def commit(self):
            return None

        async def rollback(self):
            raise AssertionError("dtmf turn should not roll back")

    class _Session:
        async def __aenter__(self):
            return _Db()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def opening(call_sid, from_number, to_number):
        return "<Response><Say>Hello</Say><Gather><Say>Menu</Say></Gather></Response>"

    async def pcm(twiml, rate):
        if "Hangup" in twiml:
            return b"\x10\x00" * 1600, False, True
        return b"\x10\x00" * 1600, True, False

    async def fake_turn(request, db):
        seen["fields"] = await _webhook_fields(request)
        await session_store.update_session(
            seen["fields"]["CallSid"], {"cancel_hangup_after_playback": True}
        )
        return Response(
            content=(
                b"<Response><Say>Your appointment has been successfully cancelled. "
                b"Thank you for calling NexaCare. Have a nice day.</Say><Hangup/></Response>"
            ),
            media_type="application/xml",
        )

    monkeypatch.setattr("app.agent.session_store.cache_get", cache_get)
    monkeypatch.setattr("app.agent.session_store.cache_set", cache_set)
    monkeypatch.setattr("app.agent.exotel_voicebot.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("app.agent.exotel_voicebot.opening_twiml", opening)
    monkeypatch.setattr("app.agent.exotel_voicebot.speakable_pcm", pcm)
    monkeypatch.setattr("app.agent.router.conversation_turn", fake_turn)
    monkeypatch.setattr("app.agent.exotel_voicebot.AsyncSessionLocal", lambda: _Session())

    session_store._sessions.pop("CA_TEST", None)
    asyncio.run(
        session_store.create_session("CA_TEST", "08951395076", "http://localhost")
    )
    asyncio.run(
        session_store.update_session(
            "CA_TEST", {"step": "collect_name", "twilio_language": "en-IN"}
        )
    )
    reloaded = asyncio.run(session_store.get_session("CA_TEST"))
    assert reloaded is not None
    assert reloaded.get("cancel_hangup_after_playback") is False

    app = FastAPI()
    app.include_router(router, prefix="/agent/v1/voice")
    client = TestClient(app)

    with client.websocket_connect("/agent/v1/voice/incoming?sample-rate=8000") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json(
            {
                "event": "start",
                "stream_sid": "MZ1",
                "start": {
                    "stream_sid": "MZ1",
                    "call_sid": "CA_TEST",
                    "from": "08951395076",
                    "to": "02048565100",
                    "media_format": {"encoding": "audio/x-raw", "sample_rate": "8000"},
                },
            }
        )
        opening_media = ws.receive_json()
        assert opening_media["event"] == "media"
        opening_mark = ws.receive_json()
        assert opening_mark["mark"]["name"] == "open-1"

        ws.send_json(
            {
                "event": "dtmf",
                "stream_sid": "MZ1",
                "dtmf": {"digit": "1", "duration": "100"},
            }
        )
        cleared = ws.receive_json()
        assert cleared["event"] == "clear"
        media = ws.receive_json()
        assert media["event"] == "media"
        mark = ws.receive_json()
        assert mark["event"] == "mark"
        assert mark["mark"]["name"] == "turn"
        assert slept == []
        after_pcm = asyncio.run(session_store.get_session("CA_TEST"))
        assert after_pcm is not None
        assert after_pcm.get("cancel_hangup_after_playback") is True

        ws.send_json(
            {
                "event": "mark",
                "sequence_number": "15",
                "stream_sid": "MZ1",
                "mark": {"name": "turn"},
            }
        )
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()

    assert slept == [2]
    assert seen["fields"]["Digits"] == "1"
    session_store._sessions.pop("CA_TEST", None)
