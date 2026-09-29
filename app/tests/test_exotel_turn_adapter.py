"""Exotel Voicebot must call conversation_turn(request, db) with webhook fields on the request."""

import inspect

from fastapi import Response

from app.agent.exotel_voicebot import _existing_turn_twiml
from app.agent.router import _webhook_fields, conversation_turn


def test_conversation_turn_accepts_request_and_db_only():
    params = list(inspect.signature(conversation_turn).parameters)
    assert params == ["request", "db"]


async def test_existing_turn_twiml_calls_conversation_turn_with_request(monkeypatch):
    seen: dict = {}

    class _Db:
        def __init__(self):
            self.committed = False

        async def commit(self):
            self.committed = True

        async def rollback(self):
            raise AssertionError("turn adapter should not roll back a successful turn")

    class _Session:
        def __init__(self):
            self.db = _Db()

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    session = _Session()

    async def fake_turn(request, db):
        seen["args"] = (request, db)
        seen["fields"] = await _webhook_fields(request)
        return Response(content=b"<Response><Say>ok</Say></Response>", media_type="application/xml")

    monkeypatch.setattr("app.agent.router.conversation_turn", fake_turn)
    monkeypatch.setattr("app.agent.exotel_voicebot.AsyncSessionLocal", lambda: session)

    twiml = await _existing_turn_twiml("CA_EXOTEL", "book an appointment", "1")

    assert twiml == "<Response><Say>ok</Say></Response>"
    assert seen["args"][1] is session.db
    assert session.db.committed is True
    assert seen["fields"]["CallSid"] == "CA_EXOTEL"
    assert seen["fields"]["SpeechResult"] == "book an appointment"
    assert seen["fields"]["Digits"] == "1"
    assert seen["fields"]["Confidence"] == "1.0"
