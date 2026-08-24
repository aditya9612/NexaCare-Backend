"""
Canonicalize hospital FAQs: dedupe → one FAQ per topic → re-embed → evaluate.

Usage (from NexaCare-Backend with PYTHONPATH=.):
  python scripts/canonicalize_hospital_faqs.py --hospital-id 1
  python scripts/canonicalize_hospital_faqs.py --hospital-id 1 --dry-run
  python scripts/canonicalize_hospital_faqs.py --hospital-id 1 --eval-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app.ai.rag.retriever import KnowledgeRetriever
from app.ai.voice_appointment_assistant.language import detect_language
from app.core.database import AsyncSessionLocal
from app.repositories.hospital_voice_repository import HospitalFaqRepository
from app.schemas.hospital_voice_schema import HospitalFaqCreate
from app.services.canonical_faq_specs import build_canonical_faq_specs
from app.services.faq_retrieval_service import FaqRetrievalService
from app.services.hospital_knowledge_service import HospitalKnowledgeService
from app.services.knowledge_embedding_sync import deactivate_kb_embedding
from app.utils.helpers import utc_now
from scripts.faq_rag_eval_cases import (
    EVAL_CASES,
    hit_at_1,
    mrr,
    recall_at_k,
)


async def canonicalize(hospital_id: int, dry_run: bool = False) -> dict:
    specs = build_canonical_faq_specs()
    report: dict = {"deleted": 0, "created": 0, "topics": [s["topic"] for s in specs]}

    async with AsyncSessionLocal() as db:
        svc = HospitalKnowledgeService(db)
        faq_repo = HospitalFaqRepository(db)
        existing = await faq_repo.list_for_hospital(hospital_id, language=None)
        report["before_count"] = len(existing)

        if dry_run:
            report["would_delete"] = len(existing)
            report["would_create"] = len(specs)
            return report

        for faq in existing:
            faq.is_deleted = True
            faq.deleted_at = utc_now()
            faq.is_active = False
            await faq_repo.update(faq)
            await deactivate_kb_embedding(db, "faq", faq.id, faq.hospital_id)
            report["deleted"] += 1

        topic_to_id: dict[str, int] = {}
        for spec in specs:
            created = await svc.create_faq(
                HospitalFaqCreate(
                    hospital_id=hospital_id,
                    question=spec["question"],
                    answer=spec["answer"],
                    language=spec["language"],
                    tags=spec["tags"],
                )
            )
            topic_to_id[spec["topic"]] = created.id
            report["created"] += 1

        await db.commit()
        await FaqRetrievalService(db).invalidate_cache(hospital_id)
        report["topic_to_id"] = topic_to_id
        report["after_count"] = len(specs)
        return report


def _build_topic_to_faq_id(faqs, specs: list[dict]) -> dict[str, int]:
    question_to_topic = {s["question"]: s["topic"] for s in specs}
    topic_to_id: dict[str, int] = {}
    for faq in faqs:
        topic = question_to_topic.get(faq.question)
        if topic:
            topic_to_id[topic] = faq.id
    return topic_to_id


async def run_evaluation(hospital_id: int) -> dict:
    """Live retrieval eval with recall, confidence bands, and language breakdown."""
    specs = build_canonical_faq_specs()
    results: list[dict] = []
    action_counts: Counter[str] = Counter()
    positive_actions: Counter[str] = Counter()
    negative_actions: Counter[str] = Counter()
    lang_group_actions: dict[str, Counter[str]] = defaultdict(Counter)

    recalls = {5: [], 10: [], 15: []}
    hits: list[float] = []
    mrr_vals: list[float] = []
    positive_recalls_15: list[float] = []
    wrong_answer_count = 0
    positive_count = 0

    async with AsyncSessionLocal() as db:
        retriever = KnowledgeRetriever(db)
        faq_repo = HospitalFaqRepository(db)
        faqs = await faq_repo.list_for_hospital(hospital_id, language=None)
        topic_to_id = _build_topic_to_faq_id(faqs, specs)

        for case in EVAL_CASES:
            detected = detect_language(case.query, current="mr")
            lang = detected.value if hasattr(detected, "value") else str(detected)
            diag = await retriever.diagnose(hospital_id, case.query, lang, top_k=15)
            action = diag.confidence_action
            action_counts[action] += 1
            lang_group_actions[case.language_group][action] += 1

            ranked_faq_ids = [
                c.id for c in diag.candidates if c.source == "faq"
            ]
            expected_id = topic_to_id.get(case.expected_topic) if case.positive else None

            for k in recalls:
                recalls[k].append(recall_at_k(ranked_faq_ids, expected_id, k))
            hits.append(hit_at_1(ranked_faq_ids, expected_id))
            mrr_vals.append(mrr(ranked_faq_ids, expected_id))

            if case.positive:
                positive_count += 1
                positive_actions[action] += 1
                positive_recalls_15.append(recall_at_k(ranked_faq_ids, expected_id, 15))
                if ranked_faq_ids and expected_id and ranked_faq_ids[0] != expected_id:
                    wrong_answer_count += 1
            else:
                negative_actions[action] += 1
                if action == "answer":
                    wrong_answer_count += 1

            top = diag.candidates[0] if diag.candidates else None
            results.append(
                {
                    "query": case.query,
                    "expected_topic": case.expected_topic,
                    "language_group": case.language_group,
                    "positive": case.positive,
                    "detected_language": lang,
                    "normalized_query": diag.normalized_query,
                    "query_variants": diag.query_variants,
                    "action": action,
                    "top_fused": round(diag.top_fused_score, 3),
                    "expected_faq_id": expected_id,
                    "top_faq_id": top.id if top and top.source == "faq" else None,
                    "ranked_faq_ids": ranked_faq_ids[:5],
                    "top_candidate": (
                        {
                            "source": top.source,
                            "id": top.id,
                            "rank": top.rank,
                            "semantic_score": round(top.semantic_score, 3),
                            "keyword_score": round(top.keyword_score, 3),
                            "tag_score": round(top.tag_score, 3),
                            "authority_bonus": round(top.authority_bonus, 3),
                            "fused_score": round(top.fused_score, 3),
                            "label": top.label[:100],
                        }
                        if top
                        else None
                    ),
                }
            )

    n = len(EVAL_CASES)
    n_pos = max(positive_count, 1)
    n_neg = max(n - positive_count, 1)

    positive_fused = [
        r["top_fused"] for r in results if r["positive"] and r["top_fused"] > 0
    ]
    negative_fused = [
        r["top_fused"] for r in results if not r["positive"] and r["top_fused"] > 0
    ]

    return {
        "hospital_id": hospital_id,
        "total_queries": n,
        "positive_queries": positive_count,
        "negative_queries": n - positive_count,
        "topic_to_faq_id": topic_to_id,
        "recall_at_5": round(sum(recalls[5]) / n, 3),
        "recall_at_10": round(sum(recalls[10]) / n, 3),
        "recall_at_15": round(sum(recalls[15]) / n, 3),
        "positive_recall_at_15": round(sum(positive_recalls_15) / n_pos, 3),
        "hit_at_1": round(sum(hits) / n, 3),
        "mrr": round(sum(mrr_vals) / n, 3),
        "answer": action_counts.get("answer", 0),
        "clarify": action_counts.get("clarify", 0),
        "transfer": action_counts.get("transfer", 0),
        "answer_rate": round(action_counts.get("answer", 0) / n, 3),
        "clarify_rate": round(action_counts.get("clarify", 0) / n, 3),
        "transfer_rate": round(action_counts.get("transfer", 0) / n, 3),
        "positive_answer_rate": round(positive_actions.get("answer", 0) / n_pos, 3),
        "positive_clarify_rate": round(positive_actions.get("clarify", 0) / n_pos, 3),
        "positive_transfer_rate": round(positive_actions.get("transfer", 0) / n_pos, 3),
        "negative_answer_rate": round(negative_actions.get("answer", 0) / n_neg, 3),
        "wrong_answer_rate": round(wrong_answer_count / n, 3),
        "confidence_calibration": {
            "answer_threshold": 0.90,
            "clarify_threshold": 0.70,
            "threshold_changed": False,
            "positive_fused_scores": {
                "min": round(min(positive_fused), 3) if positive_fused else 0.0,
                "max": round(max(positive_fused), 3) if positive_fused else 0.0,
                "avg": round(sum(positive_fused) / len(positive_fused), 3)
                if positive_fused
                else 0.0,
            },
            "negative_fused_scores": {
                "min": round(min(negative_fused), 3) if negative_fused else 0.0,
                "max": round(max(negative_fused), 3) if negative_fused else 0.0,
                "avg": round(sum(negative_fused) / len(negative_fused), 3)
                if negative_fused
                else 0.0,
            },
        },
        "by_language_group": {
            g: dict(c) for g, c in lang_group_actions.items()
        },
        "details": results,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Canonicalize hospital FAQs and evaluate retrieval")
    parser.add_argument("--hospital-id", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--eval-only", action="store_true")
    parser.add_argument("--output", default="scripts/faq_eval_report.json")
    args = parser.parse_args()

    if not args.eval_only:
        print(f"=== Canonicalizing FAQs for hospital {args.hospital_id} ===")
        canon_report = await canonicalize(args.hospital_id, dry_run=args.dry_run)
        print(
            json.dumps(
                {k: v for k, v in canon_report.items() if k != "topic_to_id"},
                ensure_ascii=False,
                indent=2,
            )
        )
        if "topic_to_id" in canon_report:
            print(
                "Topic → FAQ id:",
                json.dumps(canon_report["topic_to_id"], ensure_ascii=False),
            )
        if args.dry_run:
            print("Dry run — no changes made.")
            return

    print(f"\n=== Live RAG evaluation (Hospital {args.hospital_id}) ===")
    eval_report = await run_evaluation(args.hospital_id)
    cal = eval_report["confidence_calibration"]
    print(
        f"Recall@5={eval_report['recall_at_5']:.1%} "
        f"Recall@15={eval_report['recall_at_15']:.1%} "
        f"Hit@1={eval_report['hit_at_1']:.1%} MRR={eval_report['mrr']:.3f}"
    )
    print(
        f"ANSWER: {eval_report['answer']}/{eval_report['total_queries']} "
        f"({eval_report['answer_rate']:.1%}) | "
        f"CLARIFY: {eval_report['clarify']} ({eval_report['clarify_rate']:.1%}) | "
        f"TRANSFER: {eval_report['transfer']} ({eval_report['transfer_rate']:.1%})"
    )
    print(
        f"Positive ANSWER/CLARIFY/TRANSFER: "
        f"{eval_report['positive_answer_rate']:.1%}/"
        f"{eval_report['positive_clarify_rate']:.1%}/"
        f"{eval_report['positive_transfer_rate']:.1%} | "
        f"Wrong-answer rate: {eval_report['wrong_answer_rate']:.1%} | "
        f"Negative ANSWER rate: {eval_report['negative_answer_rate']:.1%}"
    )
    print(
        f"Confidence (unchanged): ANSWER>={cal['answer_threshold']} "
        f"CLARIFY>={cal['clarify_threshold']} | "
        f"Positive fused avg={cal['positive_fused_scores']['avg']:.3f} "
        f"max={cal['positive_fused_scores']['max']:.3f} | "
        f"Negative fused max={cal['negative_fused_scores']['max']:.3f}"
    )

    out_path = Path(args.output)
    out_path.write_text(json.dumps(eval_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull report → {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
