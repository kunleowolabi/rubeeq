"""
engine/base_profile.py — Abstract base class for all exam profiles.

Every exam type (Edexcel Economics, JAMB, WAEC, etc.) implements this
interface. The pipeline calls these standard methods; the profile provides
all exam-specific knowledge — prompts, schema, output format.

Concrete profiles live in engine/profiles/
"""

from abc import ABC, abstractmethod


class ExamProfile(ABC):

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def exam_type(self) -> str:
        """
        Short machine-readable identifier.
        e.g. 'edexcel_economics', 'jamb', 'waec_economics'
        Used in output filenames, job records, and JSON envelope.
        """

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable name shown in logs and UI.
        e.g. 'Pearson Edexcel A-Level Economics'
        """

    @property
    @abstractmethod
    def has_marking_schemes(self) -> bool:
        """
        True  → pipeline runs Stage 3 (scheme extraction) + Stage 4 (reconciliation)
        False → pipeline skips both; output bundle has no schemes section
        e.g. Edexcel = True, JAMB = False (answers embedded in question)
        """

    # ── Detection ─────────────────────────────────────────────────────────────

    @abstractmethod
    def can_handle(self, text: str) -> bool:
        """
        Given the first 2 pages of a PDF as plain text, return True if
        this profile recognises the exam.

        Called by profile_registry.detect_exam_type() — first profile
        that returns True wins. Order in the registry matters.

        Keep this cheap: string checks only, no API calls.
        """

    # ── Stage 1: Paper Metadata ───────────────────────────────────────────────

    @abstractmethod
    def metadata_prompt(self, text: str) -> str:
        """
        Build the Claude prompt to extract paper-level metadata from
        the first 2-3 pages of the questions PDF.

        Must instruct Claude to return ONLY a JSON object.
        The engine parses the response directly with json.loads().

        Required fields in the returned JSON (all profiles must return these):
            paper_code, exam_board, subject, level, year (int),
            exam_date (YYYY-MM-DD), total_marks (int),
            time_allowed_minutes (int)

        Optional/profile-specific fields are allowed and will be stored
        in the output bundle's paper.extra dict.
        """

    # ── Stage 2: Question Discovery ───────────────────────────────────────────

    @abstractmethod
    def discover_questions_prompt(self, text: str) -> str:
        """
        Build the Claude prompt for Pass 1 of question extraction:
        discover all question IDs, marks, and any profile-specific
        classification (marking style, subject area, etc.).

        Must instruct Claude to return ONLY a JSON array.
        Each element must have at minimum:
            simple_id (str)   — unique within the paper, e.g. '1a', 'Q5'
            total_marks (int)

        Profile-specific fields (e.g. marking_style, section, option_letter)
        are passed straight through to extract_question_prompt().
        """

    @abstractmethod
    def extract_question_prompt(self, text: str, q_info: dict) -> str:
        """
        Build the Claude prompt for Pass 2: extract full details for
        ONE question identified in Pass 1.

        q_info is the dict returned for this question by Pass 1.
        text is the full paper text (all pages).

        Must instruct Claude to return ONLY a JSON object.
        """

    # ── Stage 3: Scheme Extraction (optional) ────────────────────────────────

    def extract_scheme_prompt(self, text: str, q_info: dict) -> str:
        """
        Build the Claude prompt to extract the marking scheme for ONE
        question from the mark scheme PDF.

        Only called when has_marking_schemes is True.
        Default raises NotImplementedError — profiles with schemes must override.

        text is the relevant pages for this question only.
        q_info is the question dict from Stage 2.
        """
        raise NotImplementedError(
            f"{self.display_name} declares has_marking_schemes=True "
            f"but has not implemented extract_scheme_prompt()"
        )

    # ── Output Generation ─────────────────────────────────────────────────────

    @abstractmethod
    def schema_sql(self) -> str:
        """
        Return the full CREATE TABLE SQL for this exam type's content tables.

        These are the *content* tables (questions, answers, schemes etc.)
        not the platform tables (jobs, billing — those are in platform/models.py).

        Should include IF NOT EXISTS so it's safe to run repeatedly.
        """

    @abstractmethod
    def to_output_bundle(
        self,
        paper: dict,
        questions: list,
        schemes: list | None = None
    ) -> dict:
        """
        Assemble the final output bundle dict from extracted data.

        Returns a dict with this envelope:
        {
            "meta": {
                "exam_type":       self.exam_type,
                "engine_version":  "1.0",
                "generated_at":    "<ISO timestamp>",
            },
            "paper":     { ...paper metadata... },
            "questions": [ ...per question... ],
            "schemes":   [ ...per scheme... ] or None
        }

        The engine passes this to OutputGenerator to produce
        schema.sql, questions.json, and insert.py.
        """

    @abstractmethod
    def insert_script(self, bundle: dict) -> str:
        """
        Return a self-contained Python script (as a string) that reads
        the questions.json output bundle and inserts it into a Postgres DB.

        The script must:
        - Accept DB connection string from environment variable DATABASE_URL
        - Be runnable standalone: python insert.py
        - Handle duplicates gracefully (ON CONFLICT DO NOTHING or equivalent)
        - Print progress as it inserts
        """

    # ── Shared Utility ────────────────────────────────────────────────────────

    def parse_claude_json(self, raw: str) -> dict | list:
        """
        Strip markdown fences from a Claude response and parse JSON.
        All profiles can use this — it handles the ```json ... ``` wrapper
        Claude sometimes adds despite being told not to.
        """
        import json
        text = raw.strip()
        if text.startswith("```"):
            parts = text.split("```")
            # parts[1] is the content between first and second ```
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())

    def __repr__(self) -> str:
        return f"<ExamProfile: {self.display_name}>"