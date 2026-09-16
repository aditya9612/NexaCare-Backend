from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

class HospitalVoiceDocumentChunk(Base, TimestampMixin):
    __tablename__ = "hospital_voice_document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("hospital_voice_documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, index=True)
    text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    embedding_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    document = relationship("HospitalVoiceDocument", backref="chunks")
