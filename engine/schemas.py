# Copyright (c) 2025 Rubeeq. All rights reserved. See LICENSE for terms.
"""
engine/schemas.py — Pydantic validation schemas for pipeline extraction outputs.

Every Claude response is validated against these schemas before being passed
to the next pipeline stage. Validation failures raise ExtractionValidationError
which the pipeline catches and records as a partial result rather than
propagating bad data downstream.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional


class ExtractionValidationError(Exception):
    """Raised when a Claude response fails schema validation."""
    pass


# ── Paper metadata ────────────────────────────────────────────────────────────

class PaperMetadata(BaseModel):
    paper_code:           str
    exam_board:           str
    subject:              str
    level:                Optional[str]  = None
    year:                 Optional[int]  = None
    exam_date:            Optional[str]  = None
    total_marks:          Optional[int]  = None
    time_allowed_minutes: Optional[int]  = None
    sections:             Optional[list] = None

    @field_validator("year")
    @classmethod
    def year_reasonable(cls, v):
        if v is not None and not (1950 <= v <= 2100):
            raise ValueError(f"year {v} is outside reasonable range")
        return v

    @field_validator("total_marks")
    @classmethod
    def marks_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"total_marks must be positive, got {v}")
        return v


# ── Question discovery ────────────────────────────────────────────────────────

class DiscoveredQuestion(BaseModel):
    simple_id:     str
    total_marks:   Optional[int] = None
    marking_style: Optional[str] = None
    section:       Optional[str] = None

    @field_validator("simple_id")
    @classmethod
    def id_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("simple_id cannot be empty")
        return v.strip()


# ── Extracted question ────────────────────────────────────────────────────────

class ExtractedQuestion(BaseModel):
    simple_id:            str
    question_text:        str
    total_marks:          Optional[int]  = None
    marking_style:        Optional[str]  = None
    question_type:        Optional[str]  = None
    options:              Optional[dict] = None
    correct_answer:       Optional[str]  = None
    requires_diagram:     Optional[bool] = False
    requires_calculation: Optional[bool] = False
    topic:                Optional[str]  = None
    extra:                Optional[dict] = None

    @field_validator("question_text")
    @classmethod
    def text_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("question_text cannot be empty")
        return v


# ── Extracted scheme ──────────────────────────────────────────────────────────

class ExtractedScheme(BaseModel):
    simple_id:         str
    marking_style:     Optional[str]  = None
    max_marks:         Optional[int]  = None
    mark_points:       Optional[list] = None
    level_descriptors: Optional[list] = None
    model_answer:      Optional[str]  = None
    examiner_notes:    Optional[str]  = None
    extra:             Optional[dict] = None


# ── Validation helpers ────────────────────────────────────────────────────────

def validate_paper(raw: dict) -> dict:
    try:
        return PaperMetadata(**raw).model_dump()
    except Exception as e:
        raise ExtractionValidationError(f"Paper metadata validation failed: {e}")


def validate_question_list(raw: list) -> list:
    validated = []
    errors    = []
    for item in raw:
        try:
            validated.append(DiscoveredQuestion(**item).model_dump())
        except Exception as e:
            errors.append(f"  Question {item.get('simple_id', '?')}: {e}")
    if errors:
        raise ExtractionValidationError(
            "Question discovery validation failed:\n" + "\n".join(errors)
        )
    return validated


def validate_question(raw: dict) -> dict:
    try:
        return ExtractedQuestion(**raw).model_dump()
    except Exception as e:
        raise ExtractionValidationError(
            f"Question {raw.get('simple_id', '?')} validation failed: {e}"
        )


def validate_scheme(raw: dict) -> dict:
    try:
        return ExtractedScheme(**raw).model_dump()
    except Exception as e:
        raise ExtractionValidationError(
            f"Scheme {raw.get('simple_id', '?')} validation failed: {e}"
        )
