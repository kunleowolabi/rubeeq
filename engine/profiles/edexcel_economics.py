"""
engine/profiles/edexcel_economics.py — Pearson Edexcel A-Level Economics profile.

Concrete ExamProfile implementation. Contains all Edexcel-specific knowledge:
prompts, marking style logic, schema, and output generation.

Refactored from the original pipeline.py — no behaviour changes, just
reorganised so the engine can call it through the standard ExamProfile interface.
"""

import json
from datetime import datetime, timezone
from engine.base_profile import ExamProfile


class EdexcelEconomicsProfile(ExamProfile):

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def exam_type(self) -> str:
        return "edexcel_economics"

    @property
    def display_name(self) -> str:
        return "Pearson Edexcel A-Level Economics"

    @property
    def has_marking_schemes(self) -> bool:
        return True

    # ── Detection ─────────────────────────────────────────────────────────────

    def can_handle(self, text: str) -> bool:
        text_lower = text.lower()
        edexcel_signals = [
            "pearson edexcel",
            "edexcel",
            "9ec0",
            "8ec0",
            "economics a",
            "economics b",
        ]
        level_signals = [
            "a level",
            "a-level",
            "as level",
            "gce advanced",
        ]
        has_edexcel = any(s in text_lower for s in edexcel_signals)
        has_level   = any(s in text_lower for s in level_signals)
        return has_edexcel and has_level

    # ── Stage 1: Paper Metadata ───────────────────────────────────────────────

    def metadata_prompt(self, text: str) -> str:
        char  = self.get_characterisation()
        hints = ""
        if char:
            hints = f"""
Prior characterisation of this paper:
- Exam board : {char.get('exam_board', 'Pearson Edexcel')}
- Subject    : {char.get('subject', 'Economics')}
- Level      : {char.get('level', 'A Level')}
- Year       : {char.get('year', 'unknown')}
- Paper code : {char.get('paper_code', 'unknown')}
- Format     : {char.get('question_format', 'unknown')}
- Notes      : {char.get('notes', 'none')}
Use this to fill gaps where the text is ambiguous.
"""

        return f"""You are extracting structured metadata from a Pearson Edexcel exam paper PDF.
{hints}
Extract the metadata and return a single JSON object with exactly these fields:
{{
  "paper_code":             "e.g. 9EC0/03",
  "exam_board":             "e.g. Pearson Edexcel",
  "subject":                "e.g. Economics A",
  "level":                  "e.g. A Level",
  "year":                   2024,
  "exam_date":              "YYYY-MM-DD",
  "total_marks":            100,
  "time_allowed_minutes":   120,
  "sections": [
    {{"name": "A", "marks": 50}},
    {{"name": "B", "marks": 50}}
  ]
}}

Rules:
- sections: look for explicit section breakdowns. Default to [{{"name": "A", "marks": <total_marks>}}] if not found.
- exam_date: convert written date e.g. "Friday 7 June 2024" to YYYY-MM-DD.
- time_allowed_minutes: convert "X hours" to minutes.
- level: use "A Level" for GCE Advanced, "AS Level" for GCE AS.
- Return ONLY the JSON object. No explanation, no markdown, no extra text.

PDF TEXT:
{text}
"""

    # ── Stage 2: Question Discovery ───────────────────────────────────────────

    def discover_questions_prompt(self, text: str) -> str:
        char     = self.get_characterisation()
        sections = char.get("sections", [])
        notes    = char.get("notes", "")
        hints    = f"Sections detected: {sections}. {notes}" if char else ""

        return f"""You are reading a Pearson Edexcel A Level Economics exam paper.
{hints}

List every question in the paper. Return a JSON array where each element has exactly these fields:
{{
  "simple_id":     "1a",
  "section":       "A",
  "total_marks":   5,
  "marking_style": "points_based"
}}

marking_style rules — infer from the question's mark allocation and command words:
- Questions with AO point lists                        -> "points_based"
- Questions with KAA + Evaluation level bands          -> "hybrid"
- Questions with full level descriptor bands only      -> "levels_based"
- When uncertain, use "points_based" as default

Return ONLY the JSON array. No explanation, no markdown, no extra text.

EXAM PAPER TEXT:
{text}
"""

    def extract_question_prompt(self, text: str, q_info: dict) -> str:
        simple_id     = q_info["simple_id"]
        marking_style = q_info["marking_style"]
        total_marks   = q_info["total_marks"]
        section       = q_info["section"]

        if marking_style == "points_based":
            breakdown_instruction = """
    mark_breakdown: extract the actual AO allocation stated in the mark scheme or question.
    Look for explicit AO labels (AO1, AO2, AO3, AO4) or Knowledge/Application/Analysis/Evaluation labels.
    Return as {"knowledge": N, "application": N, "analysis": N, "evaluation": N, "total": N}.
    If not explicitly stated, distribute evenly and set "inferred": true."""

        elif marking_style == "hybrid":
            breakdown_instruction = """
    mark_breakdown: look for explicit KAA and Evaluation split stated in the question or mark scheme.
    Return as {"kaa_max": N, "evaluation_max": N, "total": N}.
    If not stated, use {"kaa_max": null, "evaluation_max": null, "total": TOTAL, "inferred": true}."""

        else:  # levels_based
            breakdown_instruction = """
    mark_breakdown: look for explicit KAA and Evaluation split stated in the question or mark scheme.
    Return as {"kaa_max": N, "evaluation_max": N, "total": N}.
    If not stated, use {"kaa_max": null, "evaluation_max": null, "total": TOTAL, "inferred": true}."""

        return f"""You are extracting question data from a Pearson Edexcel A Level Economics exam paper.

    Extract question {simple_id.upper()} ONLY and return a single JSON object with exactly these fields:
    {{
    "simple_id":             "{simple_id}",
    "question_number":       "e.g. 1(a)",
    "section":               "{section}",
    "question_text":         "full question text exactly as written",
    "question_type":         "short_answer | essay | calculation | diagram_required | choice",
    "total_marks":           {total_marks},
    "marking_style":         "{marking_style}",
    "mark_breakdown":        {{}},
    "requires_diagram":      false,
    "requires_calculation":  false,
    "is_optional":           false,
    "optional_group":        null,
    "context_references":    {{"figures": [], "extracts": [], "tables": [], "explicit": false}},
    "topic":                 "Microeconomics | Macroeconomics | Microeconomics and Macroeconomics",
    "subtopic":              "most relevant economic concept"
    }}

    Mark breakdown instruction:
    {breakdown_instruction}

    Rules:
    - question_type: one of "short_answer", "essay", "calculation", "diagram_required", "choice"
    - requires_diagram: true only if question explicitly asks student to draw a diagram
    - requires_calculation: true if question requires a numerical calculation
    - is_optional: true if part of an EITHER/OR choice
    - optional_group: e.g. "1d_or_1e" if is_optional, otherwise null
    - context_references: list any Figures, Extracts or Tables mentioned in the question text
    - Return ONLY the JSON object. No explanation, no markdown, no extra text.

    EXAM PAPER TEXT:
    {text}
    """
    

    # ── Stage 3: Scheme Extraction ────────────────────────────────────────────

    def extract_scheme_prompt(self, text: str, q_info: dict) -> str:
        simple_id     = q_info["simple_id"]
        marking_style = q_info["marking_style"]
        total_marks   = q_info["total_marks"]

        if marking_style == "points_based":
            breakdown_hint = """
- Set knowledge_marks_max, application_marks_max, analysis_marks_max from the mark scheme header
- Set kaa_marks_max and evaluation_marks_max to null
- level_descriptors: null
- indicative_content: extract ALL bullet points grouped by AO (knowledge, application, analysis, evaluation)
  Each point: {"text": "point text", "marks": 1}"""

        elif marking_style == "hybrid":
            breakdown_hint = """
- Set kaa_marks_max and evaluation_marks_max from the mark scheme
- Set knowledge_marks_max, application_marks_max, analysis_marks_max to null
- indicative_content: group bullet points under knowledge_points, application_points,
  analysis_points for KAA and evaluation_points for evaluation content
  Set "marks": 0 for each point. Ignore any diagram images — extract text only.
- level_descriptors: extract BOTH level tables (they appear on separate pages):
  kaa_levels: each level with marks_range [min, max] and descriptor text
  evaluation_levels: each level with marks_range [min, max] and descriptor text"""

        else:  # levels_based
            breakdown_hint = """
- Set kaa_marks_max and evaluation_marks_max from the mark scheme
- Set knowledge_marks_max, application_marks_max, analysis_marks_max to null
- indicative_content: extract all bullet points, set "marks": 0 for each
- level_descriptors: CRITICAL — extract BOTH tables which appear on separate pages:
  kaa_levels: levels 0-4, each with marks_range [min, max] and full descriptor text
  evaluation_levels: levels 0-3, each with marks_range [min, max] and full descriptor text
  Both tables MUST be populated — do not leave either as null."""

        return f"""You are extracting a marking scheme from a Pearson Edexcel A Level Economics mark scheme PDF.

Extract the marking scheme for question {simple_id.upper()} ONLY.
This is a {total_marks}-mark {marking_style} question.

Instructions:
{breakdown_hint}

Return a single JSON object with exactly these fields:
{{
  "simple_id": "{simple_id}",
  "marking_style": "{marking_style}",
  "kaa_marks_max": null,
  "evaluation_marks_max": null,
  "knowledge_marks_max": null,
  "application_marks_max": null,
  "analysis_marks_max": null,
  "indicative_content": {{
    "knowledge_points": [],
    "application_points": [],
    "analysis_points": [],
    "evaluation_points": []
  }},
  "level_descriptors": null,
  "diagram_marking": null
}}

Return ONLY the JSON object. No explanation, no markdown, no extra text.

MARK SCHEME TEXT (relevant pages only):
{text}
"""

    # ── Output Generation ─────────────────────────────────────────────────────

    def schema_sql(self) -> str:
        return """
-- ── Edexcel Economics — Content Tables ─────────────────────────────────────
-- Run once per target database. Safe to re-run (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS exam_papers (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_code              TEXT NOT NULL,
    exam_board              TEXT NOT NULL,
    subject                 TEXT NOT NULL,
    level                   TEXT,
    year                    INTEGER NOT NULL,
    exam_date               DATE,
    total_marks             INTEGER,
    time_allowed_minutes    INTEGER,
    sections                JSONB,
    question_pdf_path       TEXT,
    scheme_pdf_path         TEXT,
    processing_status       TEXT DEFAULT 'unprocessed',
    created_at              TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS questions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_paper_id           UUID REFERENCES exam_papers(id) ON DELETE CASCADE,
    parent_question_id      UUID REFERENCES questions(id),
    simple_id               TEXT NOT NULL,
    question_number         TEXT,
    section                 TEXT,
    question_text           TEXT,
    question_type           TEXT,
    total_marks             INTEGER,
    marking_style           TEXT,
    mark_breakdown          JSONB,
    requires_diagram        BOOLEAN DEFAULT FALSE,
    requires_calculation    BOOLEAN DEFAULT FALSE,
    is_optional             BOOLEAN DEFAULT FALSE,
    optional_group          TEXT,
    context_references      JSONB,
    topic                   TEXT,
    subtopic                TEXT,
    processing_status       TEXT DEFAULT 'pending',
    created_at              TIMESTAMPTZ DEFAULT now(),
    UNIQUE (exam_paper_id, simple_id)
);

CREATE TABLE IF NOT EXISTS marking_schemes (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_paper_id           UUID REFERENCES exam_papers(id) ON DELETE CASCADE,
    simple_id               TEXT NOT NULL,
    marking_style           TEXT,
    kaa_marks_max           INTEGER,
    evaluation_marks_max    INTEGER,
    knowledge_marks_max     INTEGER,
    application_marks_max   INTEGER,
    analysis_marks_max      INTEGER,
    indicative_content      JSONB,
    level_descriptors       JSONB,
    diagram_marking         TEXT,
    processing_status       TEXT DEFAULT 'pending',
    created_at              TIMESTAMPTZ DEFAULT now(),
    UNIQUE (exam_paper_id, simple_id)
);
"""

    def to_output_bundle(
        self,
        paper: dict,
        questions: list,
        schemes: list | None = None
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
            "schemes":   schemes or [],
        }

    def insert_script(self, bundle: dict) -> str:
        return '''#!/usr/bin/env python3
"""
insert.py — Generated by Exam PDF Extraction Engine
Exam type : Pearson Edexcel A-Level Economics
Usage     : DATABASE_URL=postgresql://... python insert.py

Reads questions.json in the same directory and inserts into Postgres.
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

with open("questions.json") as f:
    bundle = json.load(f)

paper     = bundle["paper"]
questions = bundle["questions"]
schemes   = bundle.get("schemes", [])

conn   = psycopg2.connect(DB_URL)
cursor = conn.cursor(cursor_factory=RealDictCursor)

print(f"Inserting paper: {paper.get(\'paper_code\')} {paper.get(\'year\')}")

cursor.execute("""
    INSERT INTO exam_papers (
        paper_code, exam_board, subject, level, year, exam_date,
        total_marks, time_allowed_minutes, sections,
        question_pdf_path, scheme_pdf_path, processing_status
    ) VALUES (
        %(paper_code)s, %(exam_board)s, %(subject)s, %(level)s, %(year)s, %(exam_date)s,
        %(total_marks)s, %(time_allowed_minutes)s, %(sections)s::jsonb,
        %(question_pdf_path)s, %(scheme_pdf_path)s, \'complete\'
    )
    ON CONFLICT DO NOTHING
    RETURNING id
""", {**paper, "sections": json.dumps(paper.get("sections", []))})

row = cursor.fetchone()
if not row:
    print("Paper already exists — skipping questions and schemes.")
    conn.close()
    sys.exit(0)

paper_id = row["id"]
print(f"  Paper ID: {paper_id}")

print(f"Inserting {len(questions)} questions...")
for q in questions:
    cursor.execute("""
        INSERT INTO questions (
            exam_paper_id, simple_id, question_number, section,
            question_text, question_type, total_marks, marking_style,
            mark_breakdown, requires_diagram, requires_calculation,
            is_optional, optional_group, context_references,
            topic, subtopic, processing_status
        ) VALUES (
            %(exam_paper_id)s, %(simple_id)s, %(question_number)s, %(section)s,
            %(question_text)s, %(question_type)s, %(total_marks)s, %(marking_style)s,
            %(mark_breakdown)s::jsonb, %(requires_diagram)s, %(requires_calculation)s,
            %(is_optional)s, %(optional_group)s, %(context_references)s::jsonb,
            %(topic)s, %(subtopic)s, \'matched\'
        )
        ON CONFLICT (exam_paper_id, simple_id) DO NOTHING
    """, {**q, "exam_paper_id": paper_id,
          "mark_breakdown": json.dumps(q.get("mark_breakdown", {})),
          "context_references": json.dumps(q.get("context_references", {}))})
    print(f"  Q {q[\'simple_id\']:<6} {q[\'total_marks\']} marks")

print(f"Inserting {len(schemes)} marking schemes...")
for s in schemes:
    cursor.execute("""
        INSERT INTO marking_schemes (
            exam_paper_id, simple_id, marking_style,
            kaa_marks_max, evaluation_marks_max,
            knowledge_marks_max, application_marks_max, analysis_marks_max,
            indicative_content, level_descriptors, processing_status
        ) VALUES (
            %(exam_paper_id)s, %(simple_id)s, %(marking_style)s,
            %(kaa_marks_max)s, %(evaluation_marks_max)s,
            %(knowledge_marks_max)s, %(application_marks_max)s, %(analysis_marks_max)s,
            %(indicative_content)s::jsonb, %(level_descriptors)s::jsonb, \'matched\'
        )
        ON CONFLICT (exam_paper_id, simple_id) DO NOTHING
    """, {**s, "exam_paper_id": paper_id,
          "indicative_content": json.dumps(s.get("indicative_content", {})),
          "level_descriptors": json.dumps(s.get("level_descriptors"))})
    print(f"  S {s[\'simple_id\']:<6} {s[\'marking_style\']}")

conn.commit()
cursor.close()
conn.close()
print("\\nDone.")
'''