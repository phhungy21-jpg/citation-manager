#!/usr/bin/env python3
"""
check_claims.py — For a published paper, check whether each in-text citation's
cited abstract actually supports the claim made in the citing sentence.

This is a FLAG generator, not a verdict. Every non-SUPPORTED result (and every
reference that couldn't be resolved or abstracted) belongs in a manual review
queue — nothing here is auto-corrected or auto-removed.

Pipeline per (sentence, citation number):
    1. Parse "## References" section -> {n: raw reference text}    (ref_resolver)
    2. Parse body prose -> sentences with their [n] / [n,m] markers
    3. Resolve reference text -> DOI via Crossref search             (ref_resolver)
    4. Fetch abstract for that DOI — checks library.csl.json first (already-
       merged Crossref+PubMed+OpenAlex), else fetches+caches fresh via the
       same three-source merge used by add_reference.py. Never writes to
       library.csl.json — that file is only ever touched by add_reference.py.
    5. Gate 1 — LLM call scoped to the ABSTRACT: SUPPORTED / PARTIALLY_SUPPORTED
       / UNSUPPORTED, plus a FLAG_TYPE (TOPIC_MISMATCH / NUMBER_CONTRADICTION /
       NOT_MENTIONED) for anything not SUPPORTED.                    (llm_client)
    6. Gate 2 — only runs when gate 1 is non-SUPPORTED: checks Unpaywall for a
       legal open-access copy of the cited paper, and if found, re-runs the
       check against the FULL TEXT instead of just the abstract. Mirrors what
       a human reviewer does with an unclear citation — read the paper before
       calling it a miscitation.                              (fulltext_fetch)
       Every LLM call (either gate) is cached by a hash of (model, system,
       user) so reruns are free and the audit trail is reproducible without
       re-hitting the API.

Usage:
    python check_claims.py "../TEMP/Jia 2023.md"
    python check_claims.py paper.pdf                  # auto-converts via pdf_to_md
    python check_claims.py paper.md --limit 5          # only check first 5 claims (testing)
    python check_claims.py paper.md --dry-run          # parse + resolve + fetch abstracts,
                                                        # skip LLM calls entirely (no API key needed)

Output:
    audit/results/flags/<paper_stem>.json   full record: counts, flagged items,
                                             and every check (see docstring below)
    audit/logs/sessions/<timestamp>_<paper_stem>.json   run summary
    audit/logs/llm_calls/<hash>.json         one file per unique LLM call
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

AUDIT_DIR = Path(__file__).parent
PIPELINE_DIR = AUDIT_DIR.parent
sys.path.insert(0, str(PIPELINE_DIR))
sys.path.insert(0, str(AUDIT_DIR))

import add_reference as ar  # noqa: E402 — Crossref/PubMed/OpenAlex fetch + merge
import ref_resolver as rr   # noqa: E402
import llm_client           # noqa: E402
import pdf_to_md            # noqa: E402
import fulltext_fetch       # noqa: E402 — gate 2: OA full-text re-check
import jats_parser          # noqa: E402 — alternate input path: PMC structured XML

LOGS_DIR = AUDIT_DIR / "logs"
LLM_CALL_DIR = LOGS_DIR / "llm_calls"
SESSION_DIR = LOGS_DIR / "sessions"
FLAGS_DIR = AUDIT_DIR / "results" / "flags"

# Rejects statistical degrees-of-freedom notation like "F[4,163] = 9.93" or
# "F[4,163]=9.93", which is otherwise indistinguishable from a multi-citation
# marker "[4,163]" — both are a bracketed comma-separated number list. Found
# via a real bug: this exact pattern in a JAMA Network Open paper caused a
# reported F-statistic to be checked as if citing references 4 and 163
# (ref 163 doesn't exist and correctly fell through, but ref 4 was a real,
# unrelated citation that got silently checked against the wrong sentence).
# The distinguishing signal is what follows the closing bracket: statistical
# notation is essentially always followed by "=" (with optional whitespace),
# which a real citation marker never is.
CITATION_RE = re.compile(r"\[(\d+(?:\s*[,\-–]\s*\d+)*)\](?!\s*=)")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")

# IMPORTANT scope note: this prompt asks the model to judge the ABSTRACT
# only, never the full paper. "UNSUPPORTED" therefore means "not supported
# by this abstract" — NOT "not supported by the paper." A structured
# abstract commonly omits secondary findings (e.g. QoL sub-analyses) that
# exist in the full text. Every verdict from this prompt is abstract-only;
# check_claims.py stamps "verdict_basis": "abstract_only" on every output
# entry so downstream consumers (adjudicators, the eventual paper) can never
# confuse "unsupported by abstract" with "unsupported by paper." See
# docs/adjudication-criteria.md for how this distinction is meant to be
# handled during manual review.
# FLAG_TYPE only applies when VERDICT is not SUPPORTED — it's a reviewer-
# style triage of *why* the claim failed, mirroring how a human reviewer
# reads a flagged citation: is the cited paper simply about something else
# (TOPIC_MISMATCH), does the source's data conflict with the claim's numbers
# (NUMBER_CONTRADICTION), or is it plausibly on-topic but the specific point
# just isn't in the abstract (NOT_MENTIONED — the case most likely to be
# resolved by reading the full text, see the gate-2 cascade below)?
SYSTEM_PROMPT = """You are checking whether a citation supports a claim made in a scientific manuscript. You will be given a CLAIM (a sentence from the manuscript) and an ABSTRACT (of the paper being cited for that claim). Determine whether the ABSTRACT supports the CLAIM.

Your judgment is scoped to the ABSTRACT text only — you are not being asked whether the full cited paper supports the claim, only whether this abstract does. A claim can be true and well-supported by a paper's full text while still being UNSUPPORTED by that paper's abstract, because abstracts often omit secondary findings. Judge only what is in front of you.

Respond in exactly this format, nothing else:
VERDICT: SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED
FLAG_TYPE: TOPIC_MISMATCH | NUMBER_CONTRADICTION | NOT_MENTIONED | NONE
QUOTE: <exact substring copied from the ABSTRACT that supports the claim, or "none" if UNSUPPORTED>
GAP: <if not SUPPORTED, one sentence on what is missing or overstated; otherwise "none">

Rules:
- QUOTE must be an exact substring of ABSTRACT — do not paraphrase or combine non-contiguous spans.
- SUPPORTED: the abstract directly and specifically supports the claim as stated. FLAG_TYPE is NONE.
- PARTIALLY_SUPPORTED: the abstract supports part of the claim, or supports a weaker/different version of it (e.g. different magnitude, different population, correlation vs causation, or the claim is more specific than the abstract can back up).
- UNSUPPORTED: the abstract does not address the claim, or the claim asserts something the abstract does not say. This does not imply the paper as a whole fails to support the claim — only that the abstract doesn't.
- For PARTIALLY_SUPPORTED or UNSUPPORTED, set FLAG_TYPE to whichever best describes the failure:
  - TOPIC_MISMATCH: the abstract is about a different outcome/subject than the claim entirely (e.g. claim is about continence recovery, abstract is about surgical margins).
  - NUMBER_CONTRADICTION: the abstract reports a specific number/range for the same outcome, and it conflicts with the number the claim states.
  - NOT_MENTIONED: the abstract is plausibly on-topic but simply doesn't contain the specific point the claim makes — full-text review might resolve this.
- Never mark SUPPORTED or PARTIALLY_SUPPORTED without a QUOTE."""

USER_TEMPLATE = 'CLAIM: "{claim}"\n\nABSTRACT:\n{abstract}'

# Gate 2: same task, but scoped to the full paper text instead of just the
# abstract, used only when gate 1 (abstract) comes back non-SUPPORTED and an
# open-access full text is available. This is what a human reviewer does
# when a citation "looks unsupported" from the abstract alone — read the
# paper before concluding it's a real miscitation.
SYSTEM_PROMPT_FULLTEXT = """You are checking whether a citation supports a claim made in a scientific manuscript. An earlier abstract-only check found this claim NOT clearly supported by the cited paper's abstract. You will now be given the FULL TEXT of that cited paper. Determine whether the FULL TEXT supports the CLAIM — abstracts often omit secondary findings that the full text contains.

Respond in exactly this format, nothing else:
VERDICT: SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED
FLAG_TYPE: TOPIC_MISMATCH | NUMBER_CONTRADICTION | NOT_MENTIONED | NONE
QUOTE: <exact substring copied from the FULL TEXT that supports the claim, or "none" if UNSUPPORTED>
GAP: <if not SUPPORTED, one sentence on what is missing or overstated; otherwise "none">

Rules are identical to the abstract-only check: QUOTE must be an exact substring, FLAG_TYPE is NONE only when SUPPORTED, never mark SUPPORTED/PARTIALLY_SUPPORTED without a QUOTE."""

USER_TEMPLATE_FULLTEXT = 'CLAIM: "{claim}"\n\nFULL TEXT:\n{fulltext}'
FULLTEXT_CHAR_LIMIT = 40000  # keep within a reasonable context budget


# ── Manuscript loading ────────────────────────────────────────────────────────
def load_manuscript(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        md_path = path.with_suffix(".md")
        if not md_path.exists():
            print(f"Converting {path.name} to Markdown ...")
            pdf_to_md.convert(path, md_path)
        return md_path.read_text(encoding="utf-8")
    return path.read_text(encoding="utf-8")


def split_body_and_refs(md_text: str) -> tuple:
    # Headings are sometimes wrapped in markdown emphasis by PDF-to-MD
    # conversion (e.g. "## **REFERENCES**") — found via a real bug: Kang
    # 2022's heading didn't match the old pattern at all, so 0 references
    # were parsed and every citation in the paper fell through as
    # "reference_not_in_list". _HEADING_WRAP tolerates *_ /** on either side.
    m = re.search(r"(?im)^#+\s*[*_]*\s*references\s*[*_]*\s*$", md_text)
    body = md_text[:m.start()] if m else md_text
    refs = md_text[m.start():] if m else ""

    # Trim the title/author/affiliation block and structured-abstract summary
    # (Objective/Methods/Results/Conclusion/Keywords), which precede the real
    # prose and often contain author-list superscripts like "Jia[1], Chen[2]"
    # that look exactly like citation markers. Start from the first
    # Introduction/Background heading if one exists — near-universal in
    # clinical papers. Known limitation: journals without that heading (or
    # with a different name for it) fall back to the untrimmed body, which
    # will re-expose this false-positive source.
    intro_m = re.search(r"(?im)^#+\s*[*_]*\s*(introduction|background)\s*[*_]*\s*$", body)
    if intro_m:
        body = body[intro_m.end():]

    return body, refs


# ── Claim extraction ──────────────────────────────────────────────────────────
MAX_CITATION_RANGE_SPAN = 15  # a-b in "[a-b]" larger than this is not a citation range


def expand_marker(marker: str) -> List[int]:
    """Parse '3', '3,7', '3-7' style citation markers. Deliberately rejects
    wide numeric ranges — found via a real bug: "15 [13-41] vs. 85 [30.50-195]
    days" is an IQR (interquartile range) statistic, not a citation to
    references 13 through 41. Real citation ranges in clinical papers are
    essentially never more than ~15 references wide; IQR/range statistics
    reported in brackets routinely are. A range wider than the cap is
    silently dropped rather than misread as 19 fake citations."""
    nums = []
    for part in marker.split(","):
        part = part.strip()
        range_m = re.match(r"^(\d+)\s*[\-–]\s*(\d+)$", part)
        if range_m:
            a, b = int(range_m.group(1)), int(range_m.group(2))
            if 0 <= b - a <= MAX_CITATION_RANGE_SPAN:
                nums.extend(range(a, b + 1))
        elif part.isdigit():
            nums.append(int(part))
    return nums


# Running headers/footers and copyright/license boilerplate that PDF-to-
# Markdown conversion leaves embedded MID-PARAGRAPH at page breaks (not on
# their own line, so the line-level filter below can't catch them). Found
# via real bugs: sentences like "...affect the quality of life (QoL) of
# patients [2,3]. © 2022 The Authors. wileyonlinelibrary.com BJU
# International published... [4]." merged an unrelated boilerplate block
# into the middle of a real sentence, corrupting citation-to-sentence
# attribution. Also handles the inverse: a page break sometimes leaves only
# the tail of a sentence ("[21], our data showed..."), which this cannot
# fix — that case is a genuine information loss, not just noise, and stays
# a known limitation (see audit/NOTES.md).
_BOILERPLATE_RE = re.compile(
    r"(?i)[©�]\s*20\d{2}\s+the authors\.?"
    r"|wileyonlinelibrary\.com"
    r"|www\.\w+\.\w+"
    r"|published by (john wiley|elsevier|wolters|springer)[^.]*\."
    r"|this is an open access article under the terms of the creative commons[^.]*\."
    r"|\b\d{2,4}\s+[A-Z][a-z]+ et al\."   # page-number + running-head author line
)


def extract_claims(body_text: str) -> List[Dict]:
    """Sentence-level claim extraction. Skips headings and PDF-conversion
    noise (image placeholders, running headers/footers). Known limitation:
    naive sentence splitting on '. ' will occasionally mis-split on
    abbreviations (e.g. 'e.g.') — acceptable for now per the handoff's
    'robust enough, not universal' bar."""
    lines = []
    for line in body_text.split("\n"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("**==>") or "intentionally omitted" in s:
            continue
        lines.append(s)
    prose = " ".join(lines)
    prose = _BOILERPLATE_RE.sub(" ", prose)
    prose = re.sub(r"\s+", " ", prose).strip()

    claims = []
    for sent in SENTENCE_SPLIT_RE.split(prose):
        sent = sent.strip()
        markers = CITATION_RE.findall(sent)
        if not markers:
            continue
        citations = sorted({n for marker in markers for n in expand_marker(marker)})
        if citations:
            claims.append({"sentence": sent, "citations": citations})
    return claims


# ── Abstract lookup (library-first, then live multi-source fetch) ────────────
def _library_record_by_doi(doi: str) -> Optional[dict]:
    for rec in ar.load_library():
        if rec.get("DOI", "").lower() == doi.lower():
            return rec
    return None


def get_abstract(doi: str) -> dict:
    """Returns {"abstract": str, "abstract_source": str, "title": str}.
    Checks library.csl.json first (already-merged, already has an abstract
    field for entries added since the multi-source merge); otherwise fetches
    fresh via the same Crossref+PubMed+OpenAlex merge add_reference.py uses.
    Never writes to library.csl.json — read-only with respect to that file."""
    lib_rec = _library_record_by_doi(doi)
    if lib_rec and lib_rec.get("abstract"):
        return {
            "abstract": lib_rec["abstract"],
            "abstract_source": "library.csl.json (cached)",
            "title": lib_rec.get("title", ""),
        }

    try:
        msg = ar.fetch_crossref(doi)
    except Exception as e:
        return {"abstract": "", "abstract_source": "", "title": "", "error": f"Crossref fetch failed: {e}"}

    ar.RAW_DIR.mkdir(exist_ok=True)
    raw_path = ar.RAW_DIR / f"{ar.safe_filename(doi)}.json"
    if not raw_path.exists():
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(msg, f, indent=2, ensure_ascii=False)

    pmid = ar.fetch_pmid(doi)
    time.sleep(0.3)
    pubmed_record = ar.fetch_pubmed_record(pmid) if pmid else None
    openalex_record = ar.fetch_openalex(doi)
    merged = ar.merge_metadata(msg, pubmed_record, openalex_record)

    return {
        "abstract": merged.get("abstract", ""),
        "abstract_source": merged.get("abstract_source", ""),
        "title": merged.get("title", ""),
    }


# ── LLM call, cached by hash ─────────────────────────────────────────────────
def _call_hash(model: str, system: str, user: str) -> str:
    payload = json.dumps({"model": model, "system": system, "user": user}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def parse_verdict(text: str) -> dict:
    verdict_m = re.search(r"VERDICT:\s*(SUPPORTED|PARTIALLY_SUPPORTED|UNSUPPORTED)", text)
    flag_type_m = re.search(r"FLAG_TYPE:\s*(TOPIC_MISMATCH|NUMBER_CONTRADICTION|NOT_MENTIONED|NONE)", text)
    quote_m = re.search(r"QUOTE:\s*(.*?)(?:\n\s*GAP:|$)", text, re.DOTALL)
    gap_m = re.search(r"GAP:\s*(.*)", text, re.DOTALL)
    return {
        "verdict": verdict_m.group(1) if verdict_m else "PARSE_ERROR",
        "flag_type": flag_type_m.group(1) if flag_type_m else ("NONE" if verdict_m and verdict_m.group(1) == "SUPPORTED" else "UNKNOWN"),
        "quote": quote_m.group(1).strip() if quote_m else "",
        "gap": gap_m.group(1).strip() if gap_m else "",
    }


def _run_llm_check(system: str, user: str) -> dict:
    """Runs (or replays from cache) one LLM support check. Returns the parsed
    verdict plus the call hash for traceability back to the full logged call."""
    model = llm_client.ANTHROPIC_MODEL if llm_client.BACKEND == "anthropic" else llm_client.BACKEND
    call_hash = _call_hash(model, system, user)

    LLM_CALL_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = LLM_CALL_DIR / f"{call_hash}.json"
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            record = json.load(f)
    else:
        result = llm_client.complete(system, user)
        parsed = parse_verdict(result["text"])
        record = {
            "hash": call_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "backend": result["backend"],
            "model": result["model"],
            "system": system,
            "user": user,
            "output_text": result["text"],
            "parsed": parsed,
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)

    return {"call_hash": call_hash, **record["parsed"]}


def check_claim(claim: str, abstract: str) -> dict:
    """Gate 1: abstract-only support check."""
    user = USER_TEMPLATE.format(claim=claim, abstract=abstract)
    return _run_llm_check(SYSTEM_PROMPT, user)


def check_claim_fulltext(claim: str, fulltext: str) -> dict:
    """Gate 2: full-text support check, only run when gate 1 is non-SUPPORTED
    and an open-access full text was available."""
    user = USER_TEMPLATE_FULLTEXT.format(claim=claim, fulltext=fulltext[:FULLTEXT_CHAR_LIMIT])
    return _run_llm_check(SYSTEM_PROMPT_FULLTEXT, user)


# ── Main ──────────────────────────────────────────────────────────────────────
def load_from_pmcid(pmcid: str) -> tuple:
    """Alternate input path: PMC structured JATS XML instead of a local .md/
    .pdf file. Returns (body_with_markers, refs, known_dois) — refs is
    {n: ref_text} same as the Markdown path so extract_claims()/downstream
    code doesn't need to know which path was used; known_dois is {n: doi}
    for references where JATS already gave us the DOI directly, letting the
    main loop skip ref_resolver.resolve_reference() entirely for those."""
    data = jats_parser.fetch_and_parse(pmcid)
    if data is None:
        print(f"ERROR: could not parse JATS XML for PMCID {pmcid}", file=sys.stderr)
        sys.exit(1)
    refs = {n: info["ref_text"] for n, info in data["refs"].items()}
    known_dois = {n: info["doi"] for n, info in data["refs"].items() if info["doi"]}
    return data["body"], refs, known_dois


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("manuscript", nargs="?", default=None, help="Path to .md or .pdf of the published paper")
    parser.add_argument("--pmcid", default=None, help="PMC ID (numeric, no 'PMC' prefix) — fetches structured JATS XML instead of a local file")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N claims (testing)")
    parser.add_argument("--dry-run", action="store_true", help="Parse/resolve/fetch abstracts, skip LLM calls")
    args = parser.parse_args()

    if not args.manuscript and not args.pmcid:
        print("ERROR: provide either a manuscript path or --pmcid", file=sys.stderr)
        sys.exit(1)

    known_dois: Dict[int, str] = {}
    if args.pmcid:
        paper_label = f"PMC{args.pmcid}"
        body, refs, known_dois = load_from_pmcid(args.pmcid)
    else:
        path = Path(args.manuscript)
        if not path.exists():
            print(f"ERROR: not found: {path}", file=sys.stderr)
            sys.exit(1)
        paper_label = path.name
        md_text = load_manuscript(path)
        body, ref_section = split_body_and_refs(md_text)
        refs = rr.parse_reference_list(md_text)

    claims = extract_claims(body)
    if args.limit:
        claims = claims[: args.limit]

    print(f"Paper: {paper_label}")
    print(f"References parsed: {len(refs)}")
    if known_dois:
        print(f"  ({len(known_dois)} of these have a DOI given directly in the source XML — resolver will be skipped for those)")
    print(f"Claims (sentences with citations) found: {len(claims)}")
    if args.dry_run:
        print("(--dry-run: LLM calls will be skipped)")
    print()

    all_checks = []
    flagged = []
    doi_cache: Dict[int, dict] = {}   # citation number -> resolution result (this run)
    abstract_cache: Dict[str, dict] = {}  # doi -> abstract dict (this run)

    for i, claim in enumerate(claims):
        for n in claim["citations"]:
            ref_text = refs.get(n)
            if ref_text is None:
                entry = {
                    "sentence": claim["sentence"], "citation_number": n,
                    "status": "reference_not_in_list",
                }
                all_checks.append(entry); flagged.append(entry)
                continue

            if n in known_dois:
                doi_cache.setdefault(n, {"resolved": True, "doi": known_dois[n], "score": {"source": "jats_xml_direct"}})
            if n not in doi_cache:
                doi_cache[n] = rr.resolve_reference(ref_text)
            resolution = doi_cache[n]

            if not resolution["resolved"]:
                entry = {
                    "sentence": claim["sentence"], "citation_number": n, "ref_text": ref_text,
                    "status": "unresolved_reference", "reason": resolution["reason"],
                    "best_candidate": resolution.get("best_candidate"),
                }
                all_checks.append(entry); flagged.append(entry)
                continue

            doi = resolution["doi"]
            if doi not in abstract_cache:
                abstract_cache[doi] = get_abstract(doi)
            abs_info = abstract_cache[doi]

            if not abs_info.get("abstract"):
                entry = {
                    "sentence": claim["sentence"], "citation_number": n, "ref_text": ref_text, "doi": doi,
                    "status": "no_abstract_found", "error": abs_info.get("error", ""),
                }
                all_checks.append(entry); flagged.append(entry)
                continue

            if args.dry_run:
                entry = {
                    "sentence": claim["sentence"], "citation_number": n, "ref_text": ref_text, "doi": doi,
                    "status": "dry_run_skipped", "abstract_source": abs_info["abstract_source"],
                }
                all_checks.append(entry)
                continue

            print(f"  [{i+1}/{len(claims)}] checking citation [{n}] ...", end=" ", flush=True)
            verdict = check_claim(claim["sentence"], abs_info["abstract"])
            print(verdict["verdict"])

            entry = {
                "sentence": claim["sentence"], "citation_number": n, "ref_text": ref_text, "doi": doi,
                "abstract_source": abs_info["abstract_source"],
                "abstract_verdict": verdict["verdict"], "abstract_flag_type": verdict["flag_type"],
                "quote": verdict["quote"], "gap": verdict["gap"],
                "llm_call_hash": verdict["call_hash"],
                "final_gate": "abstract",
                "final_verdict": verdict["verdict"], "final_flag_type": verdict["flag_type"],
            }

            # Gate 2: abstract said not-SUPPORTED — try the full text before
            # calling this a confirmed flag, same as a human reviewer would.
            if verdict["verdict"] != "SUPPORTED":
                fulltext = fulltext_fetch.fetch_fulltext(doi)
                entry["fulltext_available"] = fulltext is not None
                if fulltext:
                    ft_verdict = check_claim_fulltext(claim["sentence"], fulltext)
                    entry["fulltext_verdict"] = ft_verdict["verdict"]
                    entry["fulltext_flag_type"] = ft_verdict["flag_type"]
                    entry["fulltext_quote"] = ft_verdict["quote"]
                    entry["fulltext_gap"] = ft_verdict["gap"]
                    entry["fulltext_llm_call_hash"] = ft_verdict["call_hash"]
                    entry["final_gate"] = "fulltext"
                    entry["final_verdict"] = ft_verdict["verdict"]
                    entry["final_flag_type"] = ft_verdict["flag_type"]

            all_checks.append(entry)
            if entry["final_verdict"] != "SUPPORTED":
                flagged.append(entry)

    counts: Dict[str, int] = {}
    for entry in all_checks:
        key = entry.get("final_verdict") or entry.get("status")
        counts[key] = counts.get(key, 0) + 1

    paper_stem = (f"PMC{args.pmcid}" if args.pmcid else Path(args.manuscript).stem).replace(" ", "_")
    output = {
        "paper": paper_label,
        "source_file": f"pmcid:{args.pmcid}" if args.pmcid else str(Path(args.manuscript)),
        "generated": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        # Always the automated pipeline — distinguishes this from manual/
        # interactive review files, which use a different schema entirely
        # (see results/preview/*.manual-preview.json) and must never be
        # producible by this script.
        "provenance": "automated_pipeline",
        "counts": counts,
        "flagged": flagged,
        "all_checks": all_checks,
    }

    FLAGS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FLAGS_DIR / f"{paper_stem}.json"
    if "manual" in out_path.name.lower():
        print(f"ERROR: refusing to write pipeline output to a 'manual'-named path: {out_path}", file=sys.stderr)
        sys.exit(1)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session_path = SESSION_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{paper_stem}.json"
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump({
            "paper": paper_label, "args": vars(args), "counts": counts,
            "n_claims": len(claims), "n_checks": len(all_checks),
            "flags_output": str(out_path),
        }, f, indent=2, ensure_ascii=False)

    print(f"\nCounts: {counts}")
    print(f"Flag report: {out_path}")
    print(f"Session log: {session_path}")


if __name__ == "__main__":
    main()
