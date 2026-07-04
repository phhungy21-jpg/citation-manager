#!/usr/bin/env python3
"""
add_reference.py — Add a reference by DOI to the local CSL JSON library.

Pulls metadata from three sources and merges into one standardized,
backfilled record: Crossref (primary bibliographic data — title, authors,
journal, volume/issue/page), PubMed efetch (primary abstract source, PMID),
and OpenAlex (fallback for whatever the other two are missing). A source
that has nothing for a field is simply skipped in the backfill chain — no
field is ever invented.

Usage:
    python add_reference.py 10.1111/bju.15956
    python add_reference.py https://doi.org/10.1111/bju.15956

Output files (in the same directory as this script, or CITATION_DIR env var):
    library.csl.json     Pandoc-compatible bibliography (use with --citeproc)
    registry.csv         Human-readable tracking sheet
    raw_crossref/<doi>.json   Raw Crossref API response (audit trail)
    raw_pubmed/<pmid>.xml     Raw PubMed efetch response (audit trail)
    raw_openalex/<doi>.json   Raw OpenAlex API response (audit trail)
"""

import sys
import json
import csv
import re
import os
import time
import requests
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Optional, List, Dict

# ── Configuration ─────────────────────────────────────────────────────────────
MAILTO = "phhung.y21@gmail.com"  # Crossref / OpenAlex polite pool — required
BASE_DIR = Path(os.environ.get("CITATION_DIR", Path(__file__).parent))
LIBRARY_FILE = BASE_DIR / "library.csl.json"
REGISTRY_FILE = BASE_DIR / "registry.csv"
RAW_DIR = BASE_DIR / "raw_crossref"
RAW_PUBMED_DIR = BASE_DIR / "raw_pubmed"
RAW_OPENALEX_DIR = BASE_DIR / "raw_openalex"
REGISTRY_FIELDS = [
    "citekey", "doi", "pmid", "authors", "year", "journal", "title",
    "has_abstract", "abstract_source", "openalex_id", "added",
]

STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "and", "for", "to", "with",
    "by", "at", "as", "is", "are", "was", "were", "its", "their",
    "after", "before", "during", "from", "into", "through", "using",
    "between", "among", "versus", "vs", "or", "not", "no", "de",
}

# ── DOI utilities ─────────────────────────────────────────────────────────────
def normalize_doi(raw: str) -> str:
    doi = raw.strip()
    doi = re.sub(r"^https?://doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.strip()

def safe_filename(doi: str) -> str:
    return re.sub(r"[^\w.-]", "_", doi)

# ── Citekey generation ────────────────────────────────────────────────────────
def ascii_clean(text: str) -> str:
    """Best-effort ASCII conversion."""
    result = []
    for ch in text:
        if ord(ch) < 128:
            result.append(ch)
        # Drop non-ASCII characters — handles accented letters imperfectly but safely
    return "".join(result)

def make_citekey(family: str, year: str, title: str) -> str:
    """Deterministic citekey: authorYearTitleWords (camelCase, no stops)."""
    author = re.sub(r"[^a-z]", "", ascii_clean(family).lower())
    words = title.split()
    meaningful = []
    for w in words:
        clean = re.sub(r"[^a-z]", "", ascii_clean(w).lower())
        if clean and clean not in STOPWORDS and len(clean) > 2:
            meaningful.append(clean)
    title_part = "".join(w.capitalize() for w in meaningful[:3])
    return f"{author}{year}{title_part}"

# ── Crossref API ──────────────────────────────────────────────────────────────
def fetch_crossref(doi: str) -> dict:
    url = f"https://api.crossref.org/works/{doi}"
    headers = {"User-Agent": f"citation-pipeline/1.0 (mailto:{MAILTO})"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["message"]

def crossref_year(msg: dict) -> Optional[int]:
    for field in ("published-print", "published-online", "issued"):
        parts = msg.get(field, {}).get("date-parts", [])
        if parts and parts[0]:
            return parts[0][0]
    return None

def clean_crossref_abstract(raw: Optional[str]) -> str:
    """Crossref abstracts (when present) come as JATS-tagged XML fragments."""
    if not raw:
        return ""
    text = re.sub(r"<jats:title>.*?</jats:title>", "", raw, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ── PubMed PMID + full record ─────────────────────────────────────────────────
def fetch_pmid(doi: str) -> Optional[str]:
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {"db": "pubmed", "term": f"{doi}[DOI]", "retmode": "json", "retmax": "1"}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        return ids[0] if ids else None
    except Exception:
        return None

def parse_pubmed_xml(xml_text: str) -> Optional[dict]:
    """Extract title/abstract/journal/year/authors from a PubMed efetch XML record."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    article = root.find(".//PubmedArticle")
    if article is None:
        return None

    title_el = article.find(".//ArticleTitle")
    title = "".join(title_el.itertext()).strip() if title_el is not None else ""

    abstract_parts = []
    for ab in article.findall(".//Abstract/AbstractText"):
        label = ab.get("Label")
        text = "".join(ab.itertext()).strip()
        if not text:
            continue
        abstract_parts.append(f"{label}: {text}" if label else text)
    abstract = " ".join(abstract_parts).strip()

    journal_el = article.find(".//Journal/Title")
    journal = journal_el.text.strip() if journal_el is not None and journal_el.text else ""

    year = None
    year_el = article.find(".//JournalIssue/PubDate/Year")
    if year_el is not None and year_el.text and year_el.text.isdigit():
        year = int(year_el.text)
    else:
        medline_date = article.find(".//JournalIssue/PubDate/MedlineDate")
        if medline_date is not None and medline_date.text:
            m = re.match(r"(\d{4})", medline_date.text)
            if m:
                year = int(m.group(1))

    authors = []
    for a in article.findall(".//AuthorList/Author"):
        family = a.findtext("LastName", "") or ""
        given = a.findtext("ForeName", "") or a.findtext("Initials", "") or ""
        if family:
            authors.append({"family": family, "given": given})

    return {
        "title": title,
        "abstract": abstract,
        "container-title": journal,
        "year": year,
        "author": authors,
    }

def fetch_pubmed_record(pmid: str) -> Optional[dict]:
    """Fetch + cache the full PubMed record (title/abstract/journal/year/authors)."""
    RAW_PUBMED_DIR.mkdir(exist_ok=True)
    cache_path = RAW_PUBMED_DIR / f"{pmid}.xml"
    if cache_path.exists():
        xml_text = cache_path.read_text(encoding="utf-8")
    else:
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        params = {"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "xml"}
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            xml_text = r.text
        except Exception:
            return None
        cache_path.write_text(xml_text, encoding="utf-8")
        time.sleep(0.4)  # polite delay — 3 req/sec without an API key
    return parse_pubmed_xml(xml_text)

# ── OpenAlex ───────────────────────────────────────────────────────────────────
def reconstruct_abstract(inverted_index: Optional[dict]) -> str:
    """OpenAlex stores abstracts as {word: [positions]}; rebuild plain text."""
    if not inverted_index:
        return ""
    positions: Dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))

def parse_openalex(data: dict) -> dict:
    title = data.get("title") or data.get("display_name") or ""
    abstract = reconstruct_abstract(data.get("abstract_inverted_index"))
    year = data.get("publication_year")

    source = ((data.get("primary_location") or {}).get("source")) or {}
    journal = source.get("display_name", "") or ""

    authors = []
    for a in data.get("authorships", []):
        name = (a.get("author") or {}).get("display_name", "")
        if not name:
            continue
        parts = name.rsplit(" ", 1)
        family, given = (parts[1], parts[0]) if len(parts) == 2 else (name, "")
        authors.append({"family": family, "given": given})

    return {
        "title": title,
        "abstract": abstract,
        "container-title": journal,
        "year": year,
        "author": authors,
        "openalex_id": data.get("id", ""),
    }

def fetch_openalex(doi: str) -> Optional[dict]:
    """Fetch + cache the OpenAlex work record for a DOI."""
    RAW_OPENALEX_DIR.mkdir(exist_ok=True)
    cache_path = RAW_OPENALEX_DIR / f"{safe_filename(doi)}.json"
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        url = f"https://api.openalex.org/works/https://doi.org/{doi}"
        try:
            r = requests.get(url, params={"mailto": MAILTO}, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return None
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        time.sleep(0.2)  # polite delay
    return parse_openalex(data)

# ── Standardize + backfill across sources ───────────────────────────────────────
# Some journals (Circulation/AHA titles especially) index only a graphical
# abstract, leaving the text abstract field as a short placeholder like
# "[Figure: see text]." across every metadata source (Crossref, PubMed,
# OpenAlex all had the same placeholder for one reference in the JAMA
# Network Open n=100 calibration run). Treated as truthy by `if text:`, this
# would silently feed the LLM check a non-answer instead of failing closed
# as no_abstract_found — worse than missing, since it looks like content.
_PLACEHOLDER_ABSTRACT_RE = re.compile(r"^\s*\[[^\]]*\]\.?\s*$")


def _is_placeholder_abstract(text: str) -> bool:
    return bool(_PLACEHOLDER_ABSTRACT_RE.match(text)) or len(text.strip()) < 20


def merge_metadata(crossref_msg: dict, pubmed: Optional[dict], openalex: Optional[dict]) -> dict:
    """Combine Crossref/PubMed/OpenAlex into one deduplicated record.

    Priority order (first non-empty value wins — sources are never blended
    within a single field):
      - title, authors, journal, year: Crossref first (most reliable
        structured bibliographic data), backfilled by PubMed, then OpenAlex.
      - abstract: PubMed first (cleanest, often structured Background/
        Methods/Results/Conclusions), backfilled by Crossref's abstract
        field (inconsistent coverage), then OpenAlex's reconstructed
        abstract (last resort — lossy, word order from inverted index only).
    """
    cr_title = (crossref_msg.get("title") or [""])[0]
    cr_journal = (crossref_msg.get("container-title") or [""])[0]
    cr_year = crossref_year(crossref_msg)
    cr_authors = [
        {k: v for k, v in {"family": a.get("family"), "given": a.get("given")}.items() if v}
        for a in crossref_msg.get("author", [])
    ]
    cr_abstract = clean_crossref_abstract(crossref_msg.get("abstract"))

    pm = pubmed or {}
    oa = openalex or {}

    title = cr_title or pm.get("title") or oa.get("title") or ""
    journal = cr_journal or pm.get("container-title") or oa.get("container-title") or ""
    year = cr_year or pm.get("year") or oa.get("year")
    authors = cr_authors or pm.get("author") or oa.get("author") or []

    abstract, abstract_source = "", ""
    for label, text in (("pubmed", pm.get("abstract")), ("crossref", cr_abstract), ("openalex", oa.get("abstract"))):
        if text and not _is_placeholder_abstract(text):
            abstract, abstract_source = text, label
            break

    return {
        "title": title,
        "container-title": journal,
        "year": year,
        "author": authors,
        "abstract": abstract,
        "abstract_source": abstract_source,
        "openalex_id": oa.get("openalex_id", ""),
    }

def build_csl_record(crossref_msg: dict, merged: dict, citekey: str, doi: str, pmid: Optional[str]) -> dict:
    """Assemble the final CSL JSON record. Volume/issue/page stay Crossref-only
    — PubMed and OpenAlex rarely report them cleanly enough to trust."""
    year = merged.get("year")

    record: Dict = {
        "id": citekey,
        "type": "article-journal" if crossref_msg.get("type") == "journal-article" else crossref_msg.get("type", "article-journal"),
        "title": merged.get("title", ""),
        "container-title": merged.get("container-title", ""),
        "DOI": doi,
        "volume": crossref_msg.get("volume", ""),
        "issue": crossref_msg.get("issue", ""),
        "page": crossref_msg.get("page", ""),
        "issued": {"date-parts": [[year]] if year else [[]]},
        "author": merged.get("author", []),
        "abstract": merged.get("abstract", ""),
    }
    if pmid:
        record["PMID"] = pmid
    if merged.get("openalex_id"):
        record["OPENALEX-ID"] = merged["openalex_id"]

    # Drop empty strings and empty lists
    return {k: v for k, v in record.items() if v not in ("", [], None)}

# ── Library I/O ───────────────────────────────────────────────────────────────
def load_library() -> List[dict]:
    if not LIBRARY_FILE.exists():
        return []
    with open(LIBRARY_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_library(records: List[dict]) -> None:
    with open(LIBRARY_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

def load_registry() -> List[dict]:
    if not REGISTRY_FILE.exists():
        return []
    with open(REGISTRY_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def append_registry(row: dict) -> None:
    write_header = not REGISTRY_FILE.exists() or REGISTRY_FILE.stat().st_size == 0

    if not write_header:
        # Migrate existing rows if the header has grown new columns since
        # they were written, so the CSV never ends up with a header/data
        # column mismatch.
        with open(REGISTRY_FILE, encoding="utf-8") as f:
            current_header = next(csv.reader(f), [])
        if current_header != REGISTRY_FIELDS:
            existing_rows = load_registry()
            with open(REGISTRY_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS, extrasaction="ignore")
                writer.writeheader()
                for r in existing_rows:
                    writer.writerow(r)

    with open(REGISTRY_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    doi = normalize_doi(sys.argv[1])
    print(f"DOI: {doi}")

    # Duplicate check
    registry = load_registry()
    if any(r["doi"].lower() == doi.lower() for r in registry):
        match = next(r for r in registry if r["doi"].lower() == doi.lower())
        print(f"Already in library as @{match['citekey']} — skipping.")
        sys.exit(0)

    # Crossref
    print("Querying Crossref ...", end=" ", flush=True)
    try:
        msg = fetch_crossref(doi)
        print("OK")
    except requests.HTTPError as e:
        print(f"FAILED ({e})")
        sys.exit(1)

    # Save raw response
    RAW_DIR.mkdir(exist_ok=True)
    raw_path = RAW_DIR / f"{safe_filename(doi)}.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(msg, f, indent=2, ensure_ascii=False)

    # Extract fields for citekey
    first_author = (msg.get("author") or [{}])[0].get("family", "unknown")
    title = (msg.get("title") or ["untitled"])[0]
    year = crossref_year(msg)
    year_str = str(year) if year else "xxxx"

    citekey = make_citekey(first_author, year_str, title)

    # Ensure citekey uniqueness
    library = load_library()
    existing_keys = {r["id"] for r in library}
    if citekey in existing_keys:
        suffix = "b"
        while f"{citekey}{suffix}" in existing_keys:
            suffix = chr(ord(suffix) + 1)
        citekey = f"{citekey}{suffix}"

    # PubMed PMID + full record (title/abstract/journal/year/authors)
    time.sleep(0.5)  # polite delay
    print("Querying PubMed  ...", end=" ", flush=True)
    pmid = fetch_pmid(doi)
    pubmed_record = None
    if pmid:
        pubmed_record = fetch_pubmed_record(pmid)
        print(f"{pmid}" + (" (abstract found)" if pubmed_record and pubmed_record.get("abstract") else ""))
    else:
        print("not found")

    # OpenAlex (fallback source for whatever Crossref/PubMed are missing)
    print("Querying OpenAlex...", end=" ", flush=True)
    openalex_record = fetch_openalex(doi)
    print("OK" if openalex_record else "not found")

    # Standardize + backfill across all three sources
    merged = merge_metadata(msg, pubmed_record, openalex_record)

    # Build CSL JSON record
    record = build_csl_record(msg, merged, citekey, doi, pmid)

    # Save
    library.append(record)
    save_library(library)

    authors_str = "; ".join(
        f"{a.get('family', '')} {a.get('given', '')[:1]}".strip()
        for a in record.get("author", [])[:3]
    )
    if len(record.get("author", [])) > 3:
        authors_str += " et al."

    append_registry({
        "citekey": citekey,
        "doi": doi,
        "pmid": pmid or "",
        "authors": authors_str,
        "year": year_str,
        "journal": record.get("container-title", ""),
        "title": title[:120],
        "has_abstract": "yes" if merged.get("abstract") else "no",
        "abstract_source": merged.get("abstract_source", ""),
        "openalex_id": merged.get("openalex_id", ""),
        "added": str(date.today()),
    })

    print(f"\n  @{citekey}")
    print(f"  {title[:80]}")
    print(f"  {record.get('container-title', '')} {year_str}")
    if pmid:
        print(f"  PMID {pmid}")
    if merged.get("openalex_id"):
        print(f"  OpenAlex {merged['openalex_id']}")
    if merged.get("abstract"):
        print(f"  Abstract: {len(merged['abstract'])} chars (source: {merged['abstract_source']})")
    else:
        print("  Abstract: not found in any source")

if __name__ == "__main__":
    main()
