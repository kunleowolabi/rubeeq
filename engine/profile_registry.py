"""
engine/profile_registry.py — Profile registry and exam type detection.

Maintains the ordered list of known ExamProfiles.
detect_exam_type() reads the first 2 pages of a PDF and returns
the matching profile. First match wins — order matters.

To add a new exam type:
    1. Create engine/profiles/your_profile.py
    2. Import it here
    3. Add an instance to PROFILES list
"""

from engine.profiles.edexcel_economics import EdexcelEconomicsProfile
from engine.profiles.jamb import JAMBProfile


# ── Registry — ordered, first match wins ─────────────────────────────────────

PROFILES = [
    EdexcelEconomicsProfile(),
    JAMBProfile(),
]


# ── Public API ────────────────────────────────────────────────────────────────

def detect_exam_type(text: str):
    """
    Direct profile lookup by text — used for testing and CLI tools.
    The pipeline now uses stage0.run_stage0() which never hard-fails.
    Raises UnknownExamTypeError if no profile matches.
    """
    for profile in PROFILES:
        if profile.can_handle(text):
            return profile
    raise UnknownExamTypeError(
        f"No registered profile recognises this exam paper.\n"
        f"First 200 chars of text: {text[:200]!r}"
    )


def list_profiles() -> list:
    """Return display names of all registered profiles."""
    return [p.display_name for p in PROFILES]


class UnknownExamTypeError(Exception):
    """Raised when no profile can handle the detected exam type."""
    pass