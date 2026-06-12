"""
engine/stage0.py — Exam characterisation.

Replaces the old detect_exam_type() hard-gate with a two-step process:

Step 1: Claude freely reads the first pages and characterises the paper
        — no assumptions, no predetermined categories.

Step 2: The characterisation is checked against the profile registry.
        If a known profile matches → use it (optimised prompts).
        If nothing matches → use GenericProfile (always succeeds).

The pipeline never fails at Stage 0 again.
"""

import json
from engine.profile_registry import PROFILES, UnknownExamTypeError
from engine.base_profile import ExamProfile


def characterise_paper(text: str, anthropic_client) -> dict:
    """
    Ask Claude to freely describe the exam paper from first-page text.
    Returns a characterisation dict — no predetermined categories.

    This is the only Stage 0 Claude call. It is cheap (small text,
    small response) and drives all downstream decisions.
    """
    prompt = f"""You are reading the first pages of an exam paper PDF.
Describe what you see and return ONLY a JSON object with these fields:

{{
  "exam_board":           "e.g. Pearson Edexcel, WAEC, Cambridge, JAMB, IB, NECO, or Unknown",
  "subject":              "e.g. Economics, Mathematics, English Language",
  "level":                "e.g. A Level, AS Level, UTME, WASSCE, IGCSE, or as stated",
  "question_format":      "mcq | structured | essay | mixed",
  "has_marking_schemes":  true,
  "marking_style":        "points_based | levels_based | mcq | rubric | unknown",
  "numbering_convention": "describe how questions are numbered e.g. '1, 2, 3', '1a 1b', 'Q1 Q2', 'Section A B C'",
  "sections":             ["A", "B"] or [] if no sections,
  "year":                 2024 or null,
  "paper_code":           "e.g. 9EC0/01 or null if not found",
  "confidence":           "high | medium | low",
  "notes":                "anything unusual about the structure worth knowing"
}}

Be descriptive and accurate. Do not force the paper into a category it doesn't fit.
If a field is genuinely unknown, use null.
Return ONLY the JSON object.

PAPER TEXT:
{text}
"""

    response = anthropic_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


def select_profile(characterisation: dict) -> ExamProfile:
    """
    Given a characterisation dict, try to match a known profile.
    Falls back to GenericProfile if nothing matches — never raises.

    Match logic: each profile's can_handle() receives a synthetic text
    string built from the characterisation fields, so profiles don't
    need to change their detection interface.
    """
    # Build a synthetic signal string from characterisation
    signal = " ".join(filter(None, [
        characterisation.get("exam_board", ""),
        characterisation.get("subject", ""),
        characterisation.get("level", ""),
        characterisation.get("paper_code", ""),
    ])).lower()

    for profile in PROFILES:
        try:
            if profile.can_handle(signal):
                return profile
        except Exception:
            continue

    # No known profile matched — use generic fallback
    from engine.profiles.generic import GenericProfile
    return GenericProfile(characterisation)


def run_stage0(text: str, anthropic_client) -> tuple:
    """
    Full Stage 0: characterise then select profile.

    Returns:
        (characterisation dict, ExamProfile instance)

    Never raises — worst case returns GenericProfile with low confidence.
    """
    try:
        characterisation = characterise_paper(text, anthropic_client)
    except Exception as e:
        # If Claude call itself fails, use a minimal characterisation
        characterisation = {
            "exam_board":          "Unknown",
            "subject":             "Unknown",
            "level":               "Unknown",
            "question_format":     "unknown",
            "has_marking_schemes": True,
            "marking_style":       "unknown",
            "numbering_convention": "unknown",
            "sections":            [],
            "year":                None,
            "paper_code":          None,
            "confidence":          "low",
            "notes":               f"Stage 0 characterisation failed: {e}",
        }

    profile = select_profile(characterisation)
    return characterisation, profile