"""
engine/profiles/jamb.py — JAMB UTME profile.

Concrete ExamProfile for the Joint Admissions and Matriculation Board (JAMB)
Unified Tertiary Matriculation Examination (UTME).

Characteristics:
    - Pure MCQ: stem + 4 options (A-D) + correct answer
    - No marking schemes — answers embedded in question paper
    - Almost all JAMB PDFs are scanned → vision path is default
    - marking_style: "mcq"
    - Schema: jamb_papers, jamb_questions
"""

import json
from datetime import datetime, timezone
from engine.base_profile import ExamProfile


class JAMBProfile(ExamProfile):

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def exam_type(self) -> str:
        return "jamb"

    @property
    def display_name(self) -> str:
        return "JAMB UTME"

    @property
    def has_marking_schemes(self) -> bool:
        return False

    # ── Detection ─────────────────────────────────────────────────────────────

    def can_handle(self, text: str) -> bool:
        text_lower = text.lower()
        jamb_signals = [
            "joint admissions and matriculation",
            "jamb",
            "utme",
            "unified tertiary matriculation",
            "matriculation examination",
        ]
        return any(s in text_lower for s in jamb_signals)

    # ── Stage 1: Paper Metadata ───────────────────────────────────────────────

    def metadata_prompt(self, text: str) -> str:
        return f"""You are extracting structured metadata from a JAMB UTME exam paper PDF.

Extract the metadata and return a single JSON object with exactly these fields:
{{
  "paper_code":             "e.g. JAMB-UTME-2023-ECONOMICS",
  "exam_board":             "JAMB",
  "subject":                "e.g. Economics",
  "level":                  "UTME",
  "year":                   2023,
  "exam_date":              "YYYY-MM-DD or null if not found",
  "total_marks":            60,
  "time_allowed_minutes":   null,
  "total_questions":        60,
  "instructions":           "key instructions as a single string, or null"
}}

Rules:
- paper_code: construct as JAMB-UTME-{{YEAR}}-{{SUBJECT}} if not explicitly stated.
- total_marks: JAMB awards 1 mark per question. total_marks = total_questions.
- total_questions: count of MCQ questions in the paper. Default 60 if not stated.
- time_allowed_minutes: extract if stated, otherwise null.
- exam_date: use YYYY-MM-DD format. Use null if not found.
- Return ONLY the JSON object. No explanation, no markdown, no extra text.

PDF TEXT:
{text}
"""

    # ── Stage 2: Question Discovery ───────────────────────────────────────────

    def discover_questions_prompt(self, text: str) -> str:
        return f"""You are reading a JAMB UTME exam paper. It contains multiple choice questions.

List every question in the paper. Return a JSON array where each element has exactly these fields:
{{
  "simple_id":    "1",
  "total_marks":  1,
  "marking_style": "mcq"
}}

Rules:
- simple_id: the question number as a string e.g. "1", "2", "45"
- Every question is worth exactly 1 mark.
- marking_style is always "mcq" for JAMB.
- Return ONLY the JSON array. No explanation, no markdown, no extra text.

EXAM PAPER TEXT:
{text}
"""

    def extract_question_prompt(self, text: str, q_info: dict) -> str:
        simple_id = q_info["simple_id"]

        return f"""You are extracting question data from a JAMB UTME exam paper.

Extract question {simple_id} ONLY and return a single JSON object with exactly these fields:
{{
  "simple_id":      "{simple_id}",
  "question_text":  "full question stem exactly as written",
  "option_a":       "full text of option A",
  "option_b":       "full text of option B",
  "option_c":       "full text of option C",
  "option_d":       "full text of option D",
  "correct_answer": "A",
  "total_marks":    1,
  "marking_style":  "mcq",
  "topic":          "most relevant economic or subject concept",
  "explanation":    null
}}

Rules:
- question_text: the stem only, not the options.
- option_a through option_d: include the full option text, exclude the letter prefix.
- correct_answer: one of "A", "B", "C", "D". Extract from answer key if present
  on the same page or at the end of the paper. Use null if not found.
- explanation: extract if provided alongside the answer key, otherwise null.
- Return ONLY the JSON object. No explanation, no markdown, no extra text.

EXAM PAPER TEXT:
{text}
"""

    # ── Output Generation ─────────────────────────────────────────────────────

    def schema_sql(self) -> str:
        return """
-- ── JAMB UTME — Content Tables ──────────────────────────────────────────────
-- Run once on your target database. Safe to re-run (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS jamb_papers (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_code            TEXT NOT NULL UNIQUE,
    exam_board            TEXT NOT NULL DEFAULT 'JAMB',
    subject               TEXT NOT NULL,
    level                 TEXT NOT NULL DEFAULT 'UTME',
    year                  INTEGER NOT NULL,
    exam_date             DATE,
    total_marks           INTEGER,
    total_questions       INTEGER,
    time_allowed_minutes  INTEGER,
    instructions          TEXT,
    processing_status     TEXT DEFAULT 'unprocessed',
    created_at            TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jamb_questions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id        UUID REFERENCES jamb_papers(id) ON DELETE CASCADE,
    simple_id       TEXT NOT NULL,
    question_text   TEXT NOT NULL,
    option_a        TEXT,
    option_b        TEXT,
    option_c        TEXT,
    option_d        TEXT,
    correct_answer  TEXT CHECK (correct_answer IN ('A','B','C','D')),
    total_marks     INTEGER DEFAULT 1,
    marking_style   TEXT DEFAULT 'mcq',
    topic           TEXT,
    explanation     TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (paper_id, simple_id)
);
"""

    def to_output_bundle(
        self,
        paper: dict,
        questions: list,
        schemes: list | None = None,
    ) -> dict:
        return {
            "meta": {
                "exam_type":      self.exam_type,
                "display_name":   self.display_name,
                "engine_version": "1.0",
                "generated_at":   datetime.now(timezone.utc).isoformat(),
            },
            "paper":     paper,
            "questions": questions,
            "schemes":   None,
        }

    def insert_script(self, bundle: dict) -> str:
        return '''#!/usr/bin/env python3
"""
insert.py — Generated by Exam PDF Extraction Engine
Exam type : JAMB UTME
Usage     : DATABASE_URL=postgresql://... python insert.py

Reads data.json in the same directory and inserts into Postgres.
Safe to re-run — uses ON CONFLICT DO NOTHING.
"""

import json
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    print("ERROR: DATABASE_URL environment variable not set.")
    sys.exit(1)

with open("data.json") as f:
    bundle = json.load(f)

paper     = bundle["paper"]
questions = bundle["questions"]

conn   = psycopg2.connect(DB_URL)
cursor = conn.cursor(cursor_factory=RealDictCursor)

print(f"Inserting paper: {paper.get(\'paper_code\')} {paper.get(\'year\')}")

cursor.execute("""
    INSERT INTO jamb_papers (
        paper_code, exam_board, subject, level, year, exam_date,
        total_marks, total_questions, time_allowed_minutes,
        instructions, processing_status
    ) VALUES (
        %(paper_code)s, %(exam_board)s, %(subject)s, %(level)s, %(year)s,
        %(exam_date)s, %(total_marks)s, %(total_questions)s,
        %(time_allowed_minutes)s, %(instructions)s, \'complete\'
    )
    ON CONFLICT (paper_code) DO NOTHING
    RETURNING id
""", paper)

row = cursor.fetchone()
if not row:
    print("Paper already exists — skipping questions.")
    conn.close()
    sys.exit(0)

paper_id = row["id"]
print(f"  Paper ID: {paper_id}")

print(f"Inserting {len(questions)} questions...")
for q in questions:
    cursor.execute("""
        INSERT INTO jamb_questions (
            paper_id, simple_id, question_text,
            option_a, option_b, option_c, option_d,
            correct_answer, total_marks, marking_style,
            topic, explanation
        ) VALUES (
            %(paper_id)s, %(simple_id)s, %(question_text)s,
            %(option_a)s, %(option_b)s, %(option_c)s, %(option_d)s,
            %(correct_answer)s, %(total_marks)s, %(marking_style)s,
            %(topic)s, %(explanation)s
        )
        ON CONFLICT (paper_id, simple_id) DO NOTHING
    """, {**q, "paper_id": paper_id})
    print(f"  Q{q[\'simple_id\']:<4} {q[\'question_text\'][:60]}...")

conn.commit()
cursor.close()
conn.close()
print("\\nDone.")
'''