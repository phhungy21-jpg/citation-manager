#!/usr/bin/env python3
"""
sample_jama_network_open.py — Pull and freeze a sample of JAMA Network Open
"Original Investigation" articles with PMC full text, for the Phase 3 audit.

Per docs/adjudication-criteria.md's sample-frame decision (2026-07-01): JAMA
Network Open, original research articles only (excludes Research Letters,
Corrections, Editorials, Comments, Viewpoints), n=100, drawn from a fixed
publication-date window (default: calendar year 2025) rather than "most
recent," because very recent articles lag behind PMC deposit — a live test
found only ~27% of the most-recently-published articles had PMC full text
linked yet, vs. consistent availability for a year-old window.

Inclusion is filtered on the JATS <subj-group subj-group-type="heading">
<subject> text, NOT on the article-type attribute — "research-article" is
shared by Original Investigations AND Research Letters in this journal's
JATS output, so article-type alone can't distinguish them.

Usage:
    python sample_jama_network_open.py --n 100 --year 2025
    python sample_jama_network_open.py --n 100 --year 2025 --seed 42

Output:
    audit/data/preregistration/jama_network_open_sample_<year>_<n>.json
    One row per included article: pmcid, pmid, doi, title, heading,
    n_references, body_chars. This file is the frozen sample — write it
    once, do not regenerate it after citation-checking begins (that would
    let the sample silently drift based on what's convenient to check).
"""

import argparse
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import xml.etree.ElementTree as ET

import requests

MAILTO = "phhung.y21@gmail.com"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
BATCH_SIZE = 40

INCLUDE_HEADING = "Original Investigation"
MIN_BODY_CHARS = 3000
MIN_REFS = 10

OUT_DIR = Path(__file__).parent / "data" / "preregistration"


def search_pmcids(year: int, retmax: int = 3000) -> List[str]:
    term = f'"JAMA Netw Open"[Journal] AND ("{year}/01/01"[Publication Date] : "{year}/12/31"[Publication Date])'
    params = {"db": "pmc", "term": term, "retmode": "json", "retmax": retmax, "email": MAILTO}
    r = requests.get(ESEARCH_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()["esearchresult"]["idlist"]


def fetch_batch_xml(pmcids: List[str], retries: int = 3) -> Optional[str]:
    params = {"db": "pmc", "id": ",".join(pmcids), "rettype": "xml", "retmode": "xml", "email": MAILTO}
    for attempt in range(retries):
        try:
            r = requests.get(EFETCH_URL, params=params, timeout=60)
            r.raise_for_status()
            return r.text
        except requests.HTTPError as e:
            if attempt == retries - 1:
                print(f"FAILED after {retries} attempts ({e}) — skipping this batch")
                return None
            time.sleep(2 * (attempt + 1))  # backoff: 2s, 4s
    return None


def extract_candidate(article: ET.Element) -> Optional[dict]:
    heading_el = article.find(".//subj-group[@subj-group-type='heading']/subject")
    heading = heading_el.text if heading_el is not None else None
    if heading != INCLUDE_HEADING:
        return None

    body = article.find(".//body")
    body_chars = len("".join(body.itertext())) if body is not None else 0
    refs = article.findall(".//back//ref-list/ref")
    if body_chars < MIN_BODY_CHARS or len(refs) < MIN_REFS:
        return None

    pmcid_el = article.find(".//article-id[@pub-id-type='pmcid']")
    pmid_el = article.find(".//article-id[@pub-id-type='pmid']")
    doi_el = article.find(".//article-id[@pub-id-type='doi']")
    title_el = article.find(".//article-title")

    return {
        "pmcid": pmcid_el.text if pmcid_el is not None else None,
        "pmid": pmid_el.text if pmid_el is not None else None,
        "doi": doi_el.text if doi_el is not None else None,
        "title": "".join(title_el.itertext()).strip() if title_el is not None else "",
        "heading": heading,
        "n_references": len(refs),
        "body_chars": body_chars,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=100, help="Sample size (default 100)")
    parser.add_argument("--year", type=int, default=2025, help="Publication-date window, calendar year (default 2025)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling from the qualifying pool (default 42)")
    args = parser.parse_args()

    print(f"Searching PMC: JAMA Network Open, {args.year} ...")
    pmcids = search_pmcids(args.year)
    print(f"  {len(pmcids)} candidate PMC records found")

    # Shuffle BEFORE fetching/filtering, using the same seed as the final
    # sample draw. This makes the early-stop-once-we-have-a-margin logic
    # below statistically sound: since esearch's return order is not random
    # (relevance/uid, not random), fetching batches in that order and then
    # stopping early would give every not-yet-fetched record zero chance of
    # selection -- not a valid random sample of the population. Shuffling
    # first means any prefix of the list is itself a uniform random sample.
    random.seed(args.seed)
    random.shuffle(pmcids)

    candidates = []
    failed_batches = []
    n_batches = -(-len(pmcids) // BATCH_SIZE)
    for i in range(0, len(pmcids), BATCH_SIZE):
        batch = pmcids[i:i + BATCH_SIZE]
        print(f"  fetching batch {i // BATCH_SIZE + 1}/{n_batches} ({len(batch)} records) ...", end=" ", flush=True)
        xml_text = fetch_batch_xml(batch)
        if xml_text is None:
            failed_batches.append(batch)
            continue
        root = ET.fromstring(xml_text)
        n_kept = 0
        for article in root.findall(".//article"):
            candidate = extract_candidate(article)
            if candidate and candidate["pmcid"] and candidate["doi"]:
                candidates.append(candidate)
                n_kept += 1
        print(f"{n_kept} qualifying")
        time.sleep(0.4)

        # Stop early once we have a comfortable margin over the target —
        # no need to fetch all ~2000 records if the first third already
        # cleared several times the requested sample size.
        if len(candidates) >= args.n * 4:
            print(f"  (stopping early: {len(candidates)} qualifying candidates already found, "
                  f">= 4x the requested n={args.n})")
            break

    if failed_batches:
        print(f"\n{len(failed_batches)} batch(es) failed after retries and were skipped "
              f"({sum(len(b) for b in failed_batches)} records not checked).")

    print(f"\nTotal qualifying 'Original Investigation' articles: {len(candidates)}")
    if len(candidates) < args.n:
        print(f"WARNING: only {len(candidates)} qualify, fewer than requested n={args.n}. "
              f"Widen the --year window or lower thresholds.")

    random.seed(args.seed)
    sample = random.sample(candidates, min(args.n, len(candidates)))
    sample.sort(key=lambda c: c["pmcid"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"jama_network_open_sample_{args.year}_{args.n}.json"
    output = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "sample_frame": {
            "journal": "JAMA Network Open",
            "publication_date_window": f"{args.year}-01-01 to {args.year}-12-31",
            "inclusion_heading": INCLUDE_HEADING,
            "min_body_chars": MIN_BODY_CHARS,
            "min_references": MIN_REFS,
            "random_seed": args.seed,
        },
        "n_candidates_pool": len(candidates),
        "n_failed_batches": len(failed_batches),
        "n_records_skipped_due_to_failed_batches": sum(len(b) for b in failed_batches),
        "n_sampled": len(sample),
        "articles": sample,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nFrozen sample written: {out_path}")
    print("Do not regenerate this file after citation-checking begins.")


if __name__ == "__main__":
    main()
