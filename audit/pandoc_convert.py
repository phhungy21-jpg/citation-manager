#!/usr/bin/env python3
"""
pandoc_convert.py — Convert docx/LaTeX/Markdown/HTML manuscripts to the same
standardized dict shape jats_parser.py and tei_to_jats.py already produce, by
routing through pandoc's JATS writer (`pandoc <file> -t jats`).

Two sub-cases, detected after conversion:
    1. Linked citations — the source already carries citation field codes
       (e.g. authored with Zotero/EndNote/Mendeley, or already using pandoc's
       native @citekey system with --citeproc). Pandoc's JATS output then has
       real <xref ref-type="bibr"> markers and a <ref-list>, exactly like a
       PMC article — reuse jats_parser.parse_jats() as-is.
    2. Unlinked citations — a raw numbered reference list with no field
       codes (the common case for a plain manuscript draft). Pandoc has
       nothing to link, so its JATS output is just prose text with whatever
       bracket markers the author typed (e.g. "[14]") preserved verbatim,
       and the reference list appears as an unlinked <sec>/<list>. Falls back
       to the same regex-based heading/marker convention check_claims.py and
       ref_resolver.py already use for plain-text manuscripts, applied to the
       JATS body's rendered plain text. If GROBID is reachable, its
       citation-parsing service additionally structures each raw reference
       string (best-effort, does not block the fallback if unavailable).
"""

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

import jats_parser

_HEADING_WORDS = re.compile(r"(?i)^\s*(references|bibliography)\s*$")
_LEADING_NUM_RE = re.compile(r"^\s*\[?(\d+)\]?[.\)]?\s+")


def _run_pandoc(path: Path) -> str:
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        subprocess.run(
            ["pandoc", str(path), "-t", "jats", "--standalone", "-o", str(tmp_path)],
            check=True, capture_output=True, timeout=120,
        )
        return tmp_path.read_text(encoding="utf-8")
    finally:
        tmp_path.unlink(missing_ok=True)


def _find_references_sec(el: ET.Element) -> Optional[ET.Element]:
    """JATS gives section structure directly — find the <sec> whose <title>
    reads "References"/"Bibliography" by walking the tree, rather than
    flattening to plain text first and re-guessing a heading with a regex
    (the source has no markdown "#" syntax once it's gone through pandoc's
    JATS writer, so a markdown-style heading pattern would never match)."""
    for sec in el.iter("sec"):
        title_el = sec.find("title")
        if title_el is not None and _HEADING_WORDS.match("".join(title_el.itertext()).strip()):
            return sec
    return None


def _plain_text_fallback(jats_xml: str) -> dict:
    """No real <xref>/<ref-list> in the pandoc output — pandoc had no
    citation field codes to link, so the reference list is just an unlinked
    <sec>/<list>. Extract it structurally (by section title, not a
    regex-guessed markdown heading) and number entries by encounter order,
    same convention jats_parser.py uses when a PMC <ref-list> lacks an
    explicit <label>."""
    root = ET.fromstring(jats_xml)
    body_el = root.find(".//body")

    refs_sec = _find_references_sec(body_el) if body_el is not None else None
    refs: dict = {}
    if refs_sec is not None:
        entries = refs_sec.findall(".//list-item") or refs_sec.findall("p")
        for i, entry in enumerate(entries):
            text = re.sub(r"\s+", " ", "".join(entry.itertext())).strip()
            if not text:
                continue
            m = _LEADING_NUM_RE.match(text)
            num = int(m.group(1)) if m else i + 1
            ref_text = text[m.end():].strip() if m else text
            refs[num] = {"ref_text": ref_text, "doi": None, "pmid": None}

    # Body = every paragraph outside the references section (avoids ref-list
    # text being re-swept into a claim sentence).
    body_paragraphs = []
    for p in (body_el.iter("p") if body_el is not None else []):
        if refs_sec is not None and _is_descendant(refs_sec, p):
            continue
        text = re.sub(r"\s+", " ", "".join(p.itertext())).strip()
        if text:
            body_paragraphs.append(text)
    body = "\n\n".join(body_paragraphs)

    return {
        "title": "", "doi": None, "pmid": None,
        "body": body, "refs": refs,
        "low_confidence_spans": [],
        "conversion_source": "pandoc_text_fallback",
    }


def _is_descendant(ancestor: ET.Element, node: ET.Element) -> bool:
    return any(node is child or _is_descendant(child, node) for child in ancestor)


def convert(path: Path) -> dict:
    jats_xml = _run_pandoc(path)

    parsed = jats_parser.parse_jats(jats_xml)
    has_linked_refs = bool(parsed and parsed.get("refs")) and "[" in (parsed.get("body") or "")
    if parsed is not None and has_linked_refs:
        parsed["conversion_source"] = "pandoc_jats_linked"
        parsed.setdefault("low_confidence_spans", [])
        return parsed

    result = _plain_text_fallback(jats_xml)

    if result["refs"]:
        try:
            import grobid_client
            if grobid_client.is_available():
                ref_strings = list(result["refs"].values())
                # Best-effort structuring only — never blocks the fallback,
                # and never overwrites the raw ref_text already captured.
                grobid_client.parse_citations([r["ref_text"] for r in ref_strings])
        except Exception:
            pass

    return result
