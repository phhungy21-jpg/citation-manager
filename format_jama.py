#!/usr/bin/env python3
"""
format_jama.py — Format a numbered reference list in JAMA style from a refs JSON file.

Each entry in the refs file must have an "n" (number) and either a "doi" for
automatic CrossRef lookup or a "manual" field with a pre-formatted citation.

Usage:
    python format_jama.py                              # reads refs_master.json next to script
    python format_jama.py --refs path/to/refs.json    # explicit refs file
    python format_jama.py --output refs_jama.txt      # also save to file
    python format_jama.py --no-fetch                  # use cached CrossRef only, no network

CrossRef responses are cached in raw_crossref/ (same dir as script) to avoid
redundant network calls across projects.
"""

import sys
import io
import json
import time
import argparse
import requests
import re
import unicodedata
from pathlib import Path

# Force UTF-8 on Windows console
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

MAILTO = "phhung.y21@gmail.com"
HEADERS = {"User-Agent": f"citation-pipeline/1.0 (mailto:{MAILTO})"}
CACHE_DIR = Path(__file__).parent / "raw_crossref"


# ── CrossRef fetch (cache-first) ──────────────────────────────────────────────
def safe_filename(doi: str) -> str:
    return re.sub(r"[^\w.-]", "_", doi)


def fetch_crossref(doi: str, no_fetch: bool = False) -> dict:
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / f"{safe_filename(doi)}.json"
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    if no_fetch:
        raise FileNotFoundError(f"Cache miss and --no-fetch active: {doi}")
    url = f"https://api.crossref.org/works/{doi}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    msg = r.json()["message"]
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(msg, f, indent=2, ensure_ascii=False)
    time.sleep(0.4)
    return msg


# ── Author formatting ─────────────────────────────────────────────────────────
def ascii_approx(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def initials(given: str) -> str:
    parts = re.split(r"[\s\-]+", given.strip())
    return "".join(p[0].upper() for p in parts if p)


def format_authors(authors: list) -> str:
    """JAMA: Last AB, Last CD, ... (up to 6, then et al)"""
    parts = []
    for a in authors[:6]:
        family = ascii_approx(a.get("family", "")).strip()
        given = ascii_approx(a.get("given", "")).strip()
        ini = initials(given) if given else ""
        parts.append(f"{family} {ini}".strip() if ini else family)
    result = ", ".join(parts)
    if len(authors) > 6:
        result += ", et al"
    return result


# ── Field extraction ──────────────────────────────────────────────────────────
def get_year(msg: dict) -> str:
    for field in ("published-print", "published-online", "issued"):
        parts = msg.get(field, {}).get("date-parts", [])
        if parts and parts[0]:
            return str(parts[0][0])
    return "n.d."


def get_journal(msg: dict) -> str:
    short = msg.get("short-container-title") or []
    if short and short[0].strip():
        return short[0].strip()
    full = msg.get("container-title") or []
    return full[0].strip() if full else ""


def get_title(msg: dict) -> str:
    titles = msg.get("title") or []
    return titles[0].rstrip(".") if titles else ""


# ── JAMA formatter ────────────────────────────────────────────────────────────
def format_jama(msg: dict, doi: str) -> str:
    authors = format_authors(msg.get("author", []))
    title   = get_title(msg)
    journal = get_journal(msg)
    year    = get_year(msg)
    volume  = msg.get("volume", "")
    issue   = msg.get("issue", "")
    page    = msg.get("page", "")

    issue_str = f"({issue})" if issue else ""
    vol_str   = f"{volume}{issue_str}" if volume else ""
    page_str  = f":{page}" if page else ""
    loc       = f"{year};{vol_str}{page_str}".rstrip(";") if vol_str or page_str else year

    doi_str = f" doi:{doi}" if doi else ""
    return f"{authors}. {title}. *{journal}.* {loc}.{doi_str}"


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--refs", default=None,
        help="Path to refs JSON file (default: refs_master.json next to script)",
    )
    parser.add_argument("--output", default=None, help="Save formatted list to this file")
    parser.add_argument(
        "--no-fetch", action="store_true",
        help="Use CrossRef cache only; no network calls",
    )
    args = parser.parse_args()

    refs_path = Path(args.refs) if args.refs else Path(__file__).parent / "refs_master.json"
    if not refs_path.exists():
        print(f"ERROR: refs file not found: {refs_path}", file=sys.stderr)
        print("       Pass --refs path/to/refs.json or place refs_master.json next to this script.")
        sys.exit(1)

    with open(refs_path, encoding="utf-8") as f:
        refs = json.load(f)

    lines = []
    errors = []

    for ref in sorted(refs, key=lambda r: r["n"]):
        n      = ref["n"]
        doi    = ref.get("doi")
        manual = ref.get("manual")
        note   = ref.get("_note", "")

        if manual:
            line = f"{n}. {manual}"
        elif doi:
            try:
                print(f"  [{n:2d}] {doi[:55]:<55} ", end="", flush=True)
                msg = fetch_crossref(doi, no_fetch=args.no_fetch)
                citation = format_jama(msg, doi)
                line = f"{n}. {citation}"
                print("OK")
            except requests.HTTPError as e:
                line = f"{n}. [HTTP ERROR {e.response.status_code} for doi:{doi}]"
                errors.append((n, doi, str(e)))
                print(f"HTTP {e.response.status_code}")
            except Exception as e:
                line = f"{n}. [ERROR for doi:{doi} — {e}]"
                errors.append((n, doi, str(e)))
                print(f"FAILED: {e}")
        else:
            line = f"{n}. [MISSING: no DOI, no manual entry — {note}]"

        lines.append(line)

    output = "\n\n".join(lines)

    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nSaved to: {out_path}")

    print("\n" + "=" * 70)
    print(output)
    print("=" * 70)
    print(f"\n{len(refs)} references processed.")
    if errors:
        print(f"{len(errors)} error(s):")
        for n, doi, msg in errors:
            print(f"  [{n}] {doi}: {msg}")


if __name__ == "__main__":
    main()
