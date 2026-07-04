#!/usr/bin/env python3
"""
fulltext_fetch.py — Gate 2 of the claim-support check: when an abstract-only
verdict is anything but SUPPORTED, check whether the cited paper is open
access and, if so, fetch + convert the full text so it can be re-checked
against the actual claim instead of just the abstract.

This exists because "not supported by the abstract" is not the same as
"not supported by the paper" (see docs/adjudication-criteria.md). A real
reviewer, given an unclear or seemingly-unsupported citation, reads the full
paper before concluding it's a miscitation. This module is that step,
automated where the paper is legally accessible.

OA status via Unpaywall (https://unpaywall.org) — free, no API key, just a
polite-pool email param. Never scrapes or bypasses a paywall; if Unpaywall
reports no legal OA copy, this reports unavailable and gate 2 is skipped.
"""

import json
import time
from pathlib import Path
from typing import Optional

import requests

MAILTO = "phhung.y21@gmail.com"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"

AUDIT_DIR = Path(__file__).parent
UNPAYWALL_CACHE = AUDIT_DIR / "cache" / "unpaywall"
FULLTEXT_CACHE = AUDIT_DIR / "cache" / "fulltext"


def safe_filename(doi: str) -> str:
    import re
    return re.sub(r"[^\w.-]", "_", doi)


def check_oa_status(doi: str) -> Optional[dict]:
    """Query Unpaywall for OA status, cached by DOI. Returns the raw
    Unpaywall record, or None if the DOI isn't found / lookup fails."""
    UNPAYWALL_CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = UNPAYWALL_CACHE / f"{safe_filename(doi)}.json"
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)

    try:
        r = requests.get(UNPAYWALL_URL.format(doi=doi), params={"email": MAILTO}, timeout=20)
        if r.status_code == 404:
            data = None
        else:
            r.raise_for_status()
            data = r.json()
    except Exception:
        return None

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    time.sleep(0.2)
    return data


def best_oa_pdf_url(oa_record: Optional[dict]) -> Optional[str]:
    if not oa_record or not oa_record.get("is_oa"):
        return None
    best = oa_record.get("best_oa_location") or {}
    return best.get("url_for_pdf") or best.get("url")


def fetch_fulltext(doi: str) -> Optional[str]:
    """Returns full-text Markdown for a DOI if a legal OA copy exists and
    can be downloaded + converted, else None. Caches the converted Markdown
    by DOI so this is a one-time cost per paper."""
    FULLTEXT_CACHE.mkdir(parents=True, exist_ok=True)
    md_cache_path = FULLTEXT_CACHE / f"{safe_filename(doi)}.md"
    if md_cache_path.exists():
        return md_cache_path.read_text(encoding="utf-8")

    oa_record = check_oa_status(doi)
    pdf_url = best_oa_pdf_url(oa_record)
    if not pdf_url:
        return None

    try:
        r = requests.get(pdf_url, timeout=60, headers={"User-Agent": f"citation-pipeline-audit/1.0 (mailto:{MAILTO})"})
        r.raise_for_status()
        if "pdf" not in r.headers.get("Content-Type", "").lower() and not r.content[:4] == b"%PDF":
            return None  # landing page, not an actual PDF — don't guess
    except Exception:
        return None

    tmp_pdf = FULLTEXT_CACHE / f"{safe_filename(doi)}.pdf"
    tmp_pdf.write_bytes(r.content)

    try:
        import pdf_to_md
        text = pdf_to_md.pdf_to_markdown(tmp_pdf)
    except Exception:
        return None
    finally:
        tmp_pdf.unlink(missing_ok=True)  # don't keep raw PDFs around, just the converted text + OA metadata trail

    md_cache_path.write_text(text, encoding="utf-8")
    return text
