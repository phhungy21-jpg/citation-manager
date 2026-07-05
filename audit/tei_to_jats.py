#!/usr/bin/env python3
"""
tei_to_jats.py — Normalize GROBID's TEI XML output into the same standardized
dict shape jats_parser.py already produces for PMC JATS XML:
    {"title", "doi", "pmid", "body", "refs", "low_confidence_spans"}
where "refs" is {n: {"ref_text", "doi", "pmid"}} and "body" has [n] markers
inline, same convention as jats_parser._render_text().

GROBID's TEI is never treated as an audit-ready format on its own — this
module is the one-time normalization step so every downstream consumer
(check_claims.py, ref_resolver.py) only ever has to understand one shape,
regardless of whether the source was PMC JATS, GROBID TEI, or pandoc JATS.

Tables and figures are NOT read for content — per project decision, GROBID's
table/figure detection is comparatively weak, and this project has no
dedicated table/figure reading agent yet. Every <figure> (table or graphic)
found while walking the body is recorded into low_confidence_spans instead,
so callers know these sections exist but were not incorporated into `body`
and must not be trusted the way real prose is.
"""

import re
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}


def _q(tag: str) -> str:
    return f"{{{TEI_NS}}}{tag}"


def _xml_id(el: ET.Element) -> Optional[str]:
    """xml:id lives in the XML namespace, not the TEI namespace — a plain
    _q('id')/'id' lookup silently never matches, which breaks <ref
    target="#bN"> -> <biblStruct xml:id="bN"> linking without raising."""
    return el.get(f"{{{XML_NS}}}id")


def _render_text(el: ET.Element, rid_to_num: Dict[str, int], spans: List[dict]) -> str:
    """Mirrors jats_parser._render_text(): converts <ref type="bibr"
    target="#bN"> into [n] markers using our own ref-list numbering, and
    skips descending into table/figure content (recorded as a low-confidence
    span instead of spliced into the sentence)."""
    parts: List[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        tag = child.tag.split("}")[-1]
        if tag == "figure":
            kind = "table" if child.get("type") == "table" else "figure"
            spans.append({"type": kind, "location": _xml_id(child) or "unknown"})
        elif tag == "ref" and child.get("type") == "bibr":
            target = (child.get("target") or "").lstrip("#")
            num = rid_to_num.get(target)
            if num:
                parts.append(f"[{num}]")
        else:
            parts.append(_render_text(child, rid_to_num, spans))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _collect_paragraphs(el: ET.Element, rid_to_num: Dict[str, int], spans: List[dict]) -> List[str]:
    tag = el.tag.split("}")[-1]
    if tag == "figure":
        kind = "table" if el.get("type") == "table" else "figure"
        spans.append({"type": kind, "location": _xml_id(el) or "unknown"})
        return []
    if tag == "p":
        text = re.sub(r"\s+", " ", _render_text(el, rid_to_num, spans)).strip()
        return [text] if text else []
    out: List[str] = []
    for child in el:
        out.extend(_collect_paragraphs(child, rid_to_num, spans))
    return out


def _biblstruct_text(bibl: ET.Element) -> str:
    """Render a <biblStruct> reference entry as a flat human-readable
    string, close to what a published reference list would show — good
    enough input for ref_resolver's title/author/year extraction."""
    parts = []
    title_el = bibl.find(".//tei:title", NS)
    if title_el is not None and title_el.text:
        parts.append(title_el.text.strip())
    for author in bibl.findall(".//tei:author//tei:surname", NS):
        if author.text:
            parts.append(author.text.strip())
    date_el = bibl.find(".//tei:date", NS)
    if date_el is not None:
        when = date_el.get("when") or (date_el.text or "")
        m = re.search(r"(19|20)\d{2}", when)
        if m:
            parts.append(m.group(0))
    return " ".join(parts) if parts else "".join(bibl.itertext()).strip()


def _parse_refs(root: ET.Element) -> Dict[int, dict]:
    refs: Dict[int, dict] = {}
    bibl_structs = root.findall(".//tei:back//tei:listBibl/tei:biblStruct", NS)
    for i, bibl in enumerate(bibl_structs):
        num = i + 1
        doi_el = bibl.find(".//tei:idno[@type='DOI']", NS)
        pmid_el = bibl.find(".//tei:idno[@type='PMID']", NS)
        refs[num] = {
            "ref_text": _biblstruct_text(bibl),
            "doi": doi_el.text.strip() if doi_el is not None and doi_el.text else None,
            "pmid": pmid_el.text.strip() if pmid_el is not None and pmid_el.text else None,
            "_xml_id": _xml_id(bibl),
        }
    return refs


def tei_to_standard_dict(tei_xml: str) -> Optional[dict]:
    root = ET.fromstring(tei_xml)

    title_el = root.find(".//tei:teiHeader//tei:titleStmt/tei:title", NS)
    doi_el = root.find(".//tei:teiHeader//tei:sourceDesc//tei:idno[@type='DOI']", NS)

    refs = _parse_refs(root)
    rid_to_num = {info["_xml_id"]: n for n, info in refs.items() if info["_xml_id"]}
    for info in refs.values():
        info.pop("_xml_id", None)

    spans: List[dict] = []
    body_el = root.find(".//tei:text/tei:body", NS)
    paragraphs = _collect_paragraphs(body_el, rid_to_num, spans) if body_el is not None else []

    return {
        "title": (title_el.text or "").strip() if title_el is not None else "",
        "doi": doi_el.text.strip() if doi_el is not None and doi_el.text else None,
        "pmid": None,
        "body": "\n\n".join(paragraphs),
        "refs": refs,
        "low_confidence_spans": spans,
        "conversion_source": "grobid_tei",
    }
