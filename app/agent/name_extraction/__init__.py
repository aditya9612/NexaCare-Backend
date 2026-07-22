"""Multi-stage patient name extraction pipeline for Indian multilingual voice."""

from app.agent.name_extraction.pipeline import run as extract_patient_name_pipeline

__all__ = ["extract_patient_name_pipeline"]
