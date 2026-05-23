from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import ChatMessageType, ChatSenderType, ChatSessionStatus
from app.core.database import Base
from app.models.mixins import TimestampMixin


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    session_status: Mapped[str] = mapped_column(String(50), default=ChatSessionStatus.ACTIVE, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalated_to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    intents: Mapped[list["ChatIntent"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    ai_responses: Mapped[list["AIResponse"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    memories: Mapped[list["ConversationMemory"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    sender_type: Mapped[str] = mapped_column(String(20), default=ChatSenderType.USER)
    message: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(20), default=ChatMessageType.TEXT)
    sent_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class ChatIntent(Base, TimestampMixin):
    __tablename__ = "chat_intents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    intent_name: Mapped[str] = mapped_column(String(100), index=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    detected_entities: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["ChatSession"] = relationship(back_populates="intents")


class AIResponse(Base, TimestampMixin):
    __tablename__ = "ai_responses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    response_text: Mapped[str] = mapped_column(Text)
    response_type: Mapped[str] = mapped_column(String(50), default="text")
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(50), default="llm")

    session: Mapped["ChatSession"] = relationship(back_populates="ai_responses")


class ConversationMemory(Base, TimestampMixin):
    __tablename__ = "conversation_memories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    memory_key: Mapped[str] = mapped_column(String(100), index=True)
    memory_value: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    session: Mapped["ChatSession"] = relationship(back_populates="memories")
