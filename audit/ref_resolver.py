#!/usr/bin/env python3
"""
ref_resolver.py — Resolve a numbered reference-list entry (as it appears in a
published paper, with no DOI attached) to a Crossref DOI.

Published reference lists look like:
    14 Jia Z, Chang Y, Wang Y et al. Sustainable functional urethral
    reconstruction: Maximizing early continence recovery in robotic-assisted
    radical prostatectomy. Asian J Urol 2021; 8: 126-33

There is no DOI in that text. We query Crossref's bibliographic search with
the raw reference string and only accept the top hit if it clears a
confidence bar — otherwise the reference is reported unresolved rather than
guessed. Per CLAUDE.md's core rule (never invent DOIs/metadata), an
unresolved reference is a flag for manual lookup, not a best-effort DOI.

Confidence bar (both must hold):
    - extracted year (if any) from the raw ref text matches the candidate's
      Crossref year
    - the candidate's first author family name appears (case-insensitive)
      as a substring of the raw ref text
    - at least 70% of the candidate title's significant words (>3 chars)
      appear as substrings of the raw ref text

These thresholds are a heuristic, not a guarantee — tuned by hand against
real reference lists (see audit/NOTES.md). Treat "resolved" as "auto-matched
with high confidence," not "verified."
"""

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Optional, List, Dict

import requests

MAILTO = "phhung.y21@gmail.com"
CROSSREF_SEARCH_URL = "https://api.crossref.org/works"
HEADERS = {"User-Agent": f"citation-pipeline-audit/1.0 (mailto:{MAILTO})"}

CACHE_DIR = Path(__file__).parent / "cache" / "ref_resolution"

WORD_OVERLAP_THRESHOLD = 0.70


# ── Reference-list parsing ──────────────────────────────────────────────────
# Two kinds of contamination, handled differently:
#
# (1) TRUNCATE markers: once these appear, everything after is trailing paper
#     matter (correspondence block, abbreviation glossary, Supporting
#     Information index) that never resumes being reference-list content —
#     safe to cut everything from here to the end. Matters most for the LAST
#     reference, which has no following "N+1" marker to bound it. Found via
#     a real bug: ref 28 in Jia 2023 captured 2020 chars (true reference is
#     ~150) including a full Supporting Information table index, which fed
#     Crossref's search a query garbled enough to match an unrelated
#     cardiac-surgery paper instead of failing cleanly.
#
# (2) DELETE markers: short running-header/footer/copyright snippets that get
#     spliced INTO THE MIDDLE of a reference at a page-break, with legitimate
#     reference text (journal, year, pages) continuing right after them.
#     Truncating at these would discard that trailing text. Found via a real
#     bug: ref 21's captured text was "...posterior Rhabdosphincter
#     reconstruction in early urinary © 2022 The Authors. BJU International
#     published by John Wiley & Sons Ltd... 727 Jia et al. continence
#     recovery after robot-assisted radical prostatectomy. Eur Urol Oncol
#     2022; 5: 460-3" — truncating at "©" would have thrown away the journal/
#     year/pages and broken resolution (which is exactly what happened on
#     the first attempt at this fix).
_TRUNCATE_MARKERS = re.compile(
    r"(?i)(correspondence\s*:|correspondence\s+to|abbreviations\s*:|"
    r"supporting information|supplementary (material|information)|"
    r"appendix s\d|table s\d|figure s\d)"
)
_DELETE_MARKERS = re.compile(
    r"(?i)[©�]\s*20\d{2}\s+the authors\.?"
    r"|published by (john wiley|elsevier|wolters)[^.]*\."
    r"|wileyonlinelibrary\.com"
    r"|\b\d{2,4}\s+[A-Z][a-z]+ et al\."   # page-number + running-head author line
)


def _trim_contamination(text: str) -> str:
    m = _TRUNCATE_MARKERS.search(text)
    if m:
        text = text[:m.start()]
    text = _DELETE_MARKERS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_reference_list(md_text: str) -> Dict[int, str]:
    """Extract {n: raw reference text} from a '## References' section.

    Supports the common numbered-list formats seen from PDF-to-Markdown
    conversion: '- N ...' bullets and bare 'N. ...' / 'N ...' lines. Picks
    whichever pattern yields the most matches. Not universal — flagged as a
    known limitation (see audit/NOTES.md open questions).
    """
    # Headings sometimes come wrapped in markdown emphasis from PDF-to-MD
    # conversion (e.g. "## **REFERENCES**") — must match check_claims.py's
    # split_body_and_refs() pattern or the two disagree about where the
    # reference list starts. Found via a real bug: Kang 2022 parsed 0 refs.
    m = re.search(r"(?im)^#+\s*[*_]*\s*references\s*[*_]*\s*$", md_text)
    if not m:
        return {}
    section = md_text[m.end():]

    patterns = [
        r"(?m)^-\s*(\d+)\s+",     # "- 14 Author..."
        r"(?m)^(\d+)\.\s+",       # "14. Author..."
        r"(?m)^\[(\d+)\]\s*",     # "[14] Author..."
    ]
    best_entries: Dict[int, str] = {}
    for pat in patterns:
        matches = list(re.finditer(pat, section))
        if len(matches) <= len(best_entries):
            continue
        entries = {}
        for i, mm in enumerate(matches):
            num = int(mm.group(1))
            start = mm.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
            text = re.sub(r"\s+", " ", section[start:end]).strip()
            text = _trim_contamination(text)
            if text:
                entries[num] = text
        best_entries = entries
    return best_entries


# ── Crossref bibliographic search ────────────────────────────────────────────
def _cache_key(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:24]

def crossref_search(query: str) -> List[dict]:
    """Bibliographic search, cached by query hash (raw reference text can be
    long/messy — hashing avoids filesystem-unsafe filenames)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{_cache_key(query)}.json"
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)

    params = {"query.bibliographic": query, "rows": 5}
    r = requests.get(CROSSREF_SEARCH_URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    items = r.json().get("message", {}).get("items", [])

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    time.sleep(0.3)  # polite delay
    return items


# ── Confidence scoring ────────────────────────────────────────────────────────
def _extract_year(text: str) -> Optional[int]:
    m = re.search(r"\b((?:19|20)\d{2})\b", text)
    return int(m.group(1)) if m else None

def _candidate_year(msg: dict) -> Optional[int]:
    for field in ("published-print", "published-online", "issued"):
        parts = msg.get(field, {}).get("date-parts", [])
        if parts and parts[0]:
            return parts[0][0]
    return None

def _word_overlap(title: str, ref_text: str) -> float:
    words = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 3]
    if not words:
        return 0.0
    ref_lower = ref_text.lower()
    hits = sum(1 for w in words if w in ref_lower)
    return hits / len(words)

# Commentary/response articles ("Re: <original title>") are indexed by
# Crossref with near-identical titles to the paper they're responding to —
# high title-word-overlap, sometimes even matching year, but a different DOI
# and different (responding) authors. Found via a real bug: these out-ranked
# the actual cited paper for refs 1 and 16 in Jia 2023. Reject on title
# prefix before scoring rather than relying on author/year mismatch alone,
# since a "Re:" title inflates title_word_overlap enough that it can still
# slip past the other two checks if the responding author happens to share
# a surname, or the reply was published the same year.
_COMMENTARY_PREFIX = re.compile(r"(?i)^(re|reply to|response to|comment on)\s*[:.]")


def score_candidate(ref_text: str, msg: dict) -> dict:
    title = (msg.get("title") or [""])[0]

    if _COMMENTARY_PREFIX.match(title.strip()):
        return {
            "doi": msg.get("DOI", ""), "title": title,
            "year_match": False, "author_match": False, "title_word_overlap": 0.0,
            "confident": False, "rejected_reason": "commentary_article_title",
        }

    ref_year = _extract_year(ref_text)
    cand_year = _candidate_year(msg)
    year_match = ref_year is not None and cand_year is not None and ref_year == cand_year

    first_author = (msg.get("author") or [{}])[0].get("family", "")
    author_match = bool(first_author) and first_author.lower() in ref_text.lower()

    overlap = _word_overlap(title, ref_text)

    confident = year_match and author_match and overlap >= WORD_OVERLAP_THRESHOLD
    return {
        "doi": msg.get("DOI", ""),
        "title": title,
        "year_match": year_match,
        "author_match": author_match,
        "title_word_overlap": round(overlap, 2),
        "confident": confident,
    }


# Book-chapter citations ("Author. Title. In: Editor (Eds): Book Title
# Edition Year; pages.") are essentially never resolvable via Crossref's
# journal-article-focused bibliographic search — there is no journal article
# to find. Found via a real bug: "Walsh PC. Anatomic Radical Retropubic
# Prostatectomy. In: Walsh PC... Campbell's Urology 7th Edition 1998;
# 2565-88" resolved "successfully" to a DIFFERENT Walsh paper — a same-year,
# same-author, similarly-titled JOURNAL article ("Anatomic Radical
# Prostatectomy," J Urol 1998) — that cleared the confidence bar on title/
# author/year alone. The confidence bar checks textual similarity, not venue
# type, so it can't tell "this is close enough" from "this is the wrong
# paper by the same prolific author on the same topic." Refuse to even
# attempt these rather than risk exactly this kind of false-positive match.
_BOOK_CHAPTER_MARKER = re.compile(r"(?i)\bin:\s*[A-Z][a-zA-Z]+.{0,80}\(eds?\.?\)")


# ── Public entry point ────────────────────────────────────────────────────────
def resolve_reference(ref_text: str) -> dict:
    """Resolve one raw reference-list entry to a DOI, or report unresolved.

    Returns either:
        {"resolved": True, "doi": ..., "score": {...}}
        {"resolved": False, "reason": ..., "best_candidate": {...} | None}
    Never guesses — a low-confidence top hit is reported as unresolved with
    the candidate attached for manual review, not silently accepted.
    """
    if _BOOK_CHAPTER_MARKER.search(ref_text):
        return {"resolved": False, "reason": "Book chapter citation — not reliably resolvable via journal search", "best_candidate": None}

    try:
        candidates = crossref_search(ref_text)
    except requests.HTTPError as e:
        return {"resolved": False, "reason": f"Crossref search failed: {e}", "best_candidate": None}

    if not candidates:
        return {"resolved": False, "reason": "No Crossref candidates found", "best_candidate": None}

    scored = [score_candidate(ref_text, c) for c in candidates]

    # Crossref ranks by relevance, but the top hit is sometimes a "Re: <same
    # title>" commentary/response article (different DOI, different authors,
    # sometimes different year) rather than the original paper — check every
    # returned candidate for the confidence bar, not just the top one.
    for candidate in scored:
        if candidate["confident"]:
            return {"resolved": True, "doi": candidate["doi"], "score": candidate}

    return {"resolved": False, "reason": "No candidate cleared the confidence bar", "best_candidate": scored[0]}
