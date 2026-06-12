"""
engine/profiles/generic.py — Generic fallback profile.

Used when no known profile matches the exam paper.
Makes no assumptions about structure, marking style, or schema.
Claude infers everything from what it actually sees.

This profile ensures the pipeline always completes for any exam type.
Profile-specific fields go into the 'extra' JSONB column in the
universal schema — nothing is discarded.
"""

import json
from datetime import datetime, timezone
from engine.base_profile import ExamProfile


class GenericProfile(ExamProfile):

    def __init__(self, characterisation: dict = None):
        """
        characterisation — the dict returned by stage0.characterise_paper().
        If None, the profile operates with zero prior knowledge.
        """
        self._char = characterisation or {}

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def exam_type(self) -> str:
        board   = self._char.get("exam_board", "unknown").lower().replace(" ", "_")
        subject = self._char.get("subject",    "unknown").lower().replace(" ", "_")
        return f"generic_{board}_{subject}"

    @property
    def display_name(self) -> str:
        board   = self._char.get("exam_board", "Unknown")
        subject = self._char.get("subject",    "Unknown")
        level   = self._char.get("level",      "")
        return f"{board} — {subject} {level}".strip(" —")

    @property
    def has_marking_schemes(self) -> bool:
        return self._char.get("has_marking_schemes", True)

    # ── Detection ─────────────────────────────────────────────────────────────

    def can_handle(self, text: str) -> bool:
        # Generic profile never self-selects — it is only assigned
        # by select_profile() as a fallback. Return False here so it
        # never accidentally wins in the registry loop.
        return False

    # ── Stage 1: Paper Metadata ───────────────────────────────────────────────

    def metadata_prompt(self, text: str) -> str:
        char_context = json.dumps(self._char, indent=2) if self._char else "No prior characterisation."

        return f"""You are extracting metadata from an exam paper PDF.

Prior characterisation of this paper:
{char_context}

Extract all available metadata and return a single JSON object.
Include every field you can find. At minimum try to populate:
{{
  "paper_code":             "as found or constructed from available info",
  "exam_board":             "as found",
  "subject":                "as found",
  "level":                  "as found",
  "year":                   2024,
  "exam_date":              "YYYY-MM-DD or null",
  "total_marks":            100,
  "time_allowed_minutes":   120,
  "sections":               [],
  "extra":                  {{}}
}}

Put any additional fields you find that don't fit the above into "extra".
Return ONLY the JSON object. No explanation, no markdown.

PAPER TEXT:
{text}
"""

    # ── Stage 2: Question Discovery ───────────────────────────────────────────

    def discover_questions_prompt(self, text: str) -> str:
        char_context = json.dumps(self._char, indent=2) if self._char else ""
        numbering    = self._char.get("numbering_convention", "")
        q_format     = self._char.get("question_format", "unknown")
        marking      = self._char.get("marking_style", "unknown")

        return f"""You are reading an exam paper. Your job is to find every question.

What we know about this paper:
- Question format: {q_format}
- Numbering convention: {numbering}
- Marking style: {marking}

List every question you find. Return a JSON array where each element has:
{{
  "simple_id":    "the question identifier exactly as it appears e.g. '1', '1a', 'Q3', 'A1'",
  "total_marks":  5,
  "marking_style": "points_based | levels_based | mcq | rubric — infer from context",
  "section":      "A or null if no sections",
  "extra":        {{}}
}}

Rules:
- Use the question identifier exactly as it appears in the paper.
- If marks are not explicitly stated per question, estimate from context or use null.
- For MCQ papers: list every individual question.
- For structured papers: list every part (e.g. 1a, 1b, 2a separately).
- Put anything unusual in "extra".
- Return ONLY the JSON array.

EXAM PAPER TEXT:
{text}
"""

    def extract_question_prompt(self, text: str, q_info: dict) -> str:
        simple_id    = q_info["simple_id"]
        total_marks  = q_info.get("total_marks", "unknown")
        marking      = q_info.get("marking_style", "unknown")
        q_format     = self._char.get("question_format", "unknown")

        return f"""You are extracting one question from an exam paper.

Extract question {simple_id} ONLY and return a single JSON object:
{{
  "simple_id":             "{simple_id}",
  "question_text":         "full question text exactly as written",
  "total_marks":           {total_marks if total_marks else "null"},
  "marking_style":         "{marking}",
  "question_type":         "mcq | short_answer | essay | calculation | diagram",
  "options":               {{"A": "...", "B": "...", "C": "...", "D": "..."}} or null,
  "correct_answer":        "A or null — only if answer key is visible",
  "requires_diagram":      false,
  "requires_calculation":  false,
  "topic":                 "infer from question content",
  "extra":                 {{}}
}}

Rules:
- options: populate only for MCQ questions, null otherwise.
- correct_answer: only if an answer key appears in this paper, otherwise null.
- Put any fields specific to this exam type in "extra".
- Return ONLY the JSON object.

EXAM PAPER TEXT:
{text}
"""

    # ── Stage 3: Scheme Extraction ────────────────────────────────────────────

    def extract_scheme_prompt(self, text: str, q_info: dict) -> str:
        simple_id   = q_info["simple_id"]
        total_marks = q_info.get("total_marks", "unknown")
        marking     = q_info.get("marking_style", "unknown")

        return f"""You are extracting a marking scheme for one question.

Extract the marking scheme for question {simple_id} ONLY.
Total marks: {total_marks}. Marking style: {marking}.

Return a single JSON object:
{{
  "simple_id":          "{simple_id}",
  "marking_style":      "{marking}",
  "max_marks":          {total_marks if total_marks else "null"},
  "mark_points":        ["each point that awards marks"],
  "level_descriptors":  [] or null,
  "model_answer":       "if a model answer is provided",
  "examiner_notes":     "any examiner guidance",
  "extra":              {{}}
}}

Rules:
- mark_points: bullet points or numbered points from the scheme.
- level_descriptors: for levels-based marking only, list each level with marks range.
- Put anything that doesn't fit above into "extra".
- Return ONLY the JSON object.

MARK SCHEME TEXT:
{text}
"""

    # ── Output Generation ─────────────────────────────────────────────────────

    def schema_sql(self) -> str:
        return _UNIVERSAL_SCHEMA_SQL

    def to_output_bundle(
        self,
        paper: dict,
        questions: list,
        schemes: list | None = None,
    ) -> dict:
        return {
            "meta": {
                "exam_type":       self.exam_type,
                "display_name":    self.display_name,
                "engine_version":  "1.0",
                "generated_at":    datetime.now(timezone.utc).isoformat(),
                "characterisation": self._char,
            },
            "paper":     paper,
            "questions": questions,
            "schemes":   schemes or [],
        }

    def insert_script(self, bundle: dict) -> str:
        return _universal_insert_script(bundle)


# ── Universal schema — works for any exam type ────────────────────────────────

_UNIVERSAL_SCHEMA_SQL = """
-- ── Universal Content Schema ──────────────────────────────────────────────────
-- Works for any exam type. Profile-specific fields go in 'extra' JSONB.
-- Safe to re-run (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS papers (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_type             TEXT,
    exam_board            TEXT,
    subject               TEXT,
    level                 TEXT,
    paper_code            TEXT,
    year                  INTEGER,
    exam_date             DATE,
    total_marks           INTEGER,
    time_allowed_minutes  INTEGER,
    sections              JSONB,
    question_pdf_path     TEXT,
    scheme_pdf_path       TEXT,
    processing_status     TEXT DEFAULT 'unprocessed',
    extra                 JSONB DEFAULT '{}',
    created_at            TIMESTAMPTZ DEFAULT now(),
    UNIQUE (paper_code, year, exam_board)
);

CREATE TABLE IF NOT EXISTS questions (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id              UUID REFERENCES papers(id) ON DELETE CASCADE,
    simple_id             TEXT NOT NULL,
    question_text         TEXT,
    question_type         TEXT,
    total_marks           INTEGER,
    marking_style         TEXT,
    section               TEXT,
    options               JSONB,
    correct_answer        TEXT,
    requires_diagram      BOOLEAN DEFAULT FALSE,
    requires_calculation  BOOLEAN DEFAULT FALSE,
    topic                 TEXT,
    extra                 JSONB DEFAULT '{}',
    created_at            TIMESTAMPTZ DEFAULT now(),
    UNIQUE (paper_id, simple_id)
);

CREATE TABLE IF NOT EXISTS schemes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id            UUID REFERENCES papers(id) ON DELETE CASCADE,
    simple_id           TEXT NOT NULL,
    marking_style       TEXT,
    max_marks           INTEGER,
    mark_points         JSONB,
    level_descriptors   JSONB,
    model_answer        TEXT,
    examiner_notes      TEXT,
    extra               JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (paper_id, simple_id)
);
"""


def _universal_insert_script(bundle: dict) -> str:
    return '''#!/usr/bin/env python3
"""
insert.py — Generated by Exam PDF Extraction Engine (Universal)
Usage     : DATABASE_URL=postgresql://... python insert.py
Reads data.json and inserts into the universal schema.
Safe to re-run — uses ON CONFLICT DO NOTHING.
"""

import json, os, sys
import psycopg2
from psycopg2.extras import RealDictCursor

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    print("ERROR: DATABASE_URL not set.")
    sys.exit(1)

with open("data.json") as f:
    bundle = json.load(f)

meta      = bundle["meta"]
paper     = bundle["paper"]
questions = bundle["questions"]
schemes   = bundle.get("schemes", [])

conn   = psycopg2.connect(DB_URL)
cursor = conn.cursor(cursor_factory=RealDictCursor)

print(f"Inserting paper: {paper.get(\'paper_code\')} {paper.get(\'year\')}")

extra_fields = {k: v for k, v in paper.items() if k not in (
    "exam_board","subject","level","paper_code","year","exam_date",
    "total_marks","time_allowed_minutes","sections",
    "question_pdf_path","scheme_pdf_path"
)}

cursor.execute("""
    INSERT INTO papers (
        exam_type, exam_board, subject, level, paper_code, year,
        exam_date, total_marks, time_allowed_minutes, sections,
        question_pdf_path, scheme_pdf_path, processing_status, extra
    ) VALUES (
        %(exam_type)s, %(exam_board)s, %(subject)s, %(level)s,
        %(paper_code)s, %(year)s, %(exam_date)s, %(total_marks)s,
        %(time_allowed_minutes)s, %(sections)s::jsonb,
        %(question_pdf_path)s, %(scheme_pdf_path)s,
        \'complete\', %(extra)s::jsonb
    )
    ON CONFLICT (paper_code, year, exam_board) DO NOTHING
    RETURNING id
""", {
    "exam_type":           meta.get("exam_type"),
    **paper,
    "sections":            json.dumps(paper.get("sections", [])),
    "extra":               json.dumps(extra_fields),
})

row = cursor.fetchone()
if not row:
    print("Paper already exists — skipping.")
    conn.close()
    sys.exit(0)

paper_id = row["id"]
print(f"  Paper ID: {paper_id}")

print(f"Inserting {len(questions)} questions...")
for q in questions:
    extra = {k: v for k, v in q.items() if k not in (
        "simple_id","question_text","question_type","total_marks",
        "marking_style","section","options","correct_answer",
        "requires_diagram","requires_calculation","topic"
    )}
    cursor.execute("""
        INSERT INTO questions (
            paper_id, simple_id, question_text, question_type,
            total_marks, marking_style, section, options,
            correct_answer, requires_diagram, requires_calculation,
            topic, extra
        ) VALUES (
            %(paper_id)s, %(simple_id)s, %(question_text)s, %(question_type)s,
            %(total_marks)s, %(marking_style)s, %(section)s, %(options)s::jsonb,
            %(correct_answer)s, %(requires_diagram)s, %(requires_calculation)s,
            %(topic)s, %(extra)s::jsonb
        )
        ON CONFLICT (paper_id, simple_id) DO NOTHING
    """, {
        **q,
        "paper_id": paper_id,
        "options":  json.dumps(q.get("options")),
        "extra":    json.dumps(q.get("extra", {})),
    })
    print(f"  Q {q[\'simple_id\']:<6} {(q.get(\'question_text\') or \'\')[:60]}")

print(f"Inserting {len(schemes)} schemes...")
for s in schemes:
    extra = {k: v for k, v in s.items() if k not in (
        "simple_id","marking_style","max_marks","mark_points",
        "level_descriptors","model_answer","examiner_notes"
    )}
    cursor.execute("""
        INSERT INTO schemes (
            paper_id, simple_id, marking_style, max_marks,
            mark_points, level_descriptors, model_answer,
            examiner_notes, extra
        ) VALUES (
            %(paper_id)s, %(simple_id)s, %(marking_style)s, %(max_marks)s,
            %(mark_points)s::jsonb, %(level_descriptors)s::jsonb,
            %(model_answer)s, %(examiner_notes)s, %(extra)s::jsonb
        )
        ON CONFLICT (paper_id, simple_id) DO NOTHING
    """, {
        **s,
        "paper_id":         paper_id,
        "mark_points":      json.dumps(s.get("mark_points", [])),
        "level_descriptors": json.dumps(s.get("level_descriptors")),
        "extra":            json.dumps(extra),
    })
    print(f"  S {s[\'simple_id\']:<6}")

conn.commit()
cursor.close()
conn.close()
print("\\nDone.")
'''