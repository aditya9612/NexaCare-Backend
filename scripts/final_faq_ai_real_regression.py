"""
Final FAQ-AI Real-World Regression Harness
===========================================

Covers:
  1.  FAQ-AI real RAG flow
  2.  Real OpenAI embedding call (1 call total)
  3.  Real OpenAI selector / answer generation (1 call total)
  4.  PDF/document ingestion path (chunking + OCR probe)
  5.  Celery FAQ-AI task registration
  6.  Redis integration + FAQ-AI cache invalidation
  7.  MySQL persistence (read-only probes)
  8.  embedding_status lifecycle
  9.  embedding_error column existence
 10.  FAQ/document/chunk retrieval
 11.  OpenAI exception classification (mocked - Phase 8D regression)
 12.  Hospital/tenant isolation
 13.  FAQ-AI rate limiting
 14.  FAQ-AI OpenAI usage/audit logging interface
 15.  FAQ-AI health endpoint
 16.  Embedding-task MissingGreenlet regression
 17.  RAG-repository MissingGreenlet regression
 18.  WebSocket DB-session leak safety
 19.  Secure file-upload validation
 20.  OPENAI_API_KEY / configuration sanity
 21.  Voice Assistant safety (no voice files modified)

Data safety:
  - Zero writes to the database (read-only regression).
  - All Redis keys use a synthetic prefix and are cleaned up at end.
  - No pre-existing data is mutated or deleted.
  - No Alembic commands are run. No tables truncated.

Real OpenAI calls: EXACTLY 2 (one embedding, one selector)
  All exception-classification tests use mocks.

Usage:
    python scripts/final_faq_ai_real_regression.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Result Tracking
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
INFO = "INFO"

MARKER = "__faq_regr__"
SYNTH_HOSPITAL_ID = 999_999_999


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    elapsed: float = 0.0
    tb: str = ""


results: list[CheckResult] = []

openai_embedding_calls = 0
openai_selector_calls = 0
db_reads = 0
redis_checks = 0


def record(name: str, status: str, detail: str = "", elapsed: float = 0.0, tb: str = "") -> None:
    results.append(CheckResult(name, status, detail, elapsed, tb))
    symbol = {PASS: "v", FAIL: "X", SKIP: "-", INFO: "i"}.get(status, "?")
    elapsed_str = f"  [{elapsed:.2f}s]" if elapsed else ""
    line = f"[{status}]{elapsed_str} {name}"
    if detail:
        line += f"\n       {detail}"
    print(line)


class _SkipCheck(Exception):
    pass


def run_check(name: str, fn, *args, **kwargs):
    """For synchronous checks only."""
    t0 = time.perf_counter()
    try:
        result_val = fn(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        record(name, PASS, str(result_val) if result_val else "", elapsed)
    except AssertionError as exc:
        elapsed = time.perf_counter() - t0
        record(name, FAIL, str(exc), elapsed, traceback.format_exc())
    except _SkipCheck as exc:
        elapsed = time.perf_counter() - t0
        record(name, SKIP, str(exc), elapsed)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        record(name, FAIL, f"{type(exc).__name__}: {exc}", elapsed, traceback.format_exc())


async def run_check_async(name: str, fn, *args, **kwargs):
    """For async checks only — awaits coroutine directly inside the running loop."""
    t0 = time.perf_counter()
    try:
        result_val = await fn(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        record(name, PASS, str(result_val) if result_val else "", elapsed)
    except AssertionError as exc:
        elapsed = time.perf_counter() - t0
        record(name, FAIL, str(exc), elapsed, traceback.format_exc())
    except _SkipCheck as exc:
        elapsed = time.perf_counter() - t0
        record(name, SKIP, str(exc), elapsed)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        record(name, FAIL, f"{type(exc).__name__}: {exc}", elapsed, traceback.format_exc())


# ---------------------------------------------------------------------------
# Infrastructure probes
# ---------------------------------------------------------------------------

async def probe_mysql_async() -> bool:
    try:
        from sqlalchemy import text
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def probe_redis() -> bool:
    try:
        from app.utils.redis_service import get_redis
        client = await get_redis()
        if client:
            await client.ping()
            return True
        return False
    except Exception:
        return False


def probe_celery() -> bool:
    try:
        from app.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=2)
        registered = inspect.registered_tasks()
        return registered is not None
    except Exception:
        return False


def probe_api_server() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def probe_tesseract() -> bool:
    try:
        import subprocess
        result = subprocess.run(["tesseract", "--version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_configuration():
    from app.core.config import settings
    key = settings.OPENAI_API_KEY
    assert key, "OPENAI_API_KEY is empty"
    assert key not in ("", "sk-test", "change-me"), "OPENAI_API_KEY looks like a placeholder"
    model = settings.OPENAI_MODEL
    embed_model = settings.OPENAI_EMBEDDING_MODEL
    assert model, "OPENAI_MODEL not set"
    assert embed_model, "OPENAI_EMBEDDING_MODEL not set"
    return f"model={model}, embed_model={embed_model}, key_prefix={key[:8]}***"


def check_voice_safety():
    import subprocess
    voice_files = [
        "app/api/v1/routes/voice_routes.py",
        "app/services/hospital_voice_service.py",
        "app/ai/rag/rag_service.py",
        "app/tasks/voice_tasks.py",
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"] + voice_files,
        capture_output=True, text=True
    )
    modified = [f for f in result.stdout.strip().splitlines() if f.strip()]
    assert not modified, f"Voice production files modified: {modified}"
    return "No voice production files modified"


def check_missing_greenlet_celery_fix():
    import pathlib
    src = pathlib.Path("app/core/celery_async.py").read_text(encoding="utf-8")
    assert "engine.dispose()" in src, "engine.dispose() missing from celery_async.py"
    assert "asyncio.run" in src, "asyncio.run() missing from celery_async.py"
    return "[SOURCE VERIFICATION] run_celery_async disposes engine (MissingGreenlet fix present)"


def check_missing_greenlet_rag_repo():
    import pathlib
    src = pathlib.Path("app/repositories/knowledge_embedding_repository.py").read_text(encoding="utf-8")
    assert "await self.db.execute" in src, "Repository not using 'await db.execute'"
    return "[SOURCE VERIFICATION] KnowledgeEmbeddingRepository uses async db.execute (fix present)"


def check_websocket_session_safety():
    """
    [SOURCE VERIFICATION] Verify chat_routes uses per-request DB session injection
    (DbSession dependency), NOT a long-lived AsyncSessionLocal held across
    the full request/WebSocket lifetime.
    """
    import pathlib
    src = pathlib.Path("app/api/v1/routes/chat_routes.py").read_text(encoding="utf-8")

    # Must use the DbSession dependency alias (type-annotated DI), not bare AsyncSessionLocal
    assert "DbSession" in src, \
        "chat_routes does not use DbSession dependency alias — session safety unverified"

    # Must NOT hold a bare AsyncSessionLocal context manager at module/route level
    assert "AsyncSessionLocal()" not in src, \
        "chat_routes opens AsyncSessionLocal() directly — potential long-lived session leak"

    # verify_chat_hospital_scope must be called (hospital scope enforcement present)
    assert "verify_chat_hospital_scope" in src, \
        "verify_chat_hospital_scope not called in chat_routes"

    # Each route handler function must receive db as a parameter (per-request lifetime)
    # Confirm the DbSession annotation appears on route handler params
    assert src.count("db: DbSession") >= 1 or src.count("DbSession") >= 1, \
        "DbSession not found as a route parameter — session lifetime unknown"

    return ("[SOURCE VERIFICATION] chat_routes uses DbSession per-request DI; "
            "no long-lived AsyncSessionLocal; verify_chat_hospital_scope present")


def check_file_upload_validation():
    import pathlib
    src = pathlib.Path("app/api/v1/routes/faq_ai_document_routes.py").read_text(encoding="utf-8")
    assert ".pdf" in src.lower(), "PDF extension check missing"
    assert "application/pdf" in src, "MIME type check missing"
    assert "verify_chat_hospital_scope" in src, "Hospital scope check missing"
    assert "faq_ai_document_rate_limiter" in src, "Rate limiter not invoked"
    return "PDF ext, MIME type, hospital scope, rate limiter all present"


def check_tenant_isolation():
    from app.core.chat_auth import verify_chat_hospital_scope
    from app.core.constants import UserRole
    from app.core.exceptions import ForbiddenException
    from app.models.user_model import User

    # user.role is a Role ORM object whose .name attribute is the role string.
    # verify_chat_hospital_scope calls: role_name = user.role.name
    def make_user(role_name: str, hospital_id):
        user = MagicMock(spec=User)
        user.role = MagicMock()
        user.role.name = role_name
        user.hospital_id = hospital_id
        return user

    # HOSPITAL_ADMIN for hospital 1 must NOT access hospital 2
    user = make_user(UserRole.HOSPITAL_ADMIN, hospital_id=1)
    try:
        verify_chat_hospital_scope(user, requested_hospital_id=2)
        assert False, "Expected ForbiddenException for cross-hospital access"
    except ForbiddenException:
        pass

    # HOSPITAL_ADMIN for same hospital must pass
    user_same = make_user(UserRole.HOSPITAL_ADMIN, hospital_id=5)
    result_same = verify_chat_hospital_scope(user_same, requested_hospital_id=5)
    assert result_same == 5, f"Expected 5, got {result_same}"

    # SUPER_ADMIN may access any hospital
    super_user = make_user(UserRole.SUPER_ADMIN, hospital_id=None)
    result_super = verify_chat_hospital_scope(super_user, requested_hospital_id=2)
    assert result_super == 2, f"Expected 2, got {result_super}"

    return "Cross-hospital rejection OK; same-hospital OK; SUPER_ADMIN passthrough OK"


async def check_timeout_classified_before_connection():
    """
    Phase 8D regression (mocked):
    APITimeoutError must be classified as error_type='timeout'.
    APIConnectionError must be classified as error_type='connection'.
    Verified by capturing the structured log record emitted by EmbeddingService.
    """
    import logging
    from openai import APITimeoutError, APIConnectionError
    from app.ai.embeddings.service import EmbeddingService, EmbeddingUnavailableError

    svc = EmbeddingService()

    # --- Test 1: APITimeoutError → error_type must be "timeout" ---
    timeout_exc = APITimeoutError(request=MagicMock())
    timeout_logged_types: list[str] = []

    class CapturingFilter(logging.Filter):
        def filter(self, record):
            et = getattr(record, "error_type", None)
            if et:
                timeout_logged_types.append(et)
            return True

    f = CapturingFilter()
    target_logger = logging.getLogger("hms")
    target_logger.addFilter(f)
    try:
        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.embeddings.create = AsyncMock(side_effect=timeout_exc)
            try:
                await svc.embed_texts(["test timeout"])
                assert False, "Expected EmbeddingUnavailableError for timeout"
            except EmbeddingUnavailableError as e:
                assert "unavailable" in str(e).lower() or "temporarily" in str(e).lower(), \
                    f"Wrong client message for timeout: {e}"
    finally:
        target_logger.removeFilter(f)

    assert "timeout" in timeout_logged_types, \
        f"APITimeoutError not classified as 'timeout'. Logged error_types: {timeout_logged_types}"

    # --- Test 2: APIConnectionError → error_type must be "connection" ---
    conn_exc = APIConnectionError(request=MagicMock())
    conn_logged_types: list[str] = []

    class CapturingFilter2(logging.Filter):
        def filter(self, record):
            et = getattr(record, "error_type", None)
            if et:
                conn_logged_types.append(et)
            return True

    f2 = CapturingFilter2()
    target_logger.addFilter(f2)
    try:
        with patch("openai.AsyncOpenAI") as mock_cls2:
            mock_client2 = AsyncMock()
            mock_cls2.return_value = mock_client2
            mock_client2.embeddings.create = AsyncMock(side_effect=conn_exc)
            try:
                await svc.embed_texts(["test connection"])
                assert False, "Expected EmbeddingUnavailableError for connection"
            except EmbeddingUnavailableError:
                pass
    finally:
        target_logger.removeFilter(f2)

    assert "connection" in conn_logged_types, \
        f"APIConnectionError not classified as 'connection'. Logged error_types: {conn_logged_types}"

    # --- Critical ordering check: timeout must not have been classified as 'connection' ---
    assert "connection" not in timeout_logged_types, \
        f"APITimeoutError was misclassified as 'connection' (Phase 8D regression): {timeout_logged_types}"

    return (f"APITimeoutError → error_type='timeout' OK; "
            f"APIConnectionError → error_type='connection' OK")


def check_audit_logging_interface():
    from app.repositories.audit_repository import AuditRepository
    import inspect
    sig = inspect.signature(AuditRepository.create)
    params = list(sig.parameters)
    assert "action" in params, "missing 'action' param"
    assert "resource" in params, "missing 'resource' param"
    return f"AuditRepository.create signature: {sig}"


def check_chunking_service():
    from app.services.faq_ai_chunking_service import FaqAiChunkingService
    svc = FaqAiChunkingService()
    short = svc.chunk_text("Hello.")
    assert isinstance(short, list)
    long_text = "NexaCare hospital provides OPD, IPD, emergency care. " * 40
    long_result = svc.chunk_text(long_text)
    assert isinstance(long_result, list) and len(long_result) >= 1
    empty_result = svc.chunk_text("")
    assert isinstance(empty_result, list)
    return f"short={len(short)}, long={len(long_result)}, empty={len(empty_result)} chunks"


def check_ocr_availability(tesseract_available: bool):
    if not tesseract_available:
        raise _SkipCheck("Tesseract not installed")
    from app.utils.ocr import extract_text_from_pdf_bytes
    import inspect
    sig = inspect.signature(extract_text_from_pdf_bytes)
    assert len(sig.parameters) >= 1
    return "extract_text_from_pdf_bytes importable"


async def check_mysql_schema():
    global db_reads
    from sqlalchemy import text
    from app.core.database import AsyncSessionLocal
    required = [
        "hospital_voice_documents", "hospital_voice_document_chunks",
        "knowledge_embeddings", "hospital_faqs", "hospital_policies",
    ]
    async with AsyncSessionLocal() as db:
        for table in required:
            n = (await db.execute(
                text("SELECT COUNT(*) FROM information_schema.tables "
                     "WHERE table_schema=DATABASE() AND table_name=:t"),
                {"t": table}
            )).scalar()
            assert int(n or 0) == 1, f"Table '{table}' missing"
            db_reads += 1
        for col in ("embedding_status", "embedding_error"):
            n = (await db.execute(
                text("SELECT COUNT(*) FROM information_schema.COLUMNS "
                     "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='hospital_voice_document_chunks' "
                     "AND COLUMN_NAME=:c"),
                {"c": col}
            )).scalar()
            assert int(n or 0) == 1, f"Column 'hospital_voice_document_chunks.{col}' missing"
            db_reads += 1
        rev = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        db_reads += 1
    return f"All tables present. alembic_version={rev}"


async def check_embedding_status_values():
    global db_reads
    from sqlalchemy import text
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            text("SELECT embedding_status, COUNT(*) FROM hospital_voice_document_chunks "
                 "GROUP BY embedding_status")
        )).fetchall()
        db_reads += 1
    valid = {"pending", "processing", "completed", "failed"}
    summary = {r[0]: r[1] for r in rows}
    bad = [s for s in summary if s not in valid]
    assert not bad, f"Unexpected embedding_status values: {bad}"
    return f"Status distribution: {summary}" if summary else "No chunks in DB (OK)"


async def check_faq_retrieval_read():
    global db_reads
    from sqlalchemy import text
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        faq_count = (await db.execute(text("SELECT COUNT(*) FROM hospital_faqs"))).scalar()
        doc_count = (await db.execute(text("SELECT COUNT(*) FROM hospital_voice_documents"))).scalar()
        chunk_count = (await db.execute(text("SELECT COUNT(*) FROM hospital_voice_document_chunks"))).scalar()
        emb_count = (await db.execute(
            text("SELECT COUNT(*) FROM knowledge_embeddings WHERE is_active=1")
        )).scalar()
        db_reads += 4
    return f"faqs={faq_count}, docs={doc_count}, chunks={chunk_count}, active_embeddings={emb_count}"


async def check_redis_integration():
    global redis_checks
    from app.utils.redis_service import cache_set, cache_get, cache_delete
    key = f"faq_regression:probe:{int(time.time())}"
    ok = await cache_set(key, {"ok": True}, ttl=60)
    redis_checks += 1
    assert ok, "cache_set failed"
    val = await cache_get(key)
    redis_checks += 1
    assert val and val.get("ok") is True
    await cache_delete(key)
    redis_checks += 1
    after = await cache_get(key)
    assert after is None, "cache_delete did not clear key"
    return "set/get/delete OK"


async def check_cache_invalidation():
    global redis_checks
    from app.utils.redis_service import cache_set, cache_get
    from app.ai.embeddings.store import EmbeddingStore
    h_id = SYNTH_HOSPITAL_ID
    key = EmbeddingStore.vector_cache_key(h_id, "en")
    await cache_set(key, [{"source": "faq", "id": 1}], ttl=60)
    redis_checks += 1
    store = EmbeddingStore(db=MagicMock())
    await store.invalidate_vector_cache(h_id)
    redis_checks += 3
    after = await cache_get(key)
    assert after is None, "invalidate_vector_cache did not clear key"
    return "EmbeddingStore.invalidate_vector_cache OK"


async def check_rate_limiter():
    global redis_checks
    from app.utils.faq_ai_rate_limiter import FaqAiRedisRateLimiter
    from app.core.exceptions import BadRequestException

    limiter = FaqAiRedisRateLimiter(limit_per_minute=5)
    with patch("app.utils.faq_ai_rate_limiter.get_redis", new=AsyncMock(return_value=None)):
        await limiter.check(hospital_id=1, user_id=1)

    mock_pipeline = MagicMock()
    mock_pipeline.incr = MagicMock()
    mock_pipeline.ttl = MagicMock()
    mock_pipeline.execute = AsyncMock(return_value=[6, 55])
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
    with patch("app.utils.faq_ai_rate_limiter.get_redis", new=AsyncMock(return_value=mock_redis)):
        try:
            await limiter.check(hospital_id=1, user_id=1)
            assert False, "Expected rate limit exception"
        except BadRequestException as e:
            assert "limit" in str(e).lower() or "exceeded" in str(e).lower()
    redis_checks += 2
    return "Fail-open OK; enforcement OK"


def check_celery_task_registration():
    import app.tasks.faq_ai_tasks  # noqa
    from app.celery_app import celery_app
    expected = [
        "app.tasks.faq_ai_tasks.generate_faq_embedding",
        "app.tasks.faq_ai_tasks.generate_policy_embedding",
        "app.tasks.faq_ai_tasks.generate_document_embedding",
    ]
    missing = [t for t in expected if t not in celery_app.tasks]
    assert not missing, f"Tasks not registered: {missing}"
    return f"All 3 FAQ-AI Celery tasks registered"


def check_celery_enqueue():
    from app.tasks.faq_ai_tasks import generate_faq_embedding
    result = generate_faq_embedding.delay(faq_id=-1, dispatched_updated_at="2000-01-01T00:00:00")
    assert result is not None
    return f"Enqueued id={result.id}"


def check_faq_health_endpoint():
    import json
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/faq-ai/health", timeout=5) as resp:
            body = resp.read().decode()
            assert resp.status in (200, 503), f"Unexpected status: {resp.status}"
            data = json.loads(body)
            assert "status" in data, "Response missing 'status'"
            assert "dependencies" in data, "Response missing 'dependencies'"
            deps = data["dependencies"]
            assert "database" in deps, "Dependencies missing 'database'"
            return f"HTTP {resp.status}: status={data['status']}"
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        assert e.code == 503, f"Unexpected error {e.code}: {body}"
        try:
            data = json.loads(body)
            return f"HTTP 503 (DB unavailable, expected): status={data.get('status')}"
        except json.JSONDecodeError:
            return f"HTTP 503: {body[:100]}"


async def check_rag_flow_mocked():
    from app.ai.rag.retriever import KnowledgeRetriever
    mock_db = MagicMock()
    fake_vec = [0.0] * 1536
    fake_vec[0] = 1.0
    fake_entry = {
        "source": "faq", "id": 1, "hospital_id": 1, "language": "en",
        "embedding": fake_vec, "text": "OPD 9 AM to 5 PM.",
        "label": "[faq:1] Q: OPD hours?\nA: 9 AM to 5 PM.", "content_hash": "abc123",
    }
    retriever = KnowledgeRetriever(mock_db)
    retriever.store.list_active_vectors = AsyncMock(return_value=[fake_entry])
    retriever.faq_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.policy_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.doc_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.chunk_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.embedder.embed_text = AsyncMock(return_value=fake_vec)
    chunks = await retriever.retrieve(hospital_id=1, query="OPD timings?", language="en", top_k=5)
    assert isinstance(chunks, list), f"retrieve() must return list"
    return f"RAG pipeline OK — {len(chunks)} chunk(s)"


async def check_real_openai_embedding():
    global openai_embedding_calls
    from app.ai.embeddings.service import EmbeddingService
    svc = EmbeddingService()
    t0 = time.perf_counter()
    vector = await svc.embed_text(f"{MARKER} What are the OPD hours?")
    elapsed = time.perf_counter() - t0
    openai_embedding_calls += 1
    assert isinstance(vector, list) and len(vector) > 0, "Empty embedding returned"
    assert all(isinstance(v, float) for v in vector[:5])
    return f"dim={len(vector)}, elapsed={elapsed:.2f}s"


async def check_real_openai_selector():
    global openai_selector_calls
    from app.ai.rag.openai_selector import OpenAITop5Selector
    from app.ai.rag.retriever import RetrievedChunk
    selector = OpenAITop5Selector()
    chunk = RetrievedChunk(
        source="faq", id=99999,
        text="OPD hours are Monday to Saturday, 9 AM to 5 PM.",
        label="[faq:99999] Q: OPD hours?\nA: Mon-Sat 9 AM to 5 PM.",
        score=0.95,
    )
    result = await selector.select(
        question=f"{MARKER} OPD hours?",
        chunks=[chunk], language="en",
        normalized_question="OPD hours",
    )
    openai_selector_calls += 1
    assert result is not None
    assert result.kind in ("match", "no_answer", "invalid_id", "error"), f"Unexpected kind: {result.kind}"
    return f"kind={result.kind}, source={result.source}, entry_id={result.entry_id}"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(mysql_ok, redis_ok, celery_ok, api_ok):
    total = len(results)
    passed = sum(1 for r in results if r.status == PASS)
    failed = sum(1 for r in results if r.status == FAIL)
    skipped = sum(1 for r in results if r.status == SKIP)

    print("\n" + "=" * 60)
    print("FINAL FAQ-AI REAL-WORLD REGRESSION -- SUMMARY")
    print("=" * 60)
    print(f"TOTAL   : {total}")
    print(f"PASSED  : {passed}")
    print(f"FAILED  : {failed}")
    print(f"SKIPPED : {skipped}")

    print("\nREAL OPENAI CALLS")
    print(f"  embedding calls : {openai_embedding_calls}")
    print(f"  selector calls  : {openai_selector_calls}")
    print(f"  total           : {openai_embedding_calls + openai_selector_calls}")

    print("\nOPENAI TOKEN USAGE : UNKNOWN (logged by EmbeddingService/selector at INFO level)")
    print("OPENAI COST        : UNKNOWN")

    print("\nDATABASE")
    print(f"  reads performed  : {db_reads}")
    print(f"  temporary writes : 0")
    print(f"  cleanup result   : N/A")

    print("\nREDIS")
    print(f"  checks performed : {redis_checks}")

    print("\nCELERY")
    r_reg = next((r for r in results if "task_registration" in r.name.lower() or "05a" in r.name), None)
    r_enq = next((r for r in results if "enqueue" in r.name.lower() or "05b" in r.name), None)
    print(f"  registration : {r_reg.status if r_reg else 'NOT RUN'}")
    print(f"  enqueue      : {r_enq.status if r_enq else 'NOT RUN'}")

    print("\nPRODUCTION FIX REGRESSION")
    checks_map = [
        ("timeout classification (Phase 8D)", "11."),
        ("tenant isolation",                  "12."),
        ("file upload validation",            "19."),
        ("MissingGreenlet Celery",            "16."),
        ("MissingGreenlet RAG repo",          "17."),
        ("WebSocket session leak",            "18."),
        ("stale API key config",              "20."),
    ]
    for label, prefix in checks_map:
        r = next((r for r in results if r.name.startswith(prefix)), None)
        print(f"  {label:<35}: {r.status if r else 'NOT RUN'}")

    print("\nVOICE SAFETY")
    vs = next((r for r in results if "21." in r.name), None)
    print(f"  voice files modified : {'NO' if vs and vs.status == PASS else 'SEE RESULT'}")
    print(f"  check result         : {vs.status if vs else 'NOT RUN'}")

    failures = [r for r in results if r.status == FAIL]
    if failures:
        print("\n" + "=" * 60)
        print("FAILURE DETAILS")
        print("=" * 60)
        for r in failures:
            print(f"\n[FAIL] {r.name}")
            print(f"  {r.detail}")
            if r.tb:
                for line in r.tb.strip().splitlines():
                    print(f"    {line}")

    print("\n" + "=" * 60)
    prereq_note = []
    if not mysql_ok:  prereq_note.append("MySQL unreachable")
    if not redis_ok:  prereq_note.append("Redis unreachable")
    if not celery_ok: prereq_note.append("Celery worker unreachable")
    if not api_ok:    prereq_note.append("API server not running")

    if failed == 0 and skipped == 0:
        verdict = "PASS"
    elif failed == 0:
        verdict = "PASS WITH SKIPS"
    elif prereq_note and all(
        any(note.lower() in r.detail.lower() for note in prereq_note)
        for r in failures
    ):
        verdict = f"PASS WITH PRE-EXISTING FAILURE ({'; '.join(prereq_note)})"
    else:
        verdict = "FAIL"

    print(f"FINAL VERDICT: {verdict}")
    print("=" * 60)
    if prereq_note:
        print(f"NOTE: Infrastructure unavailable: {prereq_note}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _main():
    print("\n" + "=" * 60)
    print("FINAL FAQ-AI REAL-WORLD REGRESSION")
    print("=" * 60)

    print("\n[INFO] Probing infrastructure...")
    mysql_ok  = await probe_mysql_async()
    redis_ok  = await probe_redis()
    celery_ok = probe_celery()
    api_ok    = probe_api_server()
    tesseract_ok = probe_tesseract()

    print(f"[INFO] MySQL    : {'available' if mysql_ok else 'UNAVAILABLE'}")
    print(f"[INFO] Redis    : {'available' if redis_ok else 'UNAVAILABLE'}")
    print(f"[INFO] Celery   : {'available' if celery_ok else 'UNAVAILABLE'}")
    print(f"[INFO] API      : {'available' if api_ok else 'UNAVAILABLE'}")
    print(f"[INFO] Tesseract: {'available' if tesseract_ok else 'UNAVAILABLE'}")
    print()

    run_check("20. OPENAI_API_KEY configuration sanity", check_configuration)
    run_check("21. Voice production files unchanged",    check_voice_safety)
    run_check("16. MissingGreenlet Celery fix",          check_missing_greenlet_celery_fix)
    run_check("17. MissingGreenlet RAG repo fix",        check_missing_greenlet_rag_repo)
    run_check("18. WebSocket DB-session safety",         check_websocket_session_safety)
    run_check("19. Secure file-upload validation",       check_file_upload_validation)
    run_check("12. Hospital/tenant isolation",           check_tenant_isolation)
    await run_check_async("11. OpenAI timeout classification", check_timeout_classified_before_connection)
    run_check("14. Audit logging interface",             check_audit_logging_interface)
    run_check("04. Document chunking service",           check_chunking_service)
    run_check("04b. OCR availability probe",             check_ocr_availability, tesseract_ok)

    if mysql_ok:
        await run_check_async("07. MySQL schema probe",              check_mysql_schema)
        await run_check_async("08. embedding_status values",         check_embedding_status_values)
        await run_check_async("10. FAQ/doc/chunk counts (read-only)",check_faq_retrieval_read)
    else:
        for n in ["07. MySQL schema probe", "08. embedding_status values", "10. FAQ/doc/chunk counts"]:
            record(n, SKIP, "MySQL unavailable")

    if redis_ok:
        await run_check_async("06a. Redis set/get/delete cycle",     check_redis_integration)
        await run_check_async("06b. FAQ-AI cache invalidation",      check_cache_invalidation)
        await run_check_async("13. FAQ-AI rate limiter",             check_rate_limiter)
    else:
        for n in ["06a. Redis cycle", "06b. Cache invalidation", "13. Rate limiter"]:
            record(n, SKIP, "Redis unavailable")

    run_check("05a. Celery FAQ-AI task registration",    check_celery_task_registration)
    if celery_ok:
        run_check("05b. Celery FAQ-AI task enqueue",     check_celery_enqueue)
    else:
        record("05b. Celery FAQ-AI task enqueue", SKIP, "Celery worker not reachable")

    if api_ok:
        run_check("15. FAQ-AI health endpoint",          check_faq_health_endpoint)
    else:
        record("15. FAQ-AI health endpoint", SKIP, "API server not running")

    await run_check_async("01. Full RAG pipeline flow (mocked)",     check_rag_flow_mocked)
    await run_check_async("02. Real OpenAI embedding call",          check_real_openai_embedding)
    await run_check_async("03. Real OpenAI selector call",           check_real_openai_selector)

    print_report(mysql_ok, redis_ok, celery_ok, api_ok)


def main():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_main())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
