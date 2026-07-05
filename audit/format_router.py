#!/usr/bin/env python3
"""
format_router.py — Identify a manuscript's input format and normalize it to
the standardized dict shape used everywhere downstream:
    {"title", "doi", "pmid", "body", "refs", "low_confidence_spans",
     "conversion_source"}
where "refs" is {n: {"ref_text", "doi", "pmid"}} and "body" has [n]/[n,m]
citation markers inline (jats_parser.py's original convention, now shared by
every conversion path).

Dispatch by suffix:
    .xml            already JATS (e.g. a manually saved PMC file) — passthrough
    .pdf            GROBID (grobid_client.py) if reachable, else fall back to
                    the existing pymupdf4llm path (pdf_to_md.py), tagged
                    lower-confidence
    .docx/.tex/.html/.htm   pandoc_convert.py (pandoc -t jats)

.md is intentionally NOT routed through here — check_claims.py's existing
Markdown handling (split_body_and_refs, extract_claims) has years of
hand-tuned fixes for this project's specific pymupdf4llm-flavored output
(reference-list contamination, IQR-range false positives, running-header
splicing — see audit/NOTES.md) that operate on raw text directly. Routing
.md through a generic XML round-trip would regress all of that for zero
benefit, since .md is already a first-class, well-tested input. --pmcid
also stays a separate explicit CLI path in check_claims.py, since it fetches
by ID rather than dispatching on a local file's suffix.
"""

import re
from pathlib import Path
from typing import Optional

import jats_parser

# Same regex convention as check_claims.split_body_and_refs() — duplicated
# here rather than imported, since check_claims.py imports format_router.py
# and a reverse import would be a cycle. Used only for the PDF fallback path
# (pymupdf4llm output), which is plain markdown text just like the .md path.
_REFERENCES_HEADING_RE = re.compile(r"(?im)^#+\s*[*_]*\s*references\s*[*_]*\s*$")
_INTRO_HEADING_RE = re.compile(r"(?im)^#+\s*[*_]*\s*(introduction|background)\s*[*_]*\s*$")


def _markdown_text_to_standard_dict(md_text: str, conversion_source: str) -> dict:
    import ref_resolver as rr

    m = _REFERENCES_HEADING_RE.search(md_text)
    body = md_text[:m.start()] if m else md_text
    ref_section = md_text[m.start():] if m else ""

    intro_m = _INTRO_HEADING_RE.search(body)
    if intro_m:
        body = body[intro_m.end():]

    refs = rr.parse_reference_list(md_text)
    return {
        "title": "", "doi": None, "pmid": None,
        "body": body, "refs": refs,
        "low_confidence_spans": [],
        "conversion_source": conversion_source,
    }


def _route_pdf(path: Path) -> dict:
    import grobid_client
    import pdf_to_md

    result = grobid_client.convert(path)
    if result is not None:
        return result

    # GROBID unreachable — fall back to the existing pymupdf4llm path,
    # tagged so callers/flag reports can see this manuscript was processed
    # at lower structural fidelity (no real reference-list boundaries, no
    # real xref citation markers — same failure class documented at length
    # in audit/NOTES.md for the original 3-paper calibration).
    md_text = pdf_to_md.pdf_to_markdown(path)
    return _markdown_text_to_standard_dict(md_text, conversion_source="pymupdf4llm_fallback")


def _route_xml(path: Path) -> dict:
    xml_text = path.read_text(encoding="utf-8")
    parsed = jats_parser.parse_jats(xml_text)
    if parsed is None:
        raise ValueError(f"{path}: no <article> element found — not valid JATS XML")
    parsed.setdefault("low_confidence_spans", [])
    parsed["conversion_source"] = "jats_native"
    return parsed


def _route_pandoc(path: Path) -> dict:
    import pandoc_convert
    return pandoc_convert.convert(path)


_ROUTES = {
    ".xml": _route_xml,
    ".pdf": _route_pdf,
    ".docx": _route_pandoc,
    ".tex": _route_pandoc,
    ".html": _route_pandoc,
    ".htm": _route_pandoc,
}


def route(path: Path) -> dict:
    """The single entry point for any local-file manuscript. Raises
    ValueError for an unsupported suffix or a .md file (which has its own
    dedicated path in check_claims.py — see module docstring)."""
    suffix = path.suffix.lower()
    if suffix == ".md":
        raise ValueError(
            ".md is handled directly by check_claims.py, not format_router — "
            "see module docstring for why."
        )
    handler = _ROUTES.get(suffix)
    if handler is None:
        raise ValueError(f"Unsupported manuscript format: {suffix!r} ({path})")
    return handler(path)
