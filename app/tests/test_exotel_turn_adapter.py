"""Exotel Voicebot must route DTMF/speech to /lang, /menu, or /turn by session step."""

import base64
import inspect

import pytest
from fastapi import FastAPI, Response
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
