#!/usr/bin/env python3
"""
jats_parser.py — Fetch and parse a PMC article's structured JATS XML, as an
alternative to PDF-to-Markdown conversion for open-access papers.

Why this exists: the PDF-to-Markdown path (pdf_to_md.py) hit an entire class
of bugs this project's calibration run surfaced — reference-list boundaries
bleeding into trailing correspondence/Supporting-Information text, running
headers spliced mid-sentence, author-affiliation superscripts misread as
citation markers, bold-markdown headings not matching the section-boundary
regex. All of those are consequences of PDF conversion destroying document
structure and needing to be reconstructed heuristically. JATS XML has real
structure — a <ref-list> with unambiguous boundaries, <body>/<sec>/<p>
elements instead of flat text, and <xref ref-type="bibr" rid="..."> tags
that ARE the citation markers rather than bracket-text that has to be
regex-guessed. Where a paper is available this way, prefer it.

Bonus: JATS reference entries frequently include the cited paper's DOI
directly (<pub-id pub-id-type="doi">) — when present, this skips
ref_resolver.py's Crossref bibliographic search entirely. A resolver that
never has to guess can't introduce a resolver bug.

Usage (as a library, from check_claims.py):
    data = fetch_and_parse(pmcid)
    data["body"]   # str, paragraphs joined by blank lines, citations as [n]
    data["refs"]   # {n: {"ref_text": str, "doi": str|None, "pmid": str|None}}
"""

import re
import time
from pathlib import Path
from typing import Optional, Dict, List
import xml.etree.ElementTree as ET

import requests

MAILTO = "phhung.y21@gmail.com"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

CACHE_DIR = Path(__file__).parent / "cache" / "jats"

# Elements whose content is not narrative prose — skip entirely rather than
# let table/figure text get spliced into a citing sentence (the exact bug
# that corrupted Kang 2022's ref-13 sentence in the PDF-to-Markdown path).
_SKIP_TAGS = {"table-wrap", "table", "fig", "graphic", "disp-formula", "media", "boxed-text"}


def _cache_path(pmcid: str) -> Path:
    return CACHE_DIR / f"{pmcid}.xml"


def fetch_jats_xml(pmcid: str) -> str:
    """Fetch + cache raw JATS XML for one PMC ID (numeric, no 'PMC' prefix)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(pmcid)
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    params = {"db": "pmc", "id": pmcid, "rettype": "xml", "retmode": "xml", "email": MAILTO}
    r = requests.get(EFETCH_URL, params=params, timeout=30)
    r.raise_for_status()
    text = r.text
    cache_path.write_text(text, encoding="utf-8")
    time.sleep(0.34)  # polite delay, ~3 req/sec
    return text


def _render_text(el: ET.Element, rid_to_num: Dict[str, int]) -> str:
    """Render an element's text content, converting <xref ref-type="bibr">
    into [n] markers (using our own ref-list numbering, not the visible
    citation text, which can be superscript digits or symbols) and
    dropping any nested table/figure content."""
    parts: List[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        if child.tag in _SKIP_TAGS:
            pass
        elif child.tag == "xref" and child.get("ref-type") == "bibr":
            rids = child.get("rid", "").split()
            nums = [rid_to_num[r] for r in rids if r in rid_to_num]
            if nums:
                parts.append("[" + ",".join(str(n) for n in nums) + "]")
        else:
            parts.append(_render_text(child, rid_to_num))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _collect_paragraphs(el: ET.Element, rid_to_num: Dict[str, int]) -> List[str]:
    """Walk the body tree, rendering each <p> as one paragraph. Does not
    descend into <p> once found (render_text already captures everything
    nested inside it) and skips table/figure subtrees outright."""
    if el.tag in _SKIP_TAGS:
        return []
    if el.tag == "p":
        text = re.sub(r"\s+", " ", _render_text(el, rid_to_num)).strip()
        return [text] if text else []
    out: List[str] = []
    for child in el:
        out.extend(_collect_paragraphs(child, rid_to_num))
    return out


def _parse_refs(article: ET.Element) -> Dict[int, dict]:
    refs: Dict[int, dict] = {}
    ref_els = article.findall(".//back//ref-list/ref")
    for i, ref in enumerate(ref_els):
        label_el = ref.find("label")
        num = None
        if label_el is not None and label_el.text:
            m = re.match(r"(\d+)", label_el.text.strip())
            if m:
                num = int(m.group(1))
        if num is None:
            num = i + 1

        citation_el = ref.find(".//mixed-citation")
        if citation_el is None:
            citation_el = ref.find(".//element-citation")
        source_el = citation_el if citation_el is not None else ref
        ref_text = re.sub(r"\s+", " ", "".join(source_el.itertext())).strip()

        doi_el = ref.find(".//pub-id[@pub-id-type='doi']")
        pmid_el = ref.find(".//pub-id[@pub-id-type='pmid']")

        refs[num] = {
            "ref_text": ref_text,
            "doi": doi_el.text.strip() if doi_el is not None and doi_el.text else None,
            "pmid": pmid_el.text.strip() if pmid_el is not None and pmid_el.text else None,
            "_rid": ref.get("id"),
        }
    return refs


def parse_jats(xml_text: str) -> Optional[dict]:
    """Parse one article's JATS XML. Returns None if no <article> found.

    Handles both root shapes: PMC efetch wraps articles in
    <pmc-articleset><article>...</article></pmc-articleset> (root.find(".//
    article") finds the nested element), while pandoc's `-t jats` writer
    emits <article> as the document root itself — ElementTree's ".//" only
    matches descendants, never the root, so that case needs an explicit
    self-check or it silently returns None for a perfectly valid document.
    """
    root = ET.fromstring(xml_text)
    article = root if root.tag == "article" else root.find(".//article")
    if article is None:
        return None

    doi_el = article.find(".//article-id[@pub-id-type='doi']")
    pmid_el = article.find(".//article-id[@pub-id-type='pmid']")
    pmcid_el = article.find(".//article-id[@pub-id-type='pmcid']")
    title_el = article.find(".//article-title")

    refs = _parse_refs(article)
    rid_to_num = {info["_rid"]: n for n, info in refs.items() if info["_rid"]}
    for info in refs.values():
        info.pop("_rid", None)

    body = article.find(".//body")
    paragraphs = _collect_paragraphs(body, rid_to_num) if body is not None else []

    return {
        "title": "".join(title_el.itertext()).strip() if title_el is not None else "",
        "doi": doi_el.text.strip() if doi_el is not None and doi_el.text else None,
        "pmid": pmid_el.text.strip() if pmid_el is not None and pmid_el.text else None,
        "pmcid": pmcid_el.text.strip() if pmcid_el is not None and pmcid_el.text else None,
        "body": "\n\n".join(paragraphs),
        "refs": refs,
    }


def fetch_and_parse(pmcid: str) -> Optional[dict]:
    xml_text = fetch_jats_xml(pmcid)
    return parse_jats(xml_text)
