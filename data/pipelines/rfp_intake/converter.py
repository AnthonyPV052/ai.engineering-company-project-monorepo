"""PDF → Markdown conversion and readability metrics.

Uses MarkItDown as the primary converter. Falls back to pypdf if
MarkItDown is unavailable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("rfp_intake.converter")


def pdf_to_markdown(pdf_path: str | Path) -> str:
    """Convert a PDF file to Markdown text.

    Uses MarkItDown if available (preferred), otherwise falls back to
    pypdf-based plain-text extraction wrapped in minimal Markdown.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Try MarkItDown first
    try:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(pdf_path))
        text_content = result.text_content
        if text_content and text_content.strip():
            logger.info("MarkItDown: converted %s (%d chars)", pdf_path.name, len(text_content))
            return text_content
        logger.warning("MarkItDown returned empty content for %s, falling back", pdf_path.name)
    except ImportError:
        logger.info("MarkItDown not available, using pypdf fallback")
    except Exception as exc:
        logger.warning("MarkItDown failed for %s: %s, falling back", pdf_path.name, exc)

    # Fallback: pypdf
    try:
        import pypdf

        reader = pypdf.PdfReader(str(pdf_path))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())

        full_text = "\n\n".join(pages)
        if not full_text.strip():
            raise ValueError(f"pypdf extracted no text from {pdf_path}")

        # Wrap in minimal Markdown
        lines = []
        for para in full_text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            # Simple heuristic: short lines become headings
            if len(para.split("\n")) == 1 and len(para) < 80 and para.isupper():
                lines.append(f"## {para.title()}")
            else:
                lines.append(para)

        md_text = "\n\n".join(lines)
        logger.info("pypdf fallback: converted %s (%d chars)", pdf_path.name, len(md_text))
        return md_text
    except ImportError:
        raise ImportError(
            "No PDF converter available. Install markitdown or pypdf."
        ) from None


def compute_readability_metrics(text: str) -> dict[str, float | int | None]:
    """Compute readability metrics using py-readability-metrics.

    Returns a dict with keys matching RFPMetadata fields, or None-values
    if the library is unavailable or the text is too short.
    """
    metrics: dict[str, float | int | None] = {
        "flesch_reading_ease": None,
        "flesch_kincaid_grade": None,
        "gunning_fog": None,
        "coleman_liau_index": None,
        "automated_readability_index": None,
        "word_count": None,
        "sentence_count": None,
    }

    if not text or len(text.split()) < 20:
        logger.warning("Text too short for readability metrics (%d words)", len(text.split()) if text else 0)
        return metrics

    try:
        from readability import Readability

        rd = Readability(text)

        metrics["flesch_reading_ease"] = round(rd.flesch().score, 2)
        metrics["flesch_kincaid_grade"] = round(float(rd.flesch_kincaid().grade_level), 2)
        metrics["gunning_fog"] = round(rd.gunning_fog().score, 2)
        metrics["coleman_liau_index"] = round(rd.coleman_liau().score, 2)
        metrics["automated_readability_index"] = round(rd.ari().score, 2)

        # Word and sentence counts
        words = text.split()
        metrics["word_count"] = len(words)

        import re
        sentences = re.split(r"[.!?]+", text)
        metrics["sentence_count"] = len([s for s in sentences if s.strip()])

        logger.info(
            "Readability: FK=%s GF=%s words=%d",
            metrics["flesch_kincaid_grade"], metrics["gunning_fog"], metrics["word_count"],
        )
    except ImportError:
        logger.warning("py-readability-metrics not available; skipping readability")
    except Exception as exc:
        logger.warning("Readability computation failed: %s", exc)

    return metrics