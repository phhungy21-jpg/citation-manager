# Audit Project — Status Snapshot

Last updated: 2026-07-06

**Current phase:** Phase 4 just landed — multi-format ingestion
(`format_router.py`) and hardened reference resolution (dedup ledger,
`doi_invalid` status, exact/fuzzy title tiers with an ambiguity-gap rule,
escalating fallback cascade). Phase 3's n=100 JAMA Network Open run is still
blocked on the same thing it always was: **`ANTHROPIC_API_KEY` is still not
set in this environment.** Phase 4 doesn't change that — it's independent
hardening of the ingestion/resolution layers underneath check_claims.py.

**What check_claims.py does (updated):** for a published paper — `.md`
(handled directly, unchanged, years of hand-tuned fixes), any of
`.pdf`/`.docx`/`.tex`/`.html`/`.htm`/`.xml` (via the new `format_router.py`),
or `--pmcid <id>` (PMC structured XML) — extracts every sentence with an
in-text citation marker, resolves each numbered reference to a DOI, fetches
the abstract, and asks an LLM to classify SUPPORTED / PARTIALLY_SUPPORTED /
UNSUPPORTED with a mandatory quote and a FLAG_TYPE. Anything non-SUPPORTED
triggers gate 2 (Unpaywall OA lookup + full-text re-check). Flag entries now
also surface `resolution_method` and a distinct `doi_invalid` status.

**New this session — Phase 4, multi-format ingestion:**
- `format_router.py` dispatches by file suffix: `.xml` passthrough,
  `.pdf` → GROBID (`grobid_client.py`) with automatic fallback to the
  existing pymupdf4llm path when GROBID is unreachable (it isn't running in
  this environment — `is_available()` correctly reports this and the
  fallback branch is what's actually been exercised), `.docx`/`.tex`/
  `.html`/`.htm` → `pandoc_convert.py` (pandoc's JATS writer, confirmed
  installed: pandoc 3.9).
- `tei_to_jats.py` normalizes GROBID TEI into the same standard shape
  `jats_parser.py` already produces for PMC JATS. Table/figure content is
  tagged into `low_confidence_spans`, never read — no reading agent exists
  yet, confirmed out of scope. Caught a real bug during testing: `xml:id`
  lives in the XML namespace, not TEI's — the first version silently failed
  to link any citation marker.
- `pandoc_convert.py` handles both linked-citation manuscripts (real
  `<xref>`/`<ref-list>`, reuses `jats_parser.parse_jats()` as-is) and
  unlinked raw reference lists (the common case — extracts structurally by
  JATS `<sec>` title rather than a markdown-heading regex, since pandoc's
  JATS output has no `#` syntax). Also fixed a real bug in the shared
  `jats_parser.parse_jats()`: pandoc's JATS root *is* `<article>`, which the
  original PMC-oriented `.//article` lookup (descendants only) never
  matched.

**New this session — Phase 4, hardened reference resolution:**
- `citation_registry.py`: audit-only dedup/resolution ledger at
  `data/citation_registry.json`, separate from `library.csl.json` (which
  stays exclusively the manuscript bibliography). Confirmed a second
  `resolve_reference()` call for an already-seen reference makes zero
  network calls.
- `ref_resolver.py`'s `resolve_reference()` rebuilt as a 7-step cascade:
  literal-DOI validation (404 → new `doi_invalid` status, distinct from
  `unresolved`) → dedup lookup → book-chapter filter (unchanged) → exact
  contiguous-title match (new) → fuzzy match (threshold raised 0.70→0.85)
  with a new ambiguity-gap rule (>0.10 lead over the runner-up required, or
  it's reported unresolved rather than guessed) → escalating fallback
  cascade → unresolved stub. Every outcome is registered to the ledger.
- `fallback_sources.py`: Semantic Scholar → DataCite → arXiv (bioRxiv/
  medRxiv have no title-search API — documented no-op, not a gap) → CORE
  (skipped cleanly without `CORE_API_KEY`, confirmed doesn't block the rest
  of the cascade).

**Verified this session:** `.md` path reruns are byte-identical to
pre-Phase-4 output (Karabulut 2020, before/after). New `.html`-via-pandoc
path exercised end-to-end against a synthetic manuscript — correctly left
fabricated references unresolved rather than guessing. Dedup ledger
confirmed to eliminate network calls on a rerun.

**Not yet tested:** GROBID's actual PDF conversion path — no live GROBID
instance in this environment, so `grobid_client.py`/`tei_to_jats.py` are
only verified against a hand-built TEI fixture, not a real PDF through a
real running service. `fallback_sources.core_search()` is only verified to
skip cleanly without `CORE_API_KEY` — not live-tested with one.

**Next action, in order:**
1. Get `ANTHROPIC_API_KEY` set — the actual blocker for Phase 3's live n=100
   run and Phase 2c's first live-vs-manual precision/recall comparison.
   Nothing about Phase 4 changes this priority.
2. Once a GROBID instance is available (`docker run -p 8070:8070
   lfoppiano/grobid:0.8.0`), run `format_router.route()` against a real PDF
   to validate the live path (currently only the fallback branch is
   real-tested).
3. Optional: set `CORE_API_KEY` and confirm `fallback_sources.core_search()`
   actually returns a match against a known DOI.

**Deferred (not blocking, revisit later):**
1. Backfill the `abstract` field onto the existing library entry
   (jia2023SustainableFunctionalUrethral).
2. Whether to add a `--refresh` path to `add_reference.py`.
3. Unit-superscript false positives (`kg/m[2]` read as citing ref 2) in the
   PDF-to-Markdown path — irrelevant for the JATS/GROBID paths.
4. Gate 2 full-text fetch only succeeds for direct-PDF OA links (fails
   closed on landing pages) — same limitation applies to the n=100 run.
5. Whether to also sample flagship JAMA once the JAMA Network Open n=100
   run is complete.
6. Bracketed-sample-size-as-citation false positive (e.g. `"0.2% [12]"`) —
   found in paper 6 of the first-10 batch, no safe fix identified yet.
7. Corrupted/garbled or missing Crossref abstracts — data-quality issues at
   the source, currently handled by marking NOT_EVALUABLE.
8. Paper 8's high unresolved-reference rate for non-biomedical
   (economics/marketing) DOIs — worth checking if it recurs across the full
   n=100 run.
9. Table/figure reading agent — currently only tagged as
   `low_confidence_spans`, no content extraction (confirmed out of scope).
10. GROBID's citation-parsing service (`grobid_client.parse_citations()`,
    used by `pandoc_convert.py`'s unlinked-reference fallback) is wired up
    but, like the rest of the GROBID client, untested against a live
    instance.

**Do not run the n=100 sample without `ANTHROPIC_API_KEY`.** Everything
else required before that run (sample frame, adjudication criteria,
retrieval path, frozen sample list) is unchanged and still in place.
