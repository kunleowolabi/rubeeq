"""
engine/vision_extractor.py — Image-based PDF extraction via Claude vision.

Handles PDFs (or individual pages) that pdfplumber cannot extract text from
because they are scanned or image-based.

Two-step process:
    1. pdf2image renders each page to a PIL Image
    2. Claude vision receives the image + a prompt and returns structured JSON

No Tesseract, no third-party OCR — Claude handles both reading and
structuring in a single call per page or per question.
"""

import base64
import io
import json
from PIL import Image
from pdf2image import convert_from_path
from engine.base_profile import ExamProfile


# ── Image helpers ─────────────────────────────────────────────────────────────

def _render_pdf_pages(pdf_path: str, dpi: int = 200) -> dict:
    """
    Render all pages of a PDF to PIL Images.
    Returns { page_number (1-indexed): PIL.Image }
    DPI 200 is the sweet spot — readable by Claude, not excessively large.
    """
    images = convert_from_path(pdf_path, dpi=dpi)
    return {i + 1: img for i, img in enumerate(images)}


def _render_specific_pages(pdf_path: str, page_numbers: list, dpi: int = 200) -> dict:
    """
    Render only the specified pages. More efficient than rendering all
    when we only need a subset (e.g. for single question extraction).
    page_numbers is 1-indexed.
    """
    first = min(page_numbers)
    last  = max(page_numbers)
    images = convert_from_path(
        pdf_path,
        dpi=dpi,
        first_page=first,
        last_page=last,
    )
    result = {}
    for i, img in enumerate(images, start=first):
        if i in page_numbers:
            result[i] = img
    return result


def _image_to_base64(image: Image.Image) -> str:
    """Convert a PIL Image to a base64-encoded JPEG string for the Claude API."""
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    return base64.standard_b64encode(buffer.read()).decode("utf-8")


def _images_to_content_blocks(images: dict) -> list:
    """
    Convert a dict of { page_num: PIL.Image } to a list of Claude API
    content blocks, interleaved with page marker text blocks.

    Returns a list ready to be passed as the 'content' field in a
    Claude messages API call.
    """
    blocks = []
    for page_num in sorted(images.keys()):
        blocks.append({
            "type": "text",
            "text": f"--- PAGE {page_num} ---"
        })
        blocks.append({
            "type": "image",
            "source": {
                "type":       "base64",
                "media_type": "image/jpeg",
                "data":       _image_to_base64(images[page_num]),
            }
        })
    return blocks


# ── Vision extraction calls ───────────────────────────────────────────────────

def extract_text_from_images(
    images: dict,
    anthropic_client,
) -> dict:
    """
    OCR-only pass: extract raw text from image pages via Claude vision.
    Used when we need the text content of image pages for further processing.

    Returns { page_number: extracted_text }
    """
    content_blocks = _images_to_content_blocks(images)
    content_blocks.append({
        "type": "text",
        "text": (
            "Extract all text from these PDF pages exactly as it appears. "
            "Preserve question numbers, marks, and layout cues. "
            "For each page, prefix the text with the page marker shown above it. "
            "Return plain text only — no JSON, no markdown."
        )
    })

    response = anthropic_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": content_blocks}]
    )

    raw = response.content[0].text
    result = {}
    current_page = None
    current_lines = []

    for line in raw.splitlines():
        if line.startswith("--- PAGE") and line.endswith("---"):
            if current_page is not None:
                result[current_page] = "\n".join(current_lines).strip()
            try:
                current_page = int(line.replace("--- PAGE", "").replace("---", "").strip())
            except ValueError:
                pass
            current_lines = []
        else:
            current_lines.append(line)

    if current_page is not None:
        result[current_page] = "\n".join(current_lines).strip()

    return result


def extract_structured_from_images(
    images: dict,
    prompt: str,
    anthropic_client,
    max_tokens: int = 4000,
) -> dict | list:
    """
    Structure extraction pass: send image pages + a profile prompt to Claude
    vision and return parsed JSON.

    This is the main entry point for image-based question and scheme extraction.
    The prompt comes from the profile (same interface as text-based extraction).

    Returns parsed JSON (dict or list depending on prompt).
    """
    content_blocks = _images_to_content_blocks(images)
    content_blocks.append({
        "type": "text",
        "text": prompt
    })

    response = anthropic_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content_blocks}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


def extract_first_pages_vision(
    pdf_path: str,
    anthropic_client,
    num_pages: int = 2,
) -> str:
    """
    Extract plain text from the first N pages of an image-based PDF.
    Used by Stage 0 (exam type detection) when the PDF is fully image-based.
    Returns concatenated text string matching the format of
    pdf_detector.extract_first_pages_text().
    """
    images = _render_specific_pages(pdf_path, list(range(1, num_pages + 1)))
    text_by_page = extract_text_from_images(images, anthropic_client)

    result = ""
    for page_num in sorted(text_by_page.keys()):
        result += f"\n--- PAGE {page_num} ---\n{text_by_page[page_num]}"
    return result


# ── Page counting for billing ─────────────────────────────────────────────────

def count_image_pages(detection_result: dict) -> int:
    """
    Count how many pages are image-based in a detection result.
    Used by the billing layer to apply the higher image-page rate.
    detection_result is the dict returned by pdf_detector.detect_pdf_type().
    """
    return sum(
        1 for ptype in detection_result["pages"].values()
        if ptype == "image"
    )