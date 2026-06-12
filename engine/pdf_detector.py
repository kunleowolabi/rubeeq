"""
engine/pdf_detector.py — PDF type detection and text extraction.

Determines whether each page of a PDF is native (text-selectable)
or image-based (scanned), then extracts accordingly.

detect_pdf_type()     — returns per-page classification
extract_text()        — extracts text from native pages via pdfplumber
Pages below the character threshold are flagged for the vision path.
"""

import pdfplumber

# Pages with fewer extracted characters than this are treated as image-based.
# Covers pages that are scanned, or native but mostly diagrams/whitespace.
NATIVE_CHAR_THRESHOLD = 100


def detect_pdf_type(pdf_path: str) -> dict:
    """
    Classify every page in the PDF as 'native' or 'image'.

    Returns a dict: { page_number (1-indexed): 'native' | 'image' }

    Also returns a top-level 'pdf_type' key:
        'native' — all pages are native
        'image'  — all pages are image-based
        'mixed'  — combination of both
    """
    page_types = {}

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            char_count = len(text.strip())
            page_types[i] = "native" if char_count >= NATIVE_CHAR_THRESHOLD else "image"

    types = set(page_types.values())
    if types == {"native"}:
        pdf_type = "native"
    elif types == {"image"}:
        pdf_type = "image"
    else:
        pdf_type = "mixed"

    return {
        "pdf_type": pdf_type,
        "pages":    page_types,
    }


def extract_text_by_page(pdf_path: str) -> dict:
    """
    Extract text from all native pages of a PDF.

    Returns a dict: { page_number (1-indexed): text }
    Image-based pages are included with empty string values
    so page numbering stays consistent for the vision path.
    """
    result = {}

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            result[i] = text.strip()

    return result


def extract_first_pages_text(pdf_path: str, num_pages: int = 2) -> str:
    """
    Extract and concatenate text from the first N pages.
    Used by Stage 0 (exam type detection) and Stage 1 (paper metadata).
    Only pulls from native pages — image pages return empty string.
    """
    text = ""

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            if i > num_pages:
                break
            page_text = page.extract_text() or ""
            text += f"\n--- PAGE {i} ---\n{page_text.strip()}"

    return text


def build_full_text(text_by_page: dict) -> str:
    """
    Concatenate a text_by_page dict into a single string with page markers.
    Convenience function used by pipeline stages.
    """
    full_text = ""
    for page_num in sorted(text_by_page.keys()):
        full_text += f"\n--- PAGE {page_num} ---\n{text_by_page[page_num]}"
    return full_text


def get_page_count(pdf_path: str) -> int:
    """Return total number of pages. Used by billing layer."""
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)