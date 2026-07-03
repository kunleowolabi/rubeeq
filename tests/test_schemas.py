# Copyright (c) 2025 Rubeeq. All rights reserved. See LICENSE for terms.
"""
tests/test_schemas.py — Unit tests for extraction output validation schemas.

Tests that valid data passes, invalid data raises ExtractionValidationError,
and edge cases (nulls, missing fields, out-of-range values) are handled correctly.
"""

import pytest
from engine.schemas import (
    validate_paper,
    validate_question_list,
    validate_question,
    validate_scheme,
    ExtractionValidationError,
)


# ── validate_paper ────────────────────────────────────────────────────────────

class TestValidatePaper:

    def test_valid_minimal(self):
        raw = {"paper_code": "9EC0/01", "exam_board": "Pearson Edexcel", "subject": "Economics A"}
        result = validate_paper(raw)
        assert result["paper_code"] == "9EC0/01"
        assert result["exam_board"] == "Pearson Edexcel"

    def test_valid_full(self):
        raw = {
            "paper_code":           "9EC0/01",
            "exam_board":           "Pearson Edexcel",
            "subject":              "Economics A",
            "level":                "A Level",
            "year":                 2024,
            "exam_date":            "2024-06-07",
            "total_marks":          80,
            "time_allowed_minutes": 90,
            "sections":             [{"name": "A", "marks": 40}],
        }
        result = validate_paper(raw)
        assert result["year"] == 2024
        assert result["total_marks"] == 80

    def test_missing_required_field_raises(self):
        with pytest.raises(ExtractionValidationError):
            validate_paper({"paper_code": "9EC0/01", "exam_board": "Edexcel"})
            # missing subject

    def test_year_out_of_range_raises(self):
        raw = {"paper_code": "X", "exam_board": "Y", "subject": "Z", "year": 1800}
        with pytest.raises(ExtractionValidationError):
            validate_paper(raw)

    def test_year_future_reasonable(self):
        raw = {"paper_code": "X", "exam_board": "Y", "subject": "Z", "year": 2090}
        result = validate_paper(raw)
        assert result["year"] == 2090

    def test_zero_marks_raises(self):
        raw = {"paper_code": "X", "exam_board": "Y", "subject": "Z", "total_marks": 0}
        with pytest.raises(ExtractionValidationError):
            validate_paper(raw)

    def test_negative_marks_raises(self):
        raw = {"paper_code": "X", "exam_board": "Y", "subject": "Z", "total_marks": -5}
        with pytest.raises(ExtractionValidationError):
            validate_paper(raw)

    def test_optional_fields_default_to_none(self):
        raw = {"paper_code": "X", "exam_board": "Y", "subject": "Z"}
        result = validate_paper(raw)
        assert result["year"] is None
        assert result["total_marks"] is None
        assert result["sections"] is None


# ── validate_question_list ────────────────────────────────────────────────────

class TestValidateQuestionList:

    def test_valid_list(self):
        raw = [
            {"simple_id": "1a", "total_marks": 5,  "marking_style": "points_based"},
            {"simple_id": "1b", "total_marks": 8,  "marking_style": "points_based"},
            {"simple_id": "6e", "total_marks": 25, "marking_style": "levels_based"},
        ]
        result = validate_question_list(raw)
        assert len(result) == 3
        assert result[0]["simple_id"] == "1a"

    def test_empty_list_returns_empty(self):
        result = validate_question_list([])
        assert result == []

    def test_empty_simple_id_raises(self):
        raw = [{"simple_id": "", "total_marks": 5}]
        with pytest.raises(ExtractionValidationError):
            validate_question_list(raw)

    def test_whitespace_simple_id_raises(self):
        raw = [{"simple_id": "   ", "total_marks": 5}]
        with pytest.raises(ExtractionValidationError):
            validate_question_list(raw)

    def test_simple_id_stripped(self):
        raw = [{"simple_id": " 1a ", "total_marks": 5}]
        result = validate_question_list(raw)
        assert result[0]["simple_id"] == "1a"

    def test_optional_fields_allowed_null(self):
        raw = [{"simple_id": "1a"}]
        result = validate_question_list(raw)
        assert result[0]["total_marks"] is None
        assert result[0]["marking_style"] is None

    def test_multiple_invalid_raises_with_all_errors(self):
        raw = [
            {"simple_id": "",    "total_marks": 5},
            {"simple_id": "1b", "total_marks": 8},
            {"simple_id": "  ", "total_marks": 3},
        ]
        with pytest.raises(ExtractionValidationError) as exc_info:
            validate_question_list(raw)
        error_msg = str(exc_info.value)
        # Two invalid entries should both appear in the error message
        assert "Question discovery validation failed" in error_msg
        assert error_msg.count("simple_id cannot be empty") == 2


# ── validate_question ─────────────────────────────────────────────────────────

class TestValidateQuestion:

    def test_valid_structured_question(self):
        raw = {
            "simple_id":     "1a",
            "question_text": "Explain the concept of price elasticity of demand.",
            "total_marks":   5,
            "marking_style": "points_based",
            "question_type": "short_answer",
        }
        result = validate_question(raw)
        assert result["simple_id"] == "1a"
        assert result["question_text"] == "Explain the concept of price elasticity of demand."

    def test_valid_mcq_question(self):
        raw = {
            "simple_id":      "42",
            "question_text":  "Which of the following is a macroeconomic objective?",
            "total_marks":    1,
            "marking_style":  "mcq",
            "options":        {"A": "Low inflation", "B": "High prices", "C": "Tax cuts", "D": "Subsidies"},
            "correct_answer": "A",
        }
        result = validate_question(raw)
        assert result["correct_answer"] == "A"
        assert result["options"]["A"] == "Low inflation"

    def test_empty_question_text_raises(self):
        raw = {"simple_id": "1a", "question_text": ""}
        with pytest.raises(ExtractionValidationError):
            validate_question(raw)

    def test_whitespace_question_text_raises(self):
        raw = {"simple_id": "1a", "question_text": "   "}
        with pytest.raises(ExtractionValidationError):
            validate_question(raw)

    def test_missing_question_text_raises(self):
        raw = {"simple_id": "1a", "total_marks": 5}
        with pytest.raises(ExtractionValidationError):
            validate_question(raw)

    def test_optional_fields_default(self):
        raw = {"simple_id": "1a", "question_text": "Some question?"}
        result = validate_question(raw)
        assert result["requires_diagram"] is False
        assert result["requires_calculation"] is False
        assert result["options"] is None
        assert result["correct_answer"] is None

    def test_extra_field_stored(self):
        raw = {
            "simple_id":     "1a",
            "question_text": "Some question?",
            "extra":         {"custom_field": "custom_value"},
        }
        result = validate_question(raw)
        assert result["extra"]["custom_field"] == "custom_value"


# ── validate_scheme ───────────────────────────────────────────────────────────

class TestValidateScheme:

    def test_valid_points_based_scheme(self):
        raw = {
            "simple_id":     "1a",
            "marking_style": "points_based",
            "max_marks":     5,
            "mark_points":   ["Define PED correctly", "Apply to example", "Calculate correctly"],
        }
        result = validate_scheme(raw)
        assert result["simple_id"] == "1a"
        assert len(result["mark_points"]) == 3

    def test_valid_levels_based_scheme(self):
        raw = {
            "simple_id":        "6e",
            "marking_style":    "levels_based",
            "max_marks":        25,
            "level_descriptors": [
                {"level": 4, "marks_range": [19, 25], "descriptor": "Comprehensive analysis"},
                {"level": 3, "marks_range": [13, 18], "descriptor": "Good analysis"},
            ],
        }
        result = validate_scheme(raw)
        assert len(result["level_descriptors"]) == 2

    def test_minimal_scheme_valid(self):
        raw = {"simple_id": "2a"}
        result = validate_scheme(raw)
        assert result["simple_id"] == "2a"
        assert result["max_marks"] is None
        assert result["mark_points"] is None

    def test_missing_simple_id_raises(self):
        raw = {"marking_style": "points_based", "max_marks": 5}
        with pytest.raises(ExtractionValidationError):
            validate_scheme(raw)

    def test_examiner_notes_stored(self):
        raw = {
            "simple_id":      "3b",
            "examiner_notes": "Accept any valid economic argument with supporting evidence.",
        }
        result = validate_scheme(raw)
        assert "economic argument" in result["examiner_notes"]
