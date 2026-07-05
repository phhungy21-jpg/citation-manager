#!/usr/bin/env python3
"""
citation_registry.py — Persistent, append-only ledger of every reference-
resolution attempt made by ref_resolver.py, across all runs and all papers.

This is deliberately separate from library.csl.json (the manuscript
bibliography, only ever touched by add_reference.py per CLAUDE.md). The
registry exists so that:
  1. A reference already resolved (or already confirmed unresolvable) in a
     prior run is never re-fetched — dedup happens before any external API
     call, keyed by DOI when known, else by normalized title+year.
  2. Every resolution outcome (resolved / unresolved / doi_invalid) carries a
     resolution_method so downstream consumers (check_claims.py, manual
     adjudicators) can weight trust accordingly — a fuzzy title match should
     never be treated with the same confidence as a direct DOI hit.
  3. Unresolved references are registered as stubs with the raw reference
     string preserved verbatim, so they surface in review rather than
     silently vanishing — never fabricate a citekey or field for them.

Storage: audit/data/citation_registry.json, a flat list of records:
    {
        "key": str,                 # lowercased DOI, or "title|year" fallback key
        "doi": str | None,
        "status": "resolved" | "unresolved" | "doi_invalid",
        "resolution_method": "doi_direct" | "title_exact" | "title_fuzzy" |
                              "fallback_semantic_scholar" | "fallback_datacite" |
                              "fallback_preprint" | "fallback_core" |
                              "jats_xml_direct" | "unresolved",
        "raw_ref_text": str,
        "source": str,              # which API/module produced this record
        "checked_at": str,          # UTC ISO timestamp of last check
    }

Not thread-safe / not safe for concurrent writers — this project runs one
script at a time.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

AUDIT_DIR = Path(__file__).parent
DATA_DIR = AUDIT_DIR / "data"
REGISTRY_FILE = DATA_DIR / "citation_registry.json"


def _normalize_title(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return " ".join(words)


def make_title_year_key(title: str, year: Optional[int]) -> str:
    return f"{_normalize_title(title)}|{year or ''}"


def _load() -> List[Dict]:
    if not REGISTRY_FILE.exists():
        return []
    with open(REGISTRY_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(records: List[Dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def lookup(doi: Optional[str] = None, title: Optional[str] = None, year: Optional[int] = None) -> Optional[Dict]:
    """Dedup check — called before any external API request. Matches by DOI
    first (exact, case-insensitive), else by normalized title+year."""
    records = _load()
    if doi:
        doi_l = doi.lower()
        for rec in records:
            if rec.get("doi") and rec["doi"].lower() == doi_l:
                return rec
    if title:
        key = make_title_year_key(title, year)
        for rec in records:
            if rec.get("key") == key:
                return rec
    return None


def register(
    *,
    doi: Optional[str],
    status: str,
    resolution_method: str,
    raw_ref_text: str,
    source: str,
    title: Optional[str] = None,
    year: Optional[int] = None,
) -> Dict:
    """Append-or-update a resolution outcome, keyed by DOI if present, else
    by normalized title+year. Always called, regardless of outcome — the
    registry is a complete audit trail of every attempt, not just successes."""
    key = doi.lower() if doi else make_title_year_key(title or raw_ref_text, year)
    record = {
        "key": key,
        "doi": doi,
        "status": status,
        "resolution_method": resolution_method,
        "raw_ref_text": raw_ref_text,
        "source": source,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    records = _load()
    for i, rec in enumerate(records):
        if rec.get("key") == key:
            records[i] = record
            break
    else:
        records.append(record)
    _save(records)
    return record
