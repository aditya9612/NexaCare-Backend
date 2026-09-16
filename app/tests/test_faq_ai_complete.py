from __future__ import annotations
import pytest
from unittest.mock import patch, AsyncMock
from app.api.v1.routes.hospital_voice_routes import create_faq, update_faq, create_policy, update_policy
from app.api.v1.routes.faq_ai_document_routes import upload_document, delete_document
from app.schemas.hospital_voice_schema import HospitalFaqCreate, HospitalFaqUpdate, HospitalPolicyCreate, HospitalPolicyUpdate
from app.models.user_model import User
from app.core.exceptions import ForbiddenException
from app.services.faq_ai_chunking_service import FaqAiChunkingService
from unittest.mock import AsyncMock, patch
from datetime import datetime
from app.services.faq_ai_dispatcher import FaqAiDispatcher
from app.models.hospital_voice_model import HospitalFaq, HospitalPolicy, HospitalVoiceDocument
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException
from fastapi import UploadFile
import io
from unittest.mock import AsyncMock, patch, MagicMock
from app.ai.rag.retriever import KnowledgeRetriever
from app.ai.rag.openai_selector import OpenAITop5Selector
from app.models.hospital_voice_document_chunk import HospitalVoiceDocumentChunk
from app.models.hospital_voice_model import HospitalVoiceDocument
from app.services.faq_ai_document_service import FaqAiDocumentService
from unittest.mock import patch, MagicMock, AsyncMock
from app.tasks.faq_ai_tasks import embed_document_chunk_task, _set_chunk_failed, _embed_document_chunk_task
from httpx import AsyncClient
from app.main import app
from app.ai.embeddings.service import EmbeddingService
from openai import RateLimitError, AuthenticationError, APIConnectionError, APITimeoutError, BadRequestError, OpenAIError
from app.ai.embeddings.service import EmbeddingService, EmbeddingUnavailableError
import time
from app.core.exceptions import BadRequestException
from app.utils.faq_ai_rate_limiter import FaqAiRedisRateLimiter
from app.ai.rag.openai_selector import OpenAITop5Selector, SelectorResult, RetrievedChunk
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from app.tasks.faq_ai_tasks import _generate_document_embedding, _generate_faq_embedding, _generate_policy_embedding
pytestmark = pytest.mark.asyncio

@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.hospital_id = 1
    user.id = 1
    user.email = 'test@example.com'
    return user

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock() # Non-async add
    return db

@pytest.fixture
def doc_service(mock_db):
    service = FaqAiDocumentService(mock_db)
    service.dispatcher = AsyncMock()
    return service
_NOW = datetime(2026, 9, 1, 10, 0, 0)

def make_request():
    return MagicMock()

def make_response():
    return MagicMock()
'\ntest_faq_embedding_celery.py — Phase 2 async embedding tests.\n\nTests for the new faq_ai_tasks Celery tasks and the stale-embedding fix.\n\nPatching strategy:\n  The inner _generate_*_embedding functions use lazy imports (import inside the\n  function body). We patch at the source module level rather than trying to\n  patch a non-existent module-level attribute on faq_ai_tasks.\n\nScenarios:\n  TEST 1  — Stale task (db.updated_at > dispatch_ts) → no-op, no sync, no cache\n  TEST 2  — Deleted/inactive FAQ → no-op\n  TEST 3  — FAQ not found → no-op\n  TEST 4  — Idempotency (same task twice → correct state)\n  TEST 5  — Embedding failure → cache NOT invalidated\n  TEST 6  — Invalid/missing timestamp → task proceeds (no stale check)\n  TEST 7  — Same timestamp → NOT stale, proceeds normally\n  TEST 8  — Policy stale task discarded\n  TEST 9  — Document stale task discarded\n  TEST 10 — Inactive policy → no-op\n'
_NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
_PAST = _NOW - timedelta(minutes=5)
_FUTURE = _NOW + timedelta(minutes=5)

def _make_faq(faq_id: int=1, hospital_id: int=10, is_active: bool=True, updated_at: datetime=_NOW) -> MagicMock:
    faq = MagicMock()
    faq.id = faq_id
    faq.hospital_id = hospital_id
    faq.is_active = is_active
    faq.updated_at = updated_at
    faq.question = 'What are visiting hours?'
    faq.answer = '9 AM to 7 PM'
    faq.language = 'en'
    faq.tags = 'hours'
    return faq

def _make_policy(policy_id: int=2, hospital_id: int=10, is_active: bool=True, updated_at: datetime=_NOW) -> MagicMock:
    policy = MagicMock()
    policy.id = policy_id
    policy.hospital_id = hospital_id
    policy.is_active = is_active
    policy.updated_at = updated_at
    return policy

def _make_doc(doc_id: int=3, hospital_id: int=10, is_active: bool=True, updated_at: datetime=_NOW) -> MagicMock:
    doc = MagicMock()
    doc.id = doc_id
    doc.hospital_id = hospital_id
    doc.is_active = is_active
    doc.updated_at = updated_at
    return doc

def _session_ctx(mock_db: AsyncMock):
    """Build a mock AsyncSessionLocal context manager."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx

@pytest.mark.asyncio
async def test_audit_faq_create(mock_db, mock_user):
    payload = HospitalFaqCreate(hospital_id=1, question='Q', answer='A', language='en')
    with patch('app.api.v1.routes.hospital_voice_routes._require_admin'):
        with patch('app.api.v1.routes.hospital_voice_routes._hospital_scope', return_value=1):
            with patch('app.api.v1.routes.hospital_voice_routes.HospitalKnowledgeService') as mock_service:
                mock_service_instance = mock_service.return_value
                mock_service_instance.create_faq = AsyncMock()
                mock_service_instance.create_faq.return_value.id = 123
                with patch('app.api.v1.routes.hospital_voice_routes.AuditRepository') as mock_audit:
                    mock_audit_instance = mock_audit.return_value
                    mock_audit_instance.create = AsyncMock()
                    await create_faq(hospital_id=1, payload=payload, db=mock_db, current_user=mock_user)
                    mock_audit_instance.create.assert_called_once_with('create', 'faqs', user_id=1, resource_id='123')

@pytest.mark.asyncio
async def test_audit_policy_update(mock_db, mock_user):
    payload = HospitalPolicyUpdate(title='T')
    with patch('app.api.v1.routes.hospital_voice_routes._require_admin'):
        with patch('app.api.v1.routes.hospital_voice_routes._hospital_scope', return_value=1):
            with patch('app.api.v1.routes.hospital_voice_routes.HospitalKnowledgeService') as mock_service:
                mock_service_instance = mock_service.return_value
                mock_service_instance.get_policy = AsyncMock()
                mock_service_instance.get_policy.return_value.hospital_id = 1
                mock_service_instance.update_policy = AsyncMock()
                mock_service_instance.update_policy.return_value.id = 456
                with patch('app.api.v1.routes.hospital_voice_routes.AuditRepository') as mock_audit:
                    mock_audit_instance = mock_audit.return_value
                    mock_audit_instance.create = AsyncMock()
                    await update_policy(policy_id=456, payload=payload, db=mock_db, current_user=mock_user)
                    mock_audit_instance.create.assert_called_once_with('update', 'policies', user_id=1, resource_id='456')

@pytest.mark.asyncio
async def test_audit_document_deactivate(mock_db, mock_user):
    with patch('app.api.v1.routes.faq_ai_document_routes.verify_chat_hospital_scope'):
        with patch('app.api.v1.routes.faq_ai_document_routes.faq_ai_document_rate_limiter.check', new_callable=AsyncMock):
            with patch('app.api.v1.routes.faq_ai_document_routes.FaqAiDocumentService') as mock_service:
                mock_service_instance = mock_service.return_value
                mock_service_instance.deactivate_document = AsyncMock()
                with patch('app.api.v1.routes.faq_ai_document_routes.AuditRepository') as mock_audit:
                    mock_audit_instance = mock_audit.return_value
                    mock_audit_instance.create = AsyncMock()
                    await delete_document(hospital_id=1, document_id=789, db=mock_db, current_user=mock_user)
                    mock_audit_instance.create.assert_called_once_with(action='deactivate', resource='documents', user_id=1, resource_id='789')

@pytest.mark.asyncio
async def test_fail_closed_audit_rollback(mock_db, mock_user):
    payload = HospitalFaqCreate(hospital_id=1, question='Q', answer='A', language='en')
    with patch('app.api.v1.routes.hospital_voice_routes._require_admin'):
        with patch('app.api.v1.routes.hospital_voice_routes._hospital_scope', return_value=1):
            with patch('app.api.v1.routes.hospital_voice_routes.HospitalKnowledgeService') as mock_service:
                mock_service_instance = mock_service.return_value
                mock_service_instance.create_faq = AsyncMock()
                mock_service_instance.create_faq.return_value.id = 123
                with patch('app.api.v1.routes.hospital_voice_routes.AuditRepository') as mock_audit:
                    mock_audit_instance = mock_audit.return_value
                    mock_audit_instance.create = AsyncMock(side_effect=Exception('Audit insert failed'))
                    with pytest.raises(Exception, match='Audit insert failed'):
                        await create_faq(hospital_id=1, payload=payload, db=mock_db, current_user=mock_user)

def test_chunking_empty_input():
    service = FaqAiChunkingService()
    assert service.chunk_text('') == []
    assert service.chunk_text('   \n  \t  ') == []

def test_chunking_short_document():
    service = FaqAiChunkingService(target_words=500, overlap_words=50)
    text = 'This is a short document. It has two sentences.'
    chunks = service.chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == 'This is a short document. It has two sentences.'

def test_chunking_long_document_with_overlap():
    service = FaqAiChunkingService(target_words=10, overlap_words=5)
    text = 'This is the first sentence. This is the second sentence. This is the third sentence. This is the fourth sentence.'
    chunks = service.chunk_text(text)
    assert len(chunks) == 3
    assert chunks[0] == 'This is the first sentence. This is the second sentence.'
    assert chunks[1] == 'This is the second sentence. This is the third sentence.'
    assert chunks[2] == 'This is the third sentence. This is the fourth sentence.'

def test_chunking_deterministic():
    service = FaqAiChunkingService(target_words=20, overlap_words=10)
    text = 'First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence.'
    chunks1 = service.chunk_text(text)
    chunks2 = service.chunk_text(text)
    assert chunks1 == chunks2

def test_whitespace_normalization():
    service = FaqAiChunkingService()
    text = 'This   has   \t excessive   spaces.    And \n\n\n\n many newlines.'
    chunks = service.chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == 'This has excessive spaces. And many newlines.'

@pytest.mark.asyncio
async def test_dispatch_faq_update_commits_then_delays(mock_db):
    faq = HospitalFaq(id=1, updated_at=_NOW)
    with patch('app.services.faq_ai_dispatcher.generate_faq_embedding') as mock_task:
        dispatcher = FaqAiDispatcher(mock_db)
        await dispatcher.dispatch_faq_update(faq)
        mock_db.commit.assert_called_once()
        mock_task.delay.assert_called_once_with(1, _NOW.isoformat())

@pytest.mark.asyncio
async def test_dispatch_faq_update_failure_semantics_does_not_rollback(mock_db):
    """
    DB COMMIT succeeds -> Celery dispatch fails.
    The DB must remain committed so the FAQ is not lost, even if dispatch fails.
    """
    faq = HospitalFaq(id=1, updated_at=_NOW)
    with patch('app.services.faq_ai_dispatcher.generate_faq_embedding') as mock_task:
        mock_task.delay.side_effect = RuntimeError('RabbitMQ down')
        dispatcher = FaqAiDispatcher(mock_db)
        await dispatcher.dispatch_faq_update(faq)
        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_not_called()

@pytest.mark.asyncio
async def test_dispatch_policy_and_document(mock_db):
    policy = HospitalPolicy(id=2, updated_at=_NOW)
    doc = HospitalVoiceDocument(id=3, updated_at=_NOW)
    dispatcher = FaqAiDispatcher(mock_db)
    with patch('app.services.faq_ai_dispatcher.generate_policy_embedding') as mock_policy:
        await dispatcher.dispatch_policy_update(policy)
        mock_policy.delay.assert_called_once_with(2, _NOW.isoformat())
    with patch('app.services.faq_ai_dispatcher.generate_document_embedding') as mock_doc:
        await dispatcher.dispatch_document_update(doc)
        mock_doc.delay.assert_called_once_with(3, _NOW.isoformat())

@pytest.mark.asyncio
async def test_upload_invalid_extension(mock_user):
    file = UploadFile(filename='test.txt', file=io.BytesIO(b'test'))
    with pytest.raises(HTTPException) as exc:
        await upload_document(hospital_id=1, title='Test', file=file, current_user=mock_user, db=AsyncMock())
    assert exc.value.status_code == 400
    assert 'Only PDF files are supported' in exc.value.detail

@pytest.mark.asyncio
async def test_upload_invalid_mime(mock_user):
    from starlette.datastructures import Headers
    file = UploadFile(filename='test.pdf', file=io.BytesIO(b'test'), headers=Headers({'content-type': 'text/plain'}))
    with pytest.raises(HTTPException) as exc:
        await upload_document(hospital_id=1, title='Test', file=file, current_user=mock_user, db=AsyncMock())
    assert exc.value.status_code == 400
    assert 'Invalid MIME type' in exc.value.detail

@pytest.mark.asyncio
async def test_upload_too_large(mock_user):
    from starlette.datastructures import Headers
    file = UploadFile(filename='test.pdf', file=io.BytesIO(b'0' * (21 * 1024 * 1024)), headers=Headers({'content-type': 'application/pdf'}))
    with pytest.raises(HTTPException) as exc:
        await upload_document(hospital_id=1, title='Test', file=file, current_user=mock_user, db=AsyncMock())
    assert exc.value.status_code == 400
    assert 'File too large' in exc.value.detail

@pytest.mark.asyncio
async def test_cross_hospital_rejected():
    user = MagicMock(spec=User)
    user.id = 1
    user.hospital_id = 2
    user.role = MagicMock()
    user.role.name = 'hospital_admin'
    file = UploadFile(filename='test.pdf', file=io.BytesIO(b'test'))
    with pytest.raises(HTTPException) as exc:
        await upload_document(hospital_id=1, title='Test', file=file, current_user=user, db=AsyncMock())
    assert exc.value.status_code == 403

@pytest.mark.asyncio
async def test_retriever_resolves_document_chunk_test_faq_ai_document_rag(mock_db):
    retriever = KnowledgeRetriever(mock_db)
    chunk = HospitalVoiceDocumentChunk(id=99, document_id=1, text='Chunk content')
    chunk.document = HospitalVoiceDocument(id=1, title='Doc Title')
    retriever.chunk_repo.list_for_hospital = AsyncMock(return_value=[chunk])
    retriever.faq_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.policy_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.doc_repo.list_for_hospital = AsyncMock(return_value=[])
    lookup = await retriever._build_kb_lookup(1, 'en')
    assert 'document_chunk:99' in lookup
    assert lookup['document_chunk:99']['text'] == 'Chunk content'

@pytest.mark.asyncio
async def test_selector_matches_document_chunk():
    from app.ai.rag.openai_selector import _MATCH_PREFIX
    assert _MATCH_PREFIX.match('MATCH:document_chunk:42')
    assert _MATCH_PREFIX.match('MATCH:document_chunk:99')
    assert _MATCH_PREFIX.match('MATCH:document_chunk:42').group(1) == 'document_chunk'
    assert _MATCH_PREFIX.match('MATCH:document_chunk:42').group(2) == '42'

@pytest.mark.asyncio
async def test_selector_rejects_malformed_chunk():
    from app.ai.rag.openai_selector import _MATCH_PREFIX
    assert not _MATCH_PREFIX.match('MATCH:document_chunk:abc')
    assert not _MATCH_PREFIX.match('MATCH:document_chunk:')
    assert not _MATCH_PREFIX.match('MATCH:unknown:123')
    assert not _MATCH_PREFIX.match('MATCH:document_chunk:42 extra')

@pytest.mark.asyncio
async def test_successful_pdf_processing(doc_service, mock_db):
    with patch('app.services.faq_ai_document_service.extract_text_from_pdf_bytes', return_value='Extracted text'):
        doc_service.chunking_svc.chunk_text = MagicMock(return_value=['Chunk 1', 'Chunk 2'])

        def side_effect_add(obj):
            if isinstance(obj, HospitalVoiceDocument):
                obj.id = 99
            elif isinstance(obj, HospitalVoiceDocumentChunk):
                obj.id = 100 + obj.chunk_index
        mock_db.add.side_effect = side_effect_add
        doc = await doc_service.process_pdf(hospital_id=1, title='Test PDF', pdf_bytes=b'fake', source='test.pdf')
        assert doc.id == 99
        assert doc.title == 'Test PDF'
        assert doc.content == 'Extracted text'
        assert doc.is_active is True
        assert mock_db.add.call_count == 3
        doc_service.dispatcher.dispatch_document_embedding.assert_awaited_once_with(1, 99)

@pytest.mark.asyncio
async def test_empty_extraction_rejected(doc_service, mock_db):
    with patch('app.services.faq_ai_document_service.extract_text_from_pdf_bytes', return_value='   '):
        with pytest.raises(ValueError, match='No extractable text'):
            await doc_service.process_pdf(hospital_id=1, title='Test', pdf_bytes=b'fake')
        mock_db.add.assert_not_called()
        doc_service.dispatcher.dispatch_document_embedding.assert_not_called()

@pytest.mark.asyncio
async def test_chunking_failure_rejected(doc_service, mock_db):
    with patch('app.services.faq_ai_document_service.extract_text_from_pdf_bytes', return_value='Extracted text'):
        doc_service.chunking_svc.chunk_text = MagicMock(return_value=[])
        with pytest.raises(ValueError, match='Extracted text could not be chunked'):
            await doc_service.process_pdf(hospital_id=1, title='Test', pdf_bytes=b'fake')
        mock_db.add.assert_not_called()
        doc_service.dispatcher.dispatch_document_embedding.assert_not_called()

@pytest.mark.asyncio
async def test_deactivate_document(doc_service, mock_db):
    doc_service.doc_repo.get_by_id = AsyncMock(return_value=HospitalVoiceDocument(id=1, hospital_id=1))
    doc_service.doc_repo.update = AsyncMock()
    await doc_service.deactivate_document(hospital_id=1, document_id=1)
    doc_service.doc_repo.update.assert_awaited_once()
    mock_db.flush.assert_awaited_once()
    doc_service.dispatcher.dispatch_document_deactivation.assert_awaited_once_with(1, 1)

@pytest.mark.asyncio
async def test_deactivate_not_found(doc_service, mock_db):
    doc_service.doc_repo.get_by_id = AsyncMock(return_value=None)
    doc_service.doc_repo.update = AsyncMock()
    with pytest.raises(ValueError, match='Document not found'):
        await doc_service.deactivate_document(hospital_id=1, document_id=1)
    doc_service.doc_repo.update.assert_not_called()
    doc_service.dispatcher.dispatch_document_deactivation.assert_not_called()

async def test_chunk_default_status():
    chunk = HospitalVoiceDocumentChunk(document_id=1, chunk_index=0, text='test')
    assert chunk.document_id == 1

@patch('app.ai.embeddings.store.EmbeddingStore.upsert_kb_entry')
@patch('app.services.faq_retrieval_service.FaqRetrievalService.invalidate_cache')
@patch('app.tasks.faq_ai_tasks.AsyncSessionLocal')
async def test_chunk_embedding_success(mock_session_maker, mock_faq_svc, mock_store):
    mock_db = AsyncMock()
    mock_session_maker.return_value.__aenter__.return_value = mock_db
    mock_chunk = MagicMock()
    mock_chunk.document.is_active = True
    mock_chunk.document.language = 'en'
    mock_chunk.document.title = 'Test'
    mock_chunk.text = 'test success'
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_chunk
    mock_db.execute.return_value = mock_result
    await _embed_document_chunk_task(1, 1, is_retry=False)
    assert mock_chunk.embedding_status == 'completed'
    assert mock_chunk.embedding_error is None

@patch('app.tasks.faq_ai_tasks.AsyncSessionLocal')
async def test_chunk_set_failed(mock_session_maker):
    mock_db = AsyncMock()
    mock_session_maker.return_value.__aenter__.return_value = mock_db
    mock_chunk = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_chunk
    mock_db.execute.return_value = mock_result
    await _set_chunk_failed(1, 'Simulated Error')
    assert mock_chunk.embedding_status == 'failed'
    assert mock_chunk.embedding_error == 'Simulated Error'

@patch('app.api.v1.routes.faq_ai_health_routes.get_redis')
async def test_faq_ai_health_ok(mock_get_redis, client):
    mock_redis = AsyncMock()
    mock_get_redis.return_value = mock_redis
    response = await client.get('/api/v1/faq-ai/health')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'ok'
    assert data['dependencies']['database'] == 'ok'
    assert data['dependencies']['redis'] == 'ok'
    assert data['dependencies']['celery'] == 'unknown'
    assert data['dependencies']['openai'] == 'not_probed'

@patch('app.api.v1.routes.faq_ai_health_routes.get_redis')
async def test_faq_ai_health_redis_down(mock_get_redis, client):
    mock_get_redis.side_effect = Exception('Redis connection refused')
    response = await client.get('/api/v1/faq-ai/health')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'degraded'
    assert data['dependencies']['database'] == 'ok'
    assert data['dependencies']['redis'] == 'unavailable'
    assert 'Redis connection refused' not in response.text

@patch('openai.AsyncOpenAI')
async def test_selector_logs_usage(mock_openai, caplog):
    mock_client = AsyncMock()
    mock_openai.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='MATCH:faq:1'))]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=30, total_tokens=130)
    mock_client.chat.completions.create.return_value = mock_response
    selector = OpenAITop5Selector()
    with caplog.at_level('INFO'):
        await selector.select('question', [MagicMock(source='faq', id=1, label='label')])
    log_records = [r for r in caplog.records if r.message == 'faq_ai_openai_usage']
    assert len(log_records) == 1
    record = log_records[0]
    assert mock_client.chat.completions.create.called

@patch('openai.AsyncOpenAI')
async def test_embedding_logs_usage(mock_openai, caplog):
    mock_client = AsyncMock()
    mock_openai.return_value = mock_client
    mock_response = MagicMock()
    mock_response.data = [MagicMock(index=0, embedding=[0.1, 0.2])]
    mock_response.usage = MagicMock(prompt_tokens=50, total_tokens=50)
    mock_client.embeddings.create.return_value = mock_response
    service = EmbeddingService()
    with caplog.at_level('INFO'):
        await service.embed_texts(['hello'])
    log_records = [r for r in caplog.records if r.message == 'faq_ai_openai_usage']
    assert len(log_records) == 1
    assert mock_client.embeddings.create.called

@pytest.mark.parametrize('exc, expected_error_type, expected_msg', [(RateLimitError('error', response=make_response(), body={}), 'rate_limit', 'temporary AI service limitation'), (AuthenticationError('error', response=make_response(), body={}), 'authentication', 'AI service configuration unavailable'), (APIConnectionError(request=make_request()), 'connection', 'AI service temporarily unavailable'), (APITimeoutError(request=make_request()), 'timeout', 'AI service temporarily unavailable'), (BadRequestError('error', response=make_response(), body={}), 'bad_request', 'AI request could not be processed'), (OpenAIError('error'), 'openai_error', 'AI service unavailable'), (ValueError('error'), 'unexpected_error', 'AI service unavailable')])
@patch('openai.AsyncOpenAI')
async def test_selector_exception_classification(mock_openai, caplog, exc, expected_error_type, expected_msg):
    mock_client = AsyncMock()
    mock_client.chat.completions.create.side_effect = exc
    mock_openai.return_value = mock_client
    selector = OpenAITop5Selector()
    with caplog.at_level('WARNING'):
        result = await selector.select('question', [MagicMock(source='faq', id=1, label='label')])
    assert result.kind == 'error'
    assert result.text == expected_msg
    log_records = [r for r in caplog.records if 'faq_ai_openai_error' in r.msg or 'OpenAITop5Selector failed' in r.msg]
    assert len(log_records) == 1
    assert expected_error_type in log_records[0].message
    assert 'error' not in result.text

@pytest.mark.parametrize('exc, expected_error_type, expected_msg', [(RateLimitError('error', response=make_response(), body={}), 'rate_limit', 'temporary AI service limitation'), (AuthenticationError('error', response=make_response(), body={}), 'authentication', 'AI service configuration unavailable'), (APIConnectionError(request=make_request()), 'connection', 'AI service temporarily unavailable'), (APITimeoutError(request=make_request()), 'timeout', 'AI service temporarily unavailable'), (BadRequestError('error', response=make_response(), body={}), 'bad_request', 'AI request could not be processed'), (OpenAIError('error'), 'openai_error', 'AI service unavailable'), (ValueError('error'), 'unexpected_error', 'AI service unavailable')])
@patch('openai.AsyncOpenAI')
async def test_embedding_exception_classification(mock_openai, caplog, exc, expected_error_type, expected_msg):
    mock_client = AsyncMock()
    mock_client.embeddings.create.side_effect = exc
    mock_openai.return_value = mock_client
    service = EmbeddingService()
    with caplog.at_level('WARNING'):
        with pytest.raises(EmbeddingUnavailableError) as exc_info:
            await service.embed_texts(['hello'])
    assert expected_msg in str(exc_info.value)
    log_records = [r for r in caplog.records if 'EmbeddingService failed' in r.msg]
    assert len(log_records) == 1
    assert expected_error_type in log_records[0].message

@pytest.mark.asyncio
async def test_within_limit():
    limiter = FaqAiRedisRateLimiter(limit_per_minute=2)
    mock_pipeline = MagicMock()
    mock_pipeline.execute = AsyncMock(return_value=[1, -1])
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
    with patch('app.utils.faq_ai_rate_limiter.get_redis', new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.return_value = mock_redis
        await limiter.check(hospital_id=1, user_id=1)
        mock_pipeline.incr.assert_called_with('faq_ai:rate_limit:1:1')
        mock_pipeline.ttl.assert_called_with('faq_ai:rate_limit:1:1')
        mock_redis.expire.assert_called_with('faq_ai:rate_limit:1:1', 60)

@pytest.mark.asyncio
async def test_limit_exceeded():
    limiter = FaqAiRedisRateLimiter(limit_per_minute=2)
    mock_pipeline = MagicMock()
    mock_pipeline.execute = AsyncMock(return_value=[3, 45])
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
    with patch('app.utils.faq_ai_rate_limiter.get_redis', new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.return_value = mock_redis
        with pytest.raises(BadRequestException) as exc:
            await limiter.check(hospital_id=1, user_id=1)
        assert 'Rate limit exceeded' in str(exc.value)

@pytest.mark.asyncio
async def test_redis_unavailable_fail_open():
    limiter = FaqAiRedisRateLimiter(limit_per_minute=2)
    with patch('app.utils.faq_ai_rate_limiter.get_redis', new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.return_value = None
        await limiter.check(hospital_id=1, user_id=1)

@pytest.mark.asyncio
async def test_isolation():
    limiter = FaqAiRedisRateLimiter(limit_per_minute=2)
    mock_pipeline = MagicMock()
    mock_pipeline.execute = AsyncMock(return_value=[1, -1])
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
    with patch('app.utils.faq_ai_rate_limiter.get_redis', new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.return_value = mock_redis
        await limiter.check(hospital_id=2, user_id=3)
        mock_pipeline.incr.assert_called_with('faq_ai:rate_limit:2:3')

@pytest.mark.asyncio
async def test_build_kb_lookup_resolves_document_chunk():
    db = AsyncMock()
    retriever = KnowledgeRetriever(db)
    doc = HospitalVoiceDocument(id=10, title='Admission Policy', language='en', hospital_id=1)
    chunk = HospitalVoiceDocumentChunk(id=5, document_id=10, chunk_index=0, text='Please bring your ID.', document=doc)
    retriever.chunk_repo.list_for_hospital = AsyncMock(return_value=[chunk])
    retriever.faq_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.policy_repo.list_for_hospital = AsyncMock(return_value=[])
    retriever.doc_repo.list_for_hospital = AsyncMock(return_value=[])
    lookup = await retriever._build_kb_lookup(hospital_id=1, language='en')
    assert 'document_chunk:5' in lookup
    meta = lookup['document_chunk:5']
    assert meta['text'] == 'Please bring your ID.'
    assert 'Admission Policy' in meta['label']
    assert meta['source_type'] == 'document_chunk'
    assert meta['source_id'] == 5
    assert meta['hospital_id'] == 1

@pytest.mark.asyncio
async def test_selector_accepts_document_chunk():
    selector = OpenAITop5Selector()
    chunks = [RetrievedChunk(source='document_chunk', id=5, label='[document_chunk:5] Test', text='Test', score=0.9)]
    with patch('openai.AsyncOpenAI') as mock_openai:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='MATCH:document_chunk:5'))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client
        result = await selector.select('What to bring?', chunks)
        assert result.kind == 'match'
        assert result.source == 'document_chunk'
        assert result.entry_id == 5

@pytest.mark.asyncio
async def test_selector_rejects_invalid_source():
    selector = OpenAITop5Selector()
    chunks = [RetrievedChunk(source='document_chunk', id=5, label='[document_chunk:5] Test', text='Test', score=0.9)]
    with patch('openai.AsyncOpenAI') as mock_openai:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='MATCH:invalid:5'))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client
        result = await selector.select('What to bring?', chunks)
        assert result.kind != 'match'

@pytest.mark.asyncio
async def test_selector_rejects_arbitrary_text():
    selector = OpenAITop5Selector()
    chunks = [RetrievedChunk(source='document_chunk', id=5, label='[document_chunk:5] Test', text='Test', score=0.9)]
    with patch('openai.AsyncOpenAI') as mock_openai:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='You should bring your ID.'))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client
        result = await selector.select('What to bring?', chunks)
        assert result.kind != 'match'

@pytest.mark.asyncio
async def test_faq_embedding_stale_task_is_discarded():
    """
    If db.updated_at > dispatched_updated_at the task is stale and must exit
    without calling sync_faq_embedding or invalidating cache.
    """
    faq = _make_faq(updated_at=_FUTURE)
    dispatched_at = _NOW.isoformat()
    mock_db = AsyncMock()
    mock_sync_fn = AsyncMock()
    mock_invalidate = AsyncMock()
    with patch('app.tasks.faq_ai_tasks.AsyncSessionLocal', return_value=_session_ctx(mock_db)), patch('app.repositories.hospital_voice_repository.HospitalFaqRepository.get_by_id', AsyncMock(return_value=faq)), patch('app.tasks.faq_ai_tasks.sync_faq_embedding', mock_sync_fn), patch('app.services.faq_retrieval_service.FaqRetrievalService.invalidate_cache', mock_invalidate):
        await _generate_faq_embedding(faq_id=1, dispatched_updated_at=dispatched_at)
    mock_sync_fn.assert_not_called()
    mock_invalidate.assert_not_called()

@pytest.mark.asyncio
async def test_faq_embedding_deleted_faq_is_skipped():
    """If the FAQ is inactive when the task runs it must be a no-op."""
    faq = _make_faq(is_active=False, updated_at=_NOW)
    mock_db = AsyncMock()
    mock_sync_fn = AsyncMock()
    with patch('app.tasks.faq_ai_tasks.AsyncSessionLocal', return_value=_session_ctx(mock_db)), patch('app.repositories.hospital_voice_repository.HospitalFaqRepository.get_by_id', AsyncMock(return_value=faq)), patch('app.tasks.faq_ai_tasks.sync_faq_embedding', mock_sync_fn):
        await _generate_faq_embedding(faq_id=1, dispatched_updated_at=_NOW.isoformat())
    mock_sync_fn.assert_not_called()

@pytest.mark.asyncio
async def test_faq_embedding_not_found_is_skipped():
    """If the FAQ no longer exists in DB the task must be a no-op."""
    mock_db = AsyncMock()
    mock_sync_fn = AsyncMock()
    with patch('app.tasks.faq_ai_tasks.AsyncSessionLocal', return_value=_session_ctx(mock_db)), patch('app.repositories.hospital_voice_repository.HospitalFaqRepository.get_by_id', AsyncMock(return_value=None)), patch('app.tasks.faq_ai_tasks.sync_faq_embedding', mock_sync_fn):
        await _generate_faq_embedding(faq_id=999, dispatched_updated_at=_NOW.isoformat())
    mock_sync_fn.assert_not_called()

@pytest.mark.asyncio
async def test_faq_embedding_task_is_idempotent():
    """
    Running the same task twice on the same FAQ version must produce a correct
    final state. sync_faq_embedding is called each time (EmbeddingStore already
    does content_hash deduplication internally).
    """
    faq = _make_faq(updated_at=_NOW)
    mock_db = AsyncMock()
    mock_sync_fn = AsyncMock()
    mock_invalidate = AsyncMock()
    with patch('app.tasks.faq_ai_tasks.AsyncSessionLocal', return_value=_session_ctx(mock_db)), patch('app.repositories.hospital_voice_repository.HospitalFaqRepository.get_by_id', AsyncMock(return_value=faq)), patch('app.tasks.faq_ai_tasks.sync_faq_embedding', mock_sync_fn), patch('app.services.faq_retrieval_service.FaqRetrievalService.invalidate_cache', mock_invalidate):
        await _generate_faq_embedding(faq_id=1, dispatched_updated_at=_NOW.isoformat())
        await _generate_faq_embedding(faq_id=1, dispatched_updated_at=_NOW.isoformat())
    assert mock_sync_fn.call_count == 2
    assert mock_invalidate.call_count == 2

@pytest.mark.asyncio
async def test_cache_not_invalidated_on_embedding_failure():
    """
    If sync_faq_embedding raises, invalidate_cache must NOT be called so
    the existing cached vectors remain valid rather than being evicted,
    causing a cold rebuild from a potentially stale DB row.
    """
    faq = _make_faq(updated_at=_NOW)
    mock_db = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_invalidate = AsyncMock()

    async def _failing_sync(*_args, **_kwargs):
        raise RuntimeError('OpenAI API timeout')
    with patch('app.tasks.faq_ai_tasks.AsyncSessionLocal', return_value=_session_ctx(mock_db)), patch('app.repositories.hospital_voice_repository.HospitalFaqRepository.get_by_id', AsyncMock(return_value=faq)), patch('app.tasks.faq_ai_tasks.sync_faq_embedding', _failing_sync), patch('app.services.faq_retrieval_service.FaqRetrievalService.invalidate_cache', mock_invalidate):
        with pytest.raises(RuntimeError, match='OpenAI API timeout'):
            await _generate_faq_embedding(faq_id=1, dispatched_updated_at=_NOW.isoformat())
    mock_invalidate.assert_not_called()

@pytest.mark.asyncio
async def test_faq_embedding_invalid_timestamp_still_proceeds():
    """
    A malformed dispatched_updated_at must not crash the task.
    The stale check is skipped (dispatch_dt = None) and task proceeds normally.
    """
    faq = _make_faq(updated_at=_NOW)
    mock_db = AsyncMock()
    mock_sync_fn = AsyncMock()
    mock_invalidate = AsyncMock()
    with patch('app.tasks.faq_ai_tasks.AsyncSessionLocal', return_value=_session_ctx(mock_db)), patch('app.repositories.hospital_voice_repository.HospitalFaqRepository.get_by_id', AsyncMock(return_value=faq)), patch('app.tasks.faq_ai_tasks.sync_faq_embedding', mock_sync_fn), patch('app.services.faq_retrieval_service.FaqRetrievalService.invalidate_cache', mock_invalidate):
        await _generate_faq_embedding(faq_id=1, dispatched_updated_at='NOT-A-VALID-TIMESTAMP')
    mock_sync_fn.assert_called_once()
    mock_invalidate.assert_called_once()

@pytest.mark.asyncio
async def test_faq_embedding_same_timestamp_proceeds():
    """Task dispatched at exactly the same time as updated_at is NOT stale."""
    faq = _make_faq(updated_at=_NOW)
    mock_db = AsyncMock()
    mock_sync_fn = AsyncMock()
    mock_invalidate = AsyncMock()
    with patch('app.tasks.faq_ai_tasks.AsyncSessionLocal', return_value=_session_ctx(mock_db)), patch('app.repositories.hospital_voice_repository.HospitalFaqRepository.get_by_id', AsyncMock(return_value=faq)), patch('app.tasks.faq_ai_tasks.sync_faq_embedding', mock_sync_fn), patch('app.services.faq_retrieval_service.FaqRetrievalService.invalidate_cache', mock_invalidate):
        await _generate_faq_embedding(faq_id=1, dispatched_updated_at=_NOW.isoformat())
    mock_sync_fn.assert_called_once()
    mock_invalidate.assert_called_once()

@pytest.mark.asyncio
async def test_policy_embedding_stale_task_discarded():
    """Stale policy task must not overwrite a newer policy embedding."""
    policy = _make_policy(updated_at=_FUTURE)
    mock_db = AsyncMock()
    mock_sync_fn = AsyncMock()
    with patch('app.tasks.faq_ai_tasks.AsyncSessionLocal', return_value=_session_ctx(mock_db)), patch('app.repositories.hospital_voice_repository.HospitalPolicyRepository.get_by_id', AsyncMock(return_value=policy)), patch('app.tasks.faq_ai_tasks.sync_policy_embedding', mock_sync_fn):
        await _generate_policy_embedding(policy_id=2, dispatched_updated_at=_NOW.isoformat())
    mock_sync_fn.assert_not_called()

@pytest.mark.asyncio
async def test_document_embedding_stale_task_discarded():
    """Stale document task must not overwrite a newer document embedding."""
    doc = _make_doc(updated_at=_FUTURE)
    mock_db = AsyncMock()
    mock_sync_fn = AsyncMock()
    with patch('app.tasks.faq_ai_tasks.AsyncSessionLocal', return_value=_session_ctx(mock_db)), patch('app.repositories.hospital_voice_repository.HospitalVoiceDocumentRepository.get_by_id', AsyncMock(return_value=doc)), patch('app.tasks.faq_ai_tasks.sync_document_embedding', mock_sync_fn):
        await _generate_document_embedding(doc_id=3, dispatched_updated_at=_NOW.isoformat())
    mock_sync_fn.assert_not_called()

@pytest.mark.asyncio
async def test_policy_embedding_inactive_policy_skipped():
    """If policy is inactive when the task runs it must be a no-op."""
    policy = _make_policy(is_active=False, updated_at=_NOW)
    mock_db = AsyncMock()
    mock_sync_fn = AsyncMock()
    with patch('app.tasks.faq_ai_tasks.AsyncSessionLocal', return_value=_session_ctx(mock_db)), patch('app.repositories.hospital_voice_repository.HospitalPolicyRepository.get_by_id', AsyncMock(return_value=policy)), patch('app.services.knowledge_embedding_sync.sync_policy_embedding', mock_sync_fn):
        await _generate_policy_embedding(policy_id=2, dispatched_updated_at=_NOW.isoformat())
    mock_sync_fn.assert_not_called()