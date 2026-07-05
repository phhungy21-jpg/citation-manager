# Audit Project — Manifest

Inventory of what exists in `audit/` and its build status. Update this whenever
a file is added, a phase advances, or a script's status changes. This is the
"what" — see NOTES.md for the "why."

Status legend: `planned` (not started) · `wip` · `done` · `blocked`

## Directory map

```
audit/
  NOTES.md                    running decision log (this project)
  MANIFEST.md                 this file
  STATUS.md                   one-page current-phase snapshot
  logs/
    llm_calls/                one file per LLM call, keyed by input hash
    sessions/                 one file per script run (what ran, when, args, outcome)
  cache/
    abstracts/
      pubmed/                 raw efetch XML/JSON responses, keyed by PMID
      crossref/                raw abstract-bearing CrossRef responses, keyed by DOI
      openalex/                raw OpenAlex works responses, keyed by DOI/OpenAlex ID
  data/
    library_abstracts.json    parallel abstract store keyed by citekey (Phase 1 output)
    manuscripts/               input papers being audited (md/pdf/docx)
    preregistration/            dated pre-registration criteria docs (Phase 3)
  results/
    flags/                     flag reports per paper (automated pipeline output, review queue)
    preview/                   manual/interactive calibration reviews (provenance: manual_human_review — never pipeline output)
    examples/                  full evidence chains for the sharpest cases (internal, unanonymized)
```

## Scripts (top level of `audit/`)

| File | Phase | Status | Notes |
|---|---|---|---|
| `pdf_to_md.py` | 2 | **done** | vendored/standalone (no `doctools` dependency); CLI: `python pdf_to_md.py paper.pdf [--output out.md \| --out-dir dir/] [--overwrite]`; pymupdf4llm extraction + header/footer/page-number cleanup |
| `llm_client.py` | 2 | **done** | swappable via `LLM_BACKEND` env var; only `anthropic` implemented (REST call, `ANTHROPIC_API_KEY` required); live call untested — no key in this environment |
| `ref_resolver.py` | 2/4 | **done, hardened** | numbered ref text -> DOI. Original Crossref-only resolution (confidence bar, commentary/book-chapter rejection filters) tested against 3 real papers — Jia 2023 (54/57 resolved), Kang 2022 (24/27), Karabulut 2020 (13/22, genuine OCR-noise outlier). Phase 4 hardening: dedup lookup before any API call (`citation_registry.lookup()`); literal-DOI-in-text validation with a distinct `doi_invalid` status (a broken DOI is a finding, not just an obstacle); word-overlap threshold raised 0.70→0.85; new exact-contiguous-title match tier (`title_exact`, stricter than fuzzy overlap); ambiguity-gap rule (two comparably-scored fuzzy candidates → unresolved, never guessed between); escalating fallback cascade (`fallback_sources.py`) tried only after Crossref exact+fuzzy both fail. Every outcome registered to `citation_registry.py`, tagged with a `resolution_method` |
| `check_claims.py` | 2/3/4 | **done, calibrated** | manuscript -> (claim, ref) pairs -> abstract -> LLM flag with FLAG_TYPE (TOPIC_MISMATCH/NUMBER_CONTRADICTION/NOT_MENTIONED); accepts a local `.md` (handled directly, unchanged), any of `.pdf`/`.docx`/`.tex`/`.html`/`.htm`/`.xml` (via `format_router.py`, Phase 4), OR `--pmcid <id>` (PMC structured XML, preferred for OA papers); triggers gate 2 (`fulltext_fetch.py`) on any non-SUPPORTED verdict; flag entries now surface `resolution_method` and a distinct `doi_invalid` status alongside the existing `unresolved_reference` |
| `fulltext_fetch.py` | 2 | **done** | gate 2 of the cascade — Unpaywall OA lookup, fetches + converts full text via `pdf_to_md`, cached by DOI; only succeeds for direct-PDF OA links, fails closed on landing pages |
| `jats_parser.py` | 3 | **done, smoke-tested** | fetches + parses PMC structured JATS XML as an alternative to PDF-to-Markdown; converts `<xref ref-type="bibr">` tags to `[n]` markers directly (no bracket-regex guessing), extracts DOIs given directly in reference entries (skips `ref_resolver.py` for those), skips table/figure subtrees entirely. Smoke-tested on 3 real JAMA Network Open articles: 100%/100%/100% reference-list parse rate, 93-100% of references had a direct DOI from XML |
| `sample_jama_network_open.py` | 3 | **done** | pulls JAMA Network Open "Original Investigation" articles from PMC (filtered on `<subj-group subj-group-type="heading">`, not the `article-type` attribute), shuffles before fetching (fixed a real sampling-bias bug — early-stop + unshuffled order would have given later records zero selection probability), freezes a random n=100 sample to `data/preregistration/jama_network_open_sample_2025_100.json` |
| `format_router.py` | 4 | **wip** | single entry point for local-file ingestion: dispatches `.xml`→passthrough, `.pdf`→`grobid_client`(+pymupdf4llm fallback), `.docx`/`.tex`/`.html`/`.htm`→`pandoc_convert`. `.md` deliberately stays a separate path in `check_claims.py` (see its docstring) |
| `grobid_client.py` | 4 | **wip, untested against a live GROBID instance** | HTTP client for a local GROBID service (not bundled — user-run, e.g. via Docker). `is_available()` health-checks `/api/isalive`; `convert()` posts a PDF to `/api/processFulltextDocument`, caches raw TEI by PDF content hash; `parse_citations()` wraps GROBID's separate citation-parsing endpoint. Every entry point returns `None`/`{}` on any failure so callers fall back cleanly — no GROBID service reachable in this environment, so only unit-tested against a hand-built TEI fixture, not a real PDF |
| `tei_to_jats.py` | 4 | **done, unit-tested** | normalizes GROBID TEI XML into the same `{title, doi, pmid, body, refs, low_confidence_spans}` shape `jats_parser.py` produces for PMC JATS. Table/figure content is tagged into `low_confidence_spans`, never read (no reading agent exists yet — confirmed out of scope this pass). Caught and fixed a real bug during testing: `xml:id` lives in the XML namespace, not the TEI namespace — the original lookup silently never matched, which broke `<ref target="#bN">`→`<biblStruct xml:id="bN">` linking without raising |
| `pandoc_convert.py` | 4 | **done, smoke-tested** | routes docx/LaTeX/Markdown/HTML through `pandoc -t jats`. Detects two cases: real linked citations (Zotero/EndNote/Mendeley field codes, or pandoc's own `--citeproc`) reuse `jats_parser.parse_jats()` as-is; unlinked raw reference lists (the common case — pandoc has nothing to link) fall back to structural extraction by JATS `<sec>` title rather than a markdown-style heading regex (the source has no `#` syntax once pandoc's JATS writer runs). If GROBID is reachable, also runs its citation-parsing service over the raw ref strings, best-effort, non-blocking |
| `fallback_sources.py` | 4 | **done, live-tested** | escalating reference-resolution fallback beyond Crossref: Semantic Scholar → DataCite → arXiv (bioRxiv/medRxiv have no title-search API, documented no-op) → CORE (skipped cleanly without `CORE_API_KEY`, same fail-closed posture as `llm_client.py`'s `ANTHROPIC_API_KEY`). Every raw response cached by query hash under `cache/fallback/<source>/` |
| `citation_registry.py` | 4 | **done, live-tested** | audit-only dedup + resolution ledger at `data/citation_registry.json`, deliberately separate from `library.csl.json` (which stays exclusively the manuscript bibliography, only ever touched by `add_reference.py`, per CLAUDE.md). Keyed by DOI when known, else normalized `title\|year`. Confirmed a second `resolve_reference()` call for an already-registered reference makes zero network calls |

## Existing pipeline (extended, not replaced)

| File | Location | Status |
|---|---|---|
| `add_reference.py` | `citation-pipeline/` | **done** — now merges Crossref + PubMed efetch + OpenAlex per DOI, standardized/backfilled/deduped, `abstract` field written directly into `library.csl.json` records |
| `format_jama.py` | `citation-pipeline/` | done, in use, untouched |
| `validate_citations.py` | `citation-pipeline/` | done, in use, untouched |
| `library.csl.json` | `citation-pipeline/` | 1 entry (jia2023SustainableFunctionalUrethral) — added before the abstract-merge change, does not yet have an `abstract` field (re-add not attempted; duplicate-DOI check skips it) |

## Plan change (2026-07-01)

Phase 1 abstract retrieval was originally planned as a standalone
`fetch_abstracts.py` writing to `data/library_abstracts.json` (parallel file,
to avoid bloating the bibliography). Decision reversed: abstracts are now
pulled directly into `add_reference.py` and stored as an `abstract` field on
each CSL JSON record in `library.csl.json` itself, alongside a new
`OPENALEX-ID` field (same non-standard-extension pattern as the existing
`PMID` field). Raw per-source caching lives at the top level
(`raw_crossref/`, `raw_pubmed/`, `raw_openalex/`), same convention as before
— **not** under `audit/cache/abstracts/`, which is now unused for this
purpose. `registry.csv` gained `has_abstract` / `abstract_source` /
`openalex_id` columns; header migration is automatic on next run.

Standardization/backfill priority (see `add_reference.py` docstring):
title/authors/journal/year — Crossref → PubMed → OpenAlex; abstract —
PubMed → Crossref → OpenAlex. First non-empty source wins per field, no
blending within a field.

`audit/cache/abstracts/` and `audit/data/library_abstracts.json` in the
original scaffold are now stale — left in place but unused unless we decide
we need a project-specific abstract override later.

## Data artifacts

| File | Produced by | Status |
|---|---|---|
| `docs/adjudication-criteria.md` | manual, dated | **done** — verdict categories, synthesis-citation rule, primary outcome, second-reviewer decision, sample-frame pointer, all dated 2026-07-01 |
| `data/preregistration/2026-07-01_jama-network-open-100.md` | manual, dated | **done** — narrative pre-registration for the n=100 run: sample frame, retrieval method, outcomes, reviewer, explicitly-deferred items |
| `data/preregistration/jama_network_open_sample_2025_100.json` | `sample_jama_network_open.py` | **done, frozen** — 100 articles (PMCID/PMID/DOI/title/heading/ref-count/body-length), drawn from a 429-article qualifying pool. Not to be regenerated after checking begins |
| `cache/ref_resolution/<hash>.json` | `ref_resolver.py` | in use — Crossref bibliographic search results, keyed by query hash (mostly bypassed for JATS-sourced papers, which carry DOIs directly) |
| `cache/unpaywall/<doi>.json`, `cache/fulltext/<doi>.md` | `fulltext_fetch.py` | in use — OA status + converted full text, keyed by DOI |
| `cache/jats/<pmcid>.xml` | `jats_parser.py` | in use — raw PMC structured XML, keyed by PMCID |
| `results/flags/<paper>.json` | `check_claims.py` | in use — full record per paper: counts, flagged subset, every check. `"provenance": "automated_pipeline"` always |
| `results/preview/<paper>.manual-preview.json` | manual review (this session) | in use — 3 papers reviewed (early calibration). `"provenance": "manual_human_review"`, never pipeline-writable (guarded in check_claims.py) |
| `results/preview/three_paper_review_summary.md` | manual review (this session) | in use — condensed cross-paper summary, human-readable |
| `results/preview/jama_network_open/<pmcid>.manual-preview.json` | manual review (this session) | in use — first 10 of the n=100 JAMA Network Open sample reviewed, same schema/provenance convention as above |
| `results/preview/jama_network_open/ten_paper_review_summary.md` | manual review (this session) | in use — condensed cross-paper summary for the first-10 batch: 486 citations checked, 404 SUPPORTED/56 PARTIAL/15 UNSUPPORTED/11 NOT_EVALUABLE, plus a punch list of new pipeline bugs and data-quality issues found |
| `logs/llm_calls/<hash>.json` | `check_claims.py` | **still empty — no API key set yet.** Deliberately never populated by manual review; synthetic entries here would corrupt the real-API-call invariant this directory exists to guarantee |
| `logs/sessions/<timestamp>_<paper>.json` | `check_claims.py` (dry-run) | in use — automated dry-run session logs across 6 early-calibration/smoke-test papers plus the 10 first-batch JAMA Network Open papers |
| `logs/sessions/<timestamp>_<paper>_manual-review.json` | manual review (this session) | in use — session logs recording each interactive review pass, `"provenance": "manual_human_review"`, links to preceding dry-run sessions and the resulting manual-preview file |

## Phase checklist

- [x] Phase 1: multi-source retrieval (Crossref + PubMed + OpenAlex), merged into `library.csl.json` via `add_reference.py`
- [x] Phase 2 prep: PDF→Markdown conversion (`pdf_to_md.py`), vendored standalone, smoke-tested
- [x] Phase 2: `check_claims.py` built with FLAG_TYPE taxonomy and 2-gate (abstract + full-text) cascade
- [x] Phase 2b: 3-paper manual calibration pass (Jia 2023, Kang 2022, Karabulut 2020) — 8 real pipeline bugs found and fixed. See `results/preview/three_paper_review_summary.md` and `docs/adjudication-criteria.md`.
- [x] Phase 3 prep: sample frame, primary outcome, second-reviewer decisions locked in `docs/adjudication-criteria.md` + dated pre-registration doc
- [x] Phase 3 prep: JATS XML retrieval path built (`jats_parser.py`) and smoke-tested on 3 real JAMA Network Open articles — 100% reference-list parse rate on all 3
- [x] Phase 3 prep: n=100 JAMA Network Open sample pulled and frozen (`jama_network_open_sample_2025_100.json`), with a real sampling-bias bug caught and fixed before freezing
- [x] Phase 3a: first 10/100 manual adjudication pass (abstract-only, standing in for the LLM API) — 486 citations checked, 2 more real pipeline bugs found and fixed (placeholder abstracts, F-statistic-bracket misparsing), several new data-quality issues logged. See `results/preview/jama_network_open/ten_paper_review_summary.md`.
- [ ] Phase 2c: first **live** LLM run (needs `ANTHROPIC_API_KEY`) — compare against the manual-preview files as the first precision/recall measurement
- [ ] Phase 3: run the full n=100 sample live (needs `ANTHROPIC_API_KEY`) — the only remaining blocker
- [ ] Phase 1b (optional): decide whether to backfill the abstract field onto the existing library entry, which predates the multi-source merge
- [ ] Phase 1c (optional): decide whether `add_reference.py` needs a `--refresh` flag to re-pull already-added DOIs
- [ ] Fix unit-superscript false-positive citation markers (`kg/m[2]` etc.) — PDF-to-Markdown path only, irrelevant to JATS
- [ ] Examples extracted and anonymized for writeup
- [x] Phase 4: multi-format ingestion (`format_router.py`, `grobid_client.py`, `tei_to_jats.py`, `pandoc_convert.py`) normalizing PDF/docx/LaTeX/HTML/JATS to one standard shape; GROBID auto-falls-back to the existing pymupdf4llm path when unreachable (not running in this environment — untested against a live instance, only a hand-built TEI fixture)
- [x] Phase 4: hardened reference resolution — dedup ledger (`citation_registry.py`), `doi_invalid` status, exact/fuzzy title tiers with an ambiguity-gap rule, escalating fallback cascade (`fallback_sources.py`: Semantic Scholar/DataCite/arXiv, CORE gated behind `CORE_API_KEY`)
- [ ] Phase 4 follow-up: test `grobid_client.py`/`format_router.py`'s PDF path against a real running GROBID instance once available (`docker run -p 8070:8070 lfoppiano/grobid:0.8.0`) — currently only exercises the fallback branch
- [ ] Phase 4 follow-up: table/figure reading agent — currently only tagged as `low_confidence_spans`, no content extraction (confirmed out of scope for this pass)
- [ ] Phase 4 follow-up: set `CORE_API_KEY` and live-test `fallback_sources.core_search()` — currently only verified to skip cleanly without one
