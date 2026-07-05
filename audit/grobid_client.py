#!/usr/bin/env python3
"""
grobid_client.py — Thin client for a local GROBID service
(https://github.com/kermitt2/grobid), used to convert PDFs to structured
TEI XML instead of the flat-text pymupdf4llm path (pdf_to_md.py).

GROBID is not vendored or bundled — it's a separate Java service the user
runs themselves (typically via Docker: `docker run -p 8070:8070
lfoppiano/grobid:0.8.0`). This client only talks to it over HTTP and never
assumes it's running: every entry point checks `is_available()` first and
returns None on any failure so the caller (format_router.py) can fall back
to the pymupdf4llm path instead of erroring out.

GROBID's table/figure detection is not used for content extraction here —
per project decision, table/figure spans are only tagged as low-confidence
extension points (see tei_to_jats.py), not read. GROBID is comparatively
weak at table/figure content and this project has no dedicated reading
agent for them yet.
"""

import hashlib
import os
from pathlib import Path
from typing import Optional

import requests

GROBID_URL = os.environ.get("GROBID_URL", "http://localhost:8070")
CACHE_DIR = Path(__file__).parent / "cache" / "grobid"


def is_available(url: Optional[str] = None) -> bool:
    base = url or GROBID_URL
    try:
        r = requests.get(f"{base}/api/isalive", timeout=2)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _cache_path(pdf_path: Path) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:24]
    return CACHE_DIR / f"{digest}.tei.xml"


def fetch_tei(pdf_path: Path, url: Optional[str] = None) -> Optional[str]:
    """POST a PDF to GROBID's full-text extraction endpoint, cached by a
    hash of the PDF's own bytes (so re-running on the same file is free).
    Returns None if GROBID is unreachable or the call fails — caller must
    fall back, never treat None as an empty document."""
    base = url or GROBID_URL
    cache_path = _cache_path(pdf_path)
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    if not is_available(base):
        return None

    try:
        with open(pdf_path, "rb") as f:
            r = requests.post(
                f"{base}/api/processFulltextDocument",
                files={"input": (pdf_path.name, f, "application/pdf")},
                data={"consolidateCitations": "1", "includeRawCitations": "1"},
                timeout=180,
            )
        r.raise_for_status()
        tei_xml = r.text
    except requests.RequestException:
        return None

    cache_path.write_text(tei_xml, encoding="utf-8")
    return tei_xml


def parse_citations(raw_ref_strings: list, url: Optional[str] = None) -> dict:
    """GROBID's separate citation-parsing service (distinct from full-text
    extraction) — structures a list of raw, unlinked reference strings
    (e.g. from a pandoc-converted manuscript with no citation field codes)
    into {index: tei_biblStruct_xml}. Returns {} if GROBID is unreachable;
    caller falls back to leaving the references as raw text."""
    base = url or GROBID_URL
    if not is_available(base):
        return {}

    results = {}
    for i, ref_text in enumerate(raw_ref_strings):
        try:
            r = requests.post(
                f"{base}/api/processCitation",
                data={"citations": ref_text, "consolidateCitations": "1"},
                timeout=30,
            )
            r.raise_for_status()
            results[i] = r.text
        except requests.RequestException:
            continue
    return results


def convert(pdf_path: Path, url: Optional[str] = None) -> Optional[dict]:
    """Full PDF -> standardized-dict path: fetch TEI, normalize it. Returns
    None (caller falls back to pdf_to_md.py) if GROBID is unreachable or the
    TEI can't be parsed."""
    tei_xml = fetch_tei(pdf_path, url=url)
    if tei_xml is None:
        return None
    import tei_to_jats
    return tei_to_jats.tei_to_standard_dict(tei_xml)
