# Copyright (c) 2025 Rubeeq. All rights reserved. See LICENSE for terms.
"""
engine/pipeline.py — Main orchestrator for the extraction pipeline.

Stages:
    0. Detect exam type      — selects the correct ExamProfile
    1. Extract paper         — paper-level metadata
    2. Extract questions     — two-pass: discover then extract one-by-one
    3. Extract schemes       — one per question (skipped if profile.has_marking_schemes = False)
    4. Reconcile             — match questions to schemes, flag orphans
    Output. Generate         — schema.sql + data.json + insert.py

Usage:
    from engine.pipeline import run_pipeline
    result = run_pipeline(
        questions_path="path/to/questions.pdf",
        scheme_path="path/to/scheme.pdf",   # pass None if no scheme
        anthropic_client=client,
    )
"""

import json
import re
import traceback
from datetime import datetime, timezone

from engine.pdf_detector import (
    detect_pdf_type,
    extract_text_by_page,
    extract_first_pages_text,
    build_full_text,
    get_page_count,
)
from engine.vision_extractor import (
    extract_first_pages_vision,
    extract_structured_from_images,
    count_image_pages,
    _render_pdf_pages,
    _render_specific_pages,
)
from engine.output_generator import OutputGenerator
from engine.profile_registry import UnknownExamTypeError
from engine.schemas import (
    validate_paper,
    validate_question_list,
    validate_question,
    validate_scheme,
    ExtractionValidationError,
)
from engine.stage0 import run_stage0

# ─────────────────────────────────────────────
# LOGGER
# ─────────────────────────────────────────────

class PipelineLogger:
    """
    Structured logger for pipeline runs.
    Stores all entries in self.logs for the API/UI to stream.
    Also prints to terminal for CLI use.
    """

    def __init__(self, log_callback=None):
        """
        log_callback — optional callable(entry: dict) invoked on every log.
        Each job gets its own logger instance so concurrent jobs never
        cross-wire their log streams.
        """
        self.logs      = []
        self._callback = log_callback


    def log(self, message: str, level: str = "info"):
        entry = {"message": message, "level": level}
        self.logs.append(entry)
        prefix = {
            "info":    "  ",
            "success": "✓ ",
            "warning": "⚠  ",
            "error":   "✗ ",
        }.get(level, "  ")
        print(f"{prefix}{message}")
        if self._callback:
            self._callback(entry)

    def stage(self, title: str):
        line = "─" * 50
        print(f"\n{line}\n  STAGE: {title}\n{line}")
        self.logs.append({"message": title, "level": "stage"})


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _get_text_for_pdf(pdf_path: str, anthropic_client, logger: PipelineLogger) -> tuple:
    """
    Detect PDF type, extract text by page, return:
        (text_by_page dict, detection_result dict, page_images dict | None)

    For native PDFs: page_images is None.
    For image/mixed PDFs: page_images contains rendered PIL images for
    image-based pages only, keyed by page number.
    """
    detection = detect_pdf_type(pdf_path)
    pdf_type  = detection["pdf_type"]
    logger.log(f"PDF type: {pdf_type} ({get_page_count(pdf_path)} pages)")

    text_by_page = extract_text_by_page(pdf_path)
    page_images  = None

    if pdf_type in ("image", "mixed"):
        image_page_nums = [
            p for p, t in detection["pages"].items() if t == "image"
        ]
        logger.log(f"Rendering {len(image_page_nums)} image page(s) for vision extraction")
        page_images = _render_specific_pages(pdf_path, image_page_nums)

        # Fill text_by_page for image pages via Claude OCR
        from engine.vision_extractor import extract_text_from_images
        ocr_text = extract_text_from_images(page_images, anthropic_client)
        for page_num, text in ocr_text.items():
            text_by_page[page_num] = text
        logger.log(f"OCR complete for {len(ocr_text)} image page(s)", "success")

    return text_by_page, detection, page_images


def _get_first_pages_text(pdf_path: str, anthropic_client, num_pages: int = 2) -> str:
    """
    Extract first N pages as text, using vision if the PDF is image-based.
    Used by Stage 0 and Stage 1.
    """
    detection = detect_pdf_type(pdf_path)
    if detection["pdf_type"] == "native":
        return extract_first_pages_text(pdf_path, num_pages)
    else:
        return extract_first_pages_vision(pdf_path, anthropic_client, num_pages)


# ─────────────────────────────────────────────
# STAGE 0: DETECT EXAM TYPE
# ─────────────────────────────────────────────

def stage_0_detect(
    questions_path: str,
    anthropic_client,
    logger: PipelineLogger,
):
    logger.stage("0 — Characterise & Select Profile")
    from engine.stage0 import run_stage0
    from engine.pdf_detector import detect_pdf_type
    from engine.vision_extractor import extract_first_pages_vision

    detection = detect_pdf_type(questions_path)
    if detection["pdf_type"] == "native":
        from engine.pdf_detector import extract_first_pages_text
        text = extract_first_pages_text(questions_path, num_pages=2)
    else:
        text = extract_first_pages_vision(questions_path, anthropic_client, num_pages=2)

    characterisation, profile = run_stage0(text, anthropic_client)

    logger.log(f"Exam board  : {characterisation.get('exam_board')}")
    logger.log(f"Subject     : {characterisation.get('subject')}")
    logger.log(f"Level       : {characterisation.get('level')}")
    logger.log(f"Format      : {characterisation.get('question_format')}")
    logger.log(f"Confidence  : {characterisation.get('confidence')}")
    logger.log(f"Profile     : {profile.display_name}", "success")

    return profile

# ─────────────────────────────────────────────
# STAGE 1: EXTRACT PAPER METADATA
# ─────────────────────────────────────────────

def stage_1_extract_paper(
    questions_path: str,
    scheme_path: str | None,
    profile,
    anthropic_client,
    logger: PipelineLogger,
) -> dict:
    logger.stage("1 — Extract Paper Metadata")

    text = _get_first_pages_text(questions_path, anthropic_client, num_pages=3)
    prompt = profile.metadata_prompt(text)

    response = anthropic_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw   = profile.parse_claude_json(response.content[0].text)
    paper = validate_paper(raw)
    paper["question_pdf_path"] = questions_path
    paper["scheme_pdf_path"]   = scheme_path or ""

    logger.log(
        f"Extracted: {paper.get('paper_code')} | "
        f"{paper.get('exam_date')} | "
        f"{paper.get('total_marks')} marks",
        "success"
    )
    return paper


# ─────────────────────────────────────────────
# STAGE 2: EXTRACT QUESTIONS
# ─────────────────────────────────────────────

def stage_2_extract_questions(
    questions_path: str,
    profile,
    anthropic_client,
    logger: PipelineLogger,
) -> list:
    logger.stage("2 — Extract Questions")

    text_by_page, detection, _ = _get_text_for_pdf(
        questions_path, anthropic_client, logger
    )
    full_text = build_full_text(text_by_page)

    # Pass 1 — discover all question IDs
    discover_prompt = profile.discover_questions_prompt(full_text)
    response = anthropic_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": discover_prompt}]
    )
    raw           = profile.parse_claude_json(response.content[0].text)
    question_list = validate_question_list(raw)
    logger.log(f"Discovered {len(question_list)} questions")

    # Pass 2 — extract full details one question at a time
    questions = []
    failed    = []

    for q_info in question_list:
        simple_id = q_info["simple_id"]
        try:
            extract_prompt = profile.extract_question_prompt(full_text, q_info)
            response = anthropic_client.messages.create(
                model="claude-opus-4-6",
                max_tokens=1000,
                messages=[{"role": "user", "content": extract_prompt}]
            )
            raw      = profile.parse_claude_json(response.content[0].text)
            question = validate_question(raw)
            questions.append(question)
            logger.log(
                f"Extracted {simple_id} ({q_info.get('total_marks')} marks)",
                "success"
            )
        except Exception as e:
            failed.append(simple_id)
            logger.log(f"Failed {simple_id}: {e}", "error")

    logger.log(f"Questions: {len(questions)}/{len(question_list)} extracted")
    if failed:
        logger.log(f"Failed: {failed}", "warning")

    return questions


# ─────────────────────────────────────────────
# STAGE 3: EXTRACT SCHEMES
# ─────────────────────────────────────────────

def _detect_question_pages(text_by_page: dict, question_ids: list) -> dict:
    """
    Scan every page of the mark scheme for question number patterns.
    Returns { simple_id: [page_numbers] }
    Handles both '1(a)' and '1 (a)' formats.
    """
    def make_pattern(simple_id: str):
        if len(simple_id) > 1 and simple_id[-1].isalpha():
            number = simple_id[:-1]
            letter = simple_id[-1]
            return re.compile(
                rf'(?:^|\s){re.escape(number)}\s*\({letter}\)',
                re.IGNORECASE | re.MULTILINE
            )
        else:
            return re.compile(
                rf'(?:^|\s)Question\s+{re.escape(simple_id)}\b'
                rf'|(?:^|\s){re.escape(simple_id)}\s*\n',
                re.IGNORECASE | re.MULTILINE
            )

    sorted_pages = sorted(text_by_page.keys())
    first_page   = {}

    for simple_id in question_ids:
        pattern = make_pattern(simple_id)
        for page_num in sorted_pages:
            if pattern.search(text_by_page[page_num]):
                if simple_id not in first_page:
                    first_page[simple_id] = page_num

    # Forward-fill undetected questions from the next detected one
    for i, simple_id in enumerate(question_ids):
        if simple_id not in first_page:
            for j in range(i + 1, len(question_ids)):
                next_id = question_ids[j]
                if next_id in first_page:
                    first_page[simple_id] = first_page[next_id]
                    break

    # Build page ranges
    question_pages = {}
    found_ids = [qid for qid in question_ids if qid in first_page]

    for i, simple_id in enumerate(found_ids):
        start = first_page[simple_id]
        end   = sorted_pages[-1]
        for j in range(i + 1, len(found_ids)):
            next_start = first_page[found_ids[j]]
            if next_start > start:
                end = next_start - 1
                break
        question_pages[simple_id] = list(range(start, end + 1))

    return question_pages


def stage_3_extract_schemes(
    scheme_path: str,
    questions: list,
    profile,
    anthropic_client,
    logger: PipelineLogger,
) -> list:
    logger.stage("3 — Extract Marking Schemes")

    text_by_page, detection, _ = _get_text_for_pdf(
        scheme_path, anthropic_client, logger
    )

    question_ids  = [q["simple_id"] for q in questions]
    question_pages = _detect_question_pages(text_by_page, question_ids)

    not_found = [qid for qid in question_ids if qid not in question_pages]
    if not_found:
        logger.log(f"Page detection failed for: {not_found}", "warning")
    else:
        logger.log("Page ranges detected for all questions", "success")

    schemes = []
    failed  = []

    for question in questions:
        simple_id = question["simple_id"]
        pages     = question_pages.get(simple_id, [])

        if not pages:
            logger.log(f"Skipping {simple_id} — pages not detected", "warning")
            failed.append(simple_id)
            continue

        relevant_text = ""
        for p in pages:
            if p in text_by_page:
                relevant_text += f"\n--- PAGE {p} ---\n{text_by_page[p]}"

        if not relevant_text.strip():
            logger.log(f"Skipping {simple_id} — no text on pages {pages}", "warning")
            failed.append(simple_id)
            continue

        logger.log(
            f"Extracting scheme {simple_id} "
            f"(pages {pages}, {question.get('marking_style')}, "
            f"{question.get('total_marks')} marks)..."
        )

        try:
            prompt = profile.extract_scheme_prompt(relevant_text, question)
            response = anthropic_client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )
            raw    = profile.parse_claude_json(response.content[0].text)
            scheme = validate_scheme(raw)
            schemes.append(scheme)
            logger.log(f"Extracted scheme {simple_id}", "success")
        except Exception as e:
            failed.append(simple_id)
            logger.log(f"Failed scheme {simple_id}: {e}", "error")

    logger.log(f"Schemes: {len(schemes)}/{len(questions)} extracted")
    if failed:
        logger.log(f"Failed: {failed}", "warning")

    return schemes


# ─────────────────────────────────────────────
# STAGE 4: RECONCILE
# ─────────────────────────────────────────────

def stage_4_reconcile(
    questions: list,
    schemes: list,
    logger: PipelineLogger,
) -> dict:
    logger.stage("4 — Reconcile")

    q_ids = {q["simple_id"] for q in questions}
    s_ids = {s["simple_id"] for s in schemes}

    matched   = sorted(q_ids & s_ids)
    orphan_q  = sorted(q_ids - s_ids)
    orphan_s  = sorted(s_ids - q_ids)

    if orphan_q:
        logger.log(f"Questions without scheme: {orphan_q}", "warning")
    else:
        logger.log("All questions have a matching scheme", "success")

    if orphan_s:
        logger.log(f"Schemes without question: {orphan_s}", "warning")
    else:
        logger.log("All schemes have a matching question", "success")

    image_dependent = [
        q["simple_id"] for q in questions
        if q.get("requires_diagram")
    ]
    if image_dependent:
        logger.log(f"Image-dependent questions: {image_dependent}", "warning")

    status = "complete" if not orphan_q and not orphan_s else "partial"
    logger.log(f"Status: {status}", "success" if status == "complete" else "warning")

    return {
        "matched":          matched,
        "orphan_questions": orphan_q,
        "orphan_schemes":   orphan_s,
        "image_dependent":  image_dependent,
        "status":           status,
    }


# ─────────────────────────────────────────────
# BILLING SNAPSHOT
# ─────────────────────────────────────────────

def _billing_snapshot(
    questions_detection: dict,
    schemes_detection: dict | None,
) -> dict:
    """
    Compute page counts for billing.
    Returns counts of native and image pages across both PDFs.
    """
    def count_pages(detection):
        if not detection:
            return {"native": 0, "image": 0}
        pages = detection.get("pages", {})
        return {
            "native": sum(1 for t in pages.values() if t == "native"),
            "image":  sum(1 for t in pages.values() if t == "image"),
        }

    q_counts = count_pages(questions_detection)
    s_counts = count_pages(schemes_detection)

    return {
        "questions_pdf": q_counts,
        "schemes_pdf":   s_counts,
        "total_native":  q_counts["native"] + s_counts["native"],
        "total_image":   q_counts["image"]  + s_counts["image"],
    }


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_pipeline(
    questions_path: str,
    scheme_path: str | None,
    anthropic_client,
    log_callback=None,
) -> dict:
    """
    Run the full extraction pipeline for one paper.

    questions_path  — local file path to the questions PDF
    scheme_path     — local file path to the mark scheme PDF, or None
    anthropic_client — initialised anthropic.Anthropic() instance

    Returns a result dict:
    {
        "status":        "complete" | "partial" | "failed",
        "profile":       profile.exam_type,
        "paper":         { ...metadata... },
        "questions":     [ ...questions... ],
        "schemes":       [ ...schemes... ] or [],
        "reconciliation": { ... } or None,
        "artefacts":     { "schema.sql": "...", "data.json": "...", "insert.py": "..." },
        "billing":       { "total_native": N, "total_image": N, ... },
        "logs":          [ ...log entries... ],
        "error":         None | "error message",
    }
    """
    logger = PipelineLogger(log_callback=log_callback)
    result = {
        "status":         "failed",
        "profile":        None,
        "paper":          {},
        "questions":      [],
        "schemes":        [],
        "reconciliation": None,
        "artefacts":      {},
        "billing":        {},
        "logs":           logger.logs,
        "error":          None,
    }

    print(f"\n{'=' * 50}")
    print(f"  PIPELINE START")
    print(f"  Questions : {questions_path}")
    print(f"  Scheme    : {scheme_path or 'None'}")
    print(f"{'=' * 50}")

    try:
        # Stage 0 — detect exam type
        profile = stage_0_detect(questions_path, anthropic_client, logger)
        result["profile"] = profile.exam_type

        # Stage 1 — paper metadata
        paper = stage_1_extract_paper(
            questions_path, scheme_path, profile, anthropic_client, logger
        )
        result["paper"] = paper

        # Stage 2 — questions
        questions = stage_2_extract_questions(
            questions_path, profile, anthropic_client, logger
        )
        result["questions"] = questions

        # Stage 3 — schemes (only if profile requires them and scheme_path provided)
        schemes = []
        if profile.has_marking_schemes and scheme_path:
            schemes = stage_3_extract_schemes(
                scheme_path, questions, profile, anthropic_client, logger
            )
            result["schemes"] = schemes
        elif profile.has_marking_schemes and not scheme_path:
            logger.log("Profile expects schemes but no scheme_path provided", "warning")
        else:
            logger.log("No marking schemes for this exam type — skipping Stage 3", "info")

        # Stage 4 — reconcile (only if schemes were extracted)
        if schemes:
            reconciliation = stage_4_reconcile(questions, schemes, logger)
            result["reconciliation"] = reconciliation
            result["status"] = reconciliation["status"]
        else:
            result["status"] = "complete"

        # Output generation
        bundle = profile.to_output_bundle(paper, questions, schemes or None)
        gen    = OutputGenerator(profile, bundle)
        result["artefacts"] = gen.generate_all()

        summary = gen.summary()
        logger.log(
            f"Output generated — "
            f"{summary['questions_count']} questions, "
            f"{summary['schemes_count']} schemes",
            "success"
        )

        # Billing snapshot — re-detect both PDFs for page counts
        q_detection = detect_pdf_type(questions_path)
        s_detection = detect_pdf_type(scheme_path) if scheme_path else None
        result["billing"] = _billing_snapshot(q_detection, s_detection)

    except UnknownExamTypeError as e:
        result["status"] = "failed"
        result["error"]  = str(e)
        logger.log(f"Unknown exam type: {e}", "error")

    except Exception as e:
        result["status"] = "failed"
        result["error"]  = str(e)
        logger.log(f"Pipeline error: {e}", "error")
        logger.log(traceback.format_exc(), "error")

    print(f"\n{'=' * 50}")
    print(f"  PIPELINE COMPLETE — {result['status'].upper()}")
    print(f"{'=' * 50}\n")

    return result