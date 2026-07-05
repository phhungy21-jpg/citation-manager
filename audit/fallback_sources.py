#!/usr/bin/env python3
"""
fallback_sources.py — Escalating fallback title/author/year search, tried in
order only when Crossref's exact/fuzzy title match (ref_resolver.py) fails to
clear its confidence bar. Stop at first hit — never blend or rank across
sources.

Order: Semantic Scholar -> DataCite -> arXiv/bioRxiv/medRxiv -> CORE.

Semantic Scholar and DataCite need no API key. CORE requires one
(CORE_API_KEY env var) — if unset, core_search() returns None immediately
(logged as "skipped, no key"), the same fail-closed posture llm_client.py
uses for ANTHROPIC_API_KEY. Never guesses a match — each function returns
either a well-formed {"doi": ..., "title": ...} dict for a found record, or
None.

Every raw API response is cached by a hash of the query, same convention as
ref_resolver.crossref_search(), under audit/cache/fallback/<source>/.
"""

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests

MAILTO = "phhung.y21@gmail.com"
HEADERS = {"User-Agent": f"citation-pipeline-audit/1.0 (mailto:{MAILTO})"}

CACHE_ROOT = Path(__file__).parent / "cache" / "fallback"


def _cache_path(source: str, query: str) -> Path:
    d = CACHE_ROOT / source
    d.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(query.encode("utf-8")).hexdigest()[:24]
    return d / f"{key}.json"


def _cached_get(source: str, query: str, url: str, params: dict, headers: Optional[dict] = None) -> Optional[dict]:
    cache_path = _cache_path(source, query)
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    try:
        r = requests.get(url, params=params, headers=headers or HEADERS, timeout=30)
        if r.status_code == 404:
            data = None
        else:
            r.raise_for_status()
            data = r.json()
    except Exception:
        return None
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    time.sleep(0.3)
    return data


def _normalize(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", title.lower()))


def _title_overlap(candidate_title: str, query_text: str) -> float:
    """Fraction of candidate_title's significant words (>3 chars) that appear
    in query_text. query_text is the raw reference string (or bare title) the
    caller is trying to resolve — same "words this way" convention as
    ref_resolver.score_candidate()'s word_overlap check."""
    words = [w for w in _normalize(candidate_title).split() if len(w) > 3]
    if not words:
        return 0.0
    query_words = set(_normalize(query_text).split())
    return sum(1 for w in words if w in query_words) / len(words)


# ── Semantic Scholar ─────────────────────────────────────────────────────────
def semantic_scholar_search(title: str, year: Optional[int] = None) -> Optional[dict]:
    query = f"ss::{title}::{year or ''}"
    data = _cached_get(
        "semantic_scholar", query,
        "https://api.semanticscholar.org/graph/v1/paper/search",
        {"query": title, "fields": "title,externalIds,year", "limit": 5},
    )
    if not data:
        return None
    for paper in data.get("data", []):
        cand_title = paper.get("title") or ""
        if _title_overlap(cand_title, title) < 0.85:
            continue
        if year and paper.get("year") and abs(int(paper["year"]) - year) > 1:
            continue
        doi = (paper.get("externalIds") or {}).get("DOI")
        if doi:
            return {"doi": doi, "title": cand_title}
    return None


# ── DataCite ─────────────────────────────────────────────────────────────────
def datacite_search(title: str, year: Optional[int] = None) -> Optional[dict]:
    query = f"datacite::{title}::{year or ''}"
    data = _cached_get(
        "datacite", query,
        "https://api.datacite.org/dois",
        {"query": title, "page[size]": 5},
    )
    if not data:
        return None
    for item in data.get("data", []):
        attrs = item.get("attributes", {})
        titles = attrs.get("titles") or []
        cand_title = titles[0].get("title", "") if titles else ""
        if _title_overlap(cand_title, title) < 0.85:
            continue
        pub_year = attrs.get("publicationYear")
        if year and pub_year and abs(int(pub_year) - year) > 1:
            continue
        doi = attrs.get("doi")
        if doi:
            return {"doi": doi, "title": cand_title}
    return None


# ── arXiv / bioRxiv / medRxiv preprints ──────────────────────────────────────
def _arxiv_search(title: str) -> Optional[dict]:
    query = f"arxiv::{title}"
    cache_path = _cache_path("arxiv", query)
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            xml_text = f.read()
    else:
        try:
            r = requests.get(
                "https://export.arxiv.org/api/query",
                params={"search_query": f'ti:"{title}"', "max_results": 5},
                headers=HEADERS, timeout=30,
            )
            r.raise_for_status()
            xml_text = r.text
        except Exception:
            return None
        cache_path.write_text(xml_text, encoding="utf-8")
        time.sleep(0.3)

    import xml.etree.ElementTree as ET
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    for entry in root.findall("atom:entry", ns):
        cand_title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        if _title_overlap(cand_title, title) < 0.85:
            continue
        doi_el = entry.find("arxiv:doi", ns)
        if doi_el is not None and doi_el.text:
            return {"doi": doi_el.text.strip(), "title": cand_title}
        arxiv_id_url = entry.findtext("atom:id", default="", namespaces=ns)
        m = re.search(r"arxiv\.org/abs/(.+)$", arxiv_id_url)
        if m:
            return {"doi": f"10.48550/arXiv.{m.group(1)}", "title": cand_title}
    return None


def _biorxiv_medrxiv_search(title: str, server: str) -> Optional[dict]:
    # bioRxiv/medRxiv's public API is DOI-lookup-oriented, not title-search —
    # there is no title-search endpoint. Left as a documented no-op rather
    # than guessing via a scraping workaround.
    return None


def preprint_search(title: str, year: Optional[int] = None) -> Optional[dict]:
    result = _arxiv_search(title)
    if result:
        return result
    for server in ("biorxiv", "medrxiv"):
        result = _biorxiv_medrxiv_search(title, server)
        if result:
            return result
    return None


# ── CORE (requires CORE_API_KEY) ─────────────────────────────────────────────
def core_search(title: str, year: Optional[int] = None) -> Optional[dict]:
    api_key = os.environ.get("CORE_API_KEY")
    if not api_key:
        print("  (fallback_sources.core_search: CORE_API_KEY not set — skipped)")
        return None

    query = f"core::{title}::{year or ''}"
    data = _cached_get(
        "core", query,
        "https://api.core.ac.uk/v3/search/works",
        {"q": title, "limit": 5},
        headers={**HEADERS, "Authorization": f"Bearer {api_key}"},
    )
    if not data:
        return None
    for item in data.get("results", []):
        cand_title = item.get("title") or ""
        if _title_overlap(cand_title, title) < 0.85:
            continue
        pub_year = item.get("yearPublished")
        if year and pub_year and abs(int(pub_year) - year) > 1:
            continue
        doi = item.get("doi")
        if doi:
            return {"doi": doi, "title": cand_title}
    return None
