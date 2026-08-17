"""
app/ai/rag/INTEGRATION.md — FAQ RAG Phase 1 integration map

## Call graph

```
HospitalKnowledgeService (CRUD)
  → EmbeddingStore.upsert_kb_entry / deactivate_entry
  → FaqRetrievalService.invalidate_cache
       → voice:faq:{hospital}:{lang} snapshot keys
       → voice:faq:query:{hospital}:* query cache
       → voice:faq:vectors / voice:faq:meta vector cache

Agent / VoiceAssistant FAQ turn
  → MedicalSafetyGuard (FaqRetrievalService)
  → FaqRetrievalService.answer(hospital_id, question, language, session_id?)
       → RagFaqService.answer
            → Redis query cache
            → KnowledgeRetriever.retrieve (Top-5 cosine)
                 → EmbeddingStore + EmbeddingService (text-embedding-3-small)
                 → lazy backfill missing knowledge_embeddings rows
            → ConfidenceScorer (0.90 answer / 0.70 clarify / else transfer)
            → OpenAITop5Selector (Top-5 MATCH only; verbatim KB text)
            → FaqMemory (voice:faq_memory:{session_id}) — FAQ fields only
            → RagAnalytics structured log
  → Caller uses FaqAnswer (should_transfer / answer / confidence)
       → ReceptionTransferService only when should_transfer (unchanged)
```

## Non-goals (untouched)

- Booking / appointment flows and Gemini booking NLU
- Twilio webhook route contracts
- ReceptionTransferService internals
- Phase 6 conversation.py intent / memory helpers
- Chatbot generative FAQ path
"""
