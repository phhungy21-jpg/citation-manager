# Audit Project — Status Snapshot

Last updated: 2026-07-01

**Current phase:** First 10/100 manual adjudication pass (abstract-only,
Gate 1 equivalent, standing in for the not-yet-available LLM API) complete.
Sample frame, primary outcome, and reviewer decisions are locked in
`docs/adjudication-criteria.md` and `data/preregistration/2026-07-01_jama-network-open-100.md`.
A frozen, properly-random n=100 sample of JAMA Network Open Original
Investigations is drawn (`data/preregistration/jama_network_open_sample_2025_100.json`).
A new retrieval path (`jats_parser.py`, PMC structured XML) replaces PDF-to-
Markdown for this run and was smoke-tested on 3 real sampled articles with
excellent results (see below). **The only remaining blocker to actually
running the automated n=100 sample is `ANTHROPIC_API_KEY`, still not set in
this environment.**

**First 10/100 manual adjudication — see
`results/preview/jama_network_open/ten_paper_review_summary.md` for full
detail and per-paper `.manual-preview.json` files:** 486 citation-instances
checked across 10 papers — 404 (83.1%) SUPPORTED, 56 (11.5%)
PARTIALLY_SUPPORTED, 15 (3.1%) UNSUPPORTED, 11 (2.3%) NOT_EVALUABLE
(data-quality artifacts). Flagged rate among evaluable citations: 14.9%.
**Not a population estimate — first 10 of 100, solo review, abstract-only
(no Gate 2 follow-up performed in this pass).** 2 more real pipeline bugs
found and fixed (placeholder abstracts, F-statistic-bracket
misparsing — see NOTES.md); several new data-quality issues found and
logged but not fixed (bracketed-sample-size false positives, corrupted/
missing Crossref abstracts, one paper's very high unresolved-reference rate
for non-biomedical DOIs). Strongest miscitation candidate found:
PMC11780478 citing an unrelated semaglutide-vs-tirzepatide trial for a
statistics-methodology claim — good first Gate-2 target once the API key
is available.

**What check_claims.py does:** for a published paper (.md/.pdf, or now
`--pmcid <id>` for PMC structured XML), extracts every sentence with an
in-text citation marker, resolves each numbered reference to a DOI (direct
from JATS XML when available, else Crossref bibliographic search with a
confidence bar), fetches the abstract, and asks an LLM to classify
SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED with a mandatory quote and a
FLAG_TYPE (TOPIC_MISMATCH / NUMBER_CONTRADICTION / NOT_MENTIONED). Anything
non-SUPPORTED triggers gate 2 (Unpaywall OA lookup + full-text re-check).

**3-paper manual calibration (Jia 2023, Kang 2022, Karabulut 2020) —
already done, see `results/preview/three_paper_review_summary.md`:** 71
citations checked, 12 (17%) UNSUPPORTED, 2 verified real miscitations via
gate 2, 1 gate-2 rescue of a false positive. **3-paper convenience sample —
not a population estimate.** 8 real pipeline bugs found and fixed against
these three PDF-converted papers.

**New this session — JATS XML retrieval path, validated on 3 real JAMA
Network Open articles:**
- `jats_parser.py`: fetches + parses PMC structured XML instead of PDF-to-
  Markdown. Reference lists have unambiguous boundaries (no more last-ref
  contamination), citation markers come from real `<xref ref-type="bibr">`
  tags (no more superscript/IQR-range false positives), and reference
  entries frequently carry the cited paper's DOI directly — smoke tests
  showed 93-100% of references per article had a DOI straight from the XML,
  letting `ref_resolver.py`'s Crossref search be skipped almost entirely.
- Reference-list parse rate on the 3 smoke-tested articles: **100%, 100%,
  100%** (38/38, 47/47, 40/40) — vs. 59-95% on the PDF-converted 3-paper
  calibration set. The entire class of PDF-conversion bugs (reference
  boundaries, heading regexes, running headers, superscripts) doesn't apply
  to this path.
- `sample_jama_network_open.py`: pulls PMC records for JAMA Network Open,
  filters on the `<subj-group subj-group-type="heading">` text (not the
  `article-type` attribute — that alone can't distinguish Original
  Investigations from Research Letters in this journal's JATS), and freezes
  a random sample. **Caught and fixed a real sampling-methodology bug**
  before freezing the final sample: an early-stopping optimization would
  have given every unfetched record zero selection probability unless the
  candidate ID list was shuffled *before* fetching — fixed by shuffling
  with the seed prior to any batch fetching.
- `check_claims.py` gained a `--pmcid` argument as an alternative to a
  local file path.

**Next action:** get `ANTHROPIC_API_KEY` set. Recommended order: (1) run
`check_claims.py` live (no `--dry-run`) on Jia 2023 first, diff against
`Jia_2023.manual-preview.json` as the first real precision/recall
measurement; (2) if that looks reasonable, run the full n=100 JAMA Network
Open sample per `data/preregistration/2026-07-01_jama-network-open-100.md`.

**Deferred (not blocking, revisit later):**
1. Backfill the `abstract` field onto the existing library entry
   (jia2023SustainableFunctionalUrethral).
2. Whether to add a `--refresh` path to `add_reference.py`.
3. Unit-superscript false positives (`kg/m[2]` read as citing ref 2) in the
   PDF-to-Markdown path — irrelevant for the JATS path, which doesn't have
   this failure mode, but still unpatched for any future PDF-based runs.
4. Gate 2 full-text fetch only succeeds for direct-PDF OA links (fails
   closed on landing pages) — same limitation applies to the n=100 run.
5. Whether to also sample flagship JAMA once the JAMA Network Open n=100
   run is complete (see pre-registration doc's "not decided yet" section).
6. Bracketed-sample-size-as-citation false positive (e.g. `"0.2% [12]"`) —
   found in paper 6 of the first-10 batch, no safe fix identified yet.
7. Corrupted/garbled or missing Crossref abstracts (duplicated JATS text,
   author-byline-only fields, website boilerplate, TOC-only fields for
   pre-1980s articles) — data-quality issues at the source, not fixable in
   our pipeline; currently handled by marking NOT_EVALUABLE.
8. Paper 8's high unresolved-reference rate for non-biomedical
   (economics/marketing) DOIs — worth checking if it recurs across the
   full n=100 run.

**Do not run the n=100 sample without `ANTHROPIC_API_KEY`.** Everything
else required before that run (sample frame, adjudication criteria,
retrieval path, frozen sample list) is in place as of this update.
