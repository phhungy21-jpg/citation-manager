# Audit Project — Running Notes

Freeform, dated decision log. Newest entries on top. This is the "why" ledger —
MANIFEST.md tracks "what exists," this tracks "why we chose it."

---

## 2026-07-06 — Phase 4: multi-format ingestion + hardened reference resolution

User handed over a detailed spec asking for two things: (1) normalize *any*
manuscript format (PDF/docx/LaTeX/md/HTML/JATS) to one standard shape before
claim-checking, using GROBID for PDFs and pandoc for everything else; (2) a
much stricter reference-resolution pipeline — dedup, an escalating fallback
cascade beyond Crossref, exact/fuzzy title tiers with an ambiguity-gap rule,
and explicit `doi_invalid`/`unresolved` outcomes with a persistent ledger.

Given the size of this change, four scoping questions were asked and
confirmed before writing any code (all went with the recommended option):
1. **GROBID isn't running locally** (no response on `:8070`) — built the
   client + TEI→JATS normalization anyway, with automatic fallback to the
   existing pymupdf4llm path (`pdf_to_md.py`) when GROBID is unreachable.
   Means this is untested against a live GROBID instance — only against a
   hand-built TEI fixture (see tei_to_jats.py bug below) — but the fallback
   branch is real-tested and the client activates the moment GROBID is
   running (`docker run -p 8070:8070 lfoppiano/grobid:0.8.0`).
2. **Table/figure handling** — tagged into `low_confidence_spans` only, no
   reading agent built (none existed in this codebase, confirmed out of
   scope for this pass).
3. **Fallback cascade** — Semantic Scholar + DataCite + arXiv/bioRxiv/medRxiv
   implemented now (all free, no key required); CORE gated behind
   `CORE_API_KEY`, same fail-closed pattern `llm_client.py` already uses for
   `ANTHROPIC_API_KEY`.
4. **Registry location** — new audit-only `data/citation_registry.json`,
   deliberately not `library.csl.json` (which stays exclusively the
   manuscript bibliography per CLAUDE.md's "only add_reference.py touches
   it" rule).

### New files
`citation_registry.py` (dedup/ledger), `fallback_sources.py` (escalating
resolution beyond Crossref), `grobid_client.py` + `tei_to_jats.py` (PDF via
GROBID), `pandoc_convert.py` (docx/tex/html/md via pandoc's JATS writer),
`format_router.py` (single dispatch point, wired into `check_claims.py`).
`.md` deliberately stays outside the router — it has years of hand-tuned
fixes (reference-list contamination, IQR-range false positives, running-
header splicing) that operate on raw text directly; routing it through a
generic XML round-trip would regress all of that for no benefit.

### `ref_resolver.py` rewrite
`resolve_reference()`'s cascade, in order: literal DOI in the ref text →
validate at Crossref (404 → `doi_invalid`, not `unresolved` — a broken DOI
in the source is itself a finding) → dedup lookup → book-chapter filter
(unchanged) → exact contiguous-title match (new, stricter than fuzzy
overlap) → fuzzy match (threshold raised 0.70→0.85) with a new ambiguity-gap
rule (best candidate must lead the runner-up by >0.10 overlap, else
unresolved rather than guessed) → fallback cascade → unresolved stub. Every
outcome, success or not, is written to `citation_registry.py`.

### Two real bugs caught while writing the tests for this
1. **`tei_to_jats.py`: `xml:id` read from the wrong namespace.** `xml:id`
   lives in the XML namespace (`http://www.w3.org/XML/1998/namespace`), not
   TEI's own namespace — the first version's lookup silently matched
   nothing, so every `<ref target="#bN">` citation marker in the body text
   failed to link to its `<biblStruct xml:id="bN">` reference entry (the
   `[n]` marker just vanished from the rendered body instead of erroring).
   Caught by a hand-built TEI fixture test, not by GROBID itself (unreachable
   in this environment). Fixed with an explicit `_xml_id()` helper using the
   correct namespace.
2. **`jats_parser.parse_jats()` couldn't parse pandoc's own JATS output.**
   PMC efetch responses wrap articles in `<pmc-articleset><article>...`, so
   the existing `root.find(".//article")` (descendants only) works — but
   pandoc's `-t jats` writer emits `<article>` as the document root itself,
   which `.//article` never matches (ElementTree's `.//` excludes the node
   it's called on). `parse_jats()` silently returned `None` for a perfectly
   valid document. Fixed with an explicit root-tag check. This is a shared
   file (also used by the PMC `--pmcid` path) — the fix is additive and
   doesn't change PMC's existing behavior at all.

### Verified end-to-end (dry-run, no LLM calls, real network calls)
- `.md` path: reran Karabulut 2020 before/after — identical counts, confirms
  zero regression to the existing calibrated pipeline.
- New `.html` path (via pandoc): a synthetic 3-reference test manuscript
  correctly left all 3 fake references unresolved/no-match (the confidence
  bar and fallback cascade did not fabricate matches for made-up citations,
  except one coincidental real-DOI match that's an artifact of using overly
  generic synthetic text like "Third paper" — not a pipeline bug, just a
  reminder these thresholds are tuned against *real* reference text).
- Dedup ledger confirmed: a second `check_claims.py` run against the same
  paper made zero ref-resolution network calls (~10s runtime, all spent on
  abstract fetches, not Crossref/fallback searches).
- `fallback_sources.core_search()` confirmed to skip cleanly with no
  `CORE_API_KEY` set, without blocking the rest of the cascade.

### Not yet tested
GROBID's actual PDF path (`grobid_client.convert()` → `tei_to_jats`) — no
live GROBID instance in this environment. Only the fallback branch
(pymupdf4llm) and the TEI-parsing logic (via a hand-built fixture) are
verified. First live run should also sanity-check GROBID's table/figure
tagging against a real PDF with real tables.

## 2026-07-01 — First 10/100 manual adjudication pass complete (standing in for the LLM API)

User asked me to personally do the adjudication (abstract-only Gate 1
equivalent) for the first 10 of the pre-registered 100-paper JAMA Network
Open sample, since `ANTHROPIC_API_KEY` still isn't set. After finishing
papers 1-2, flagged the scale honestly (10 papers ≈ 490 citation-checks,
~3x the earlier 3-paper calibration) via AskUserQuestion; user chose
**"Continue at full depth"** over a lighter-touch pass or pausing for the
API key — binding instruction for the rest of this phase: full scrutiny per
citation, not a sampled/faster pass.

Workflow per paper (same pattern as the 3-paper calibration, scaled up):
`check_claims.py --pmcid <id> --dry-run` → extract resolved (sentence,
ref_text, doi, abstract) tuples to scratchpad → read and classify every one
→ write a `PMC<id>.manual-preview.json` under
`results/preview/jama_network_open/` (`provenance: "manual_human_review"`).
Combined findings and full per-paper numbers:
`results/preview/jama_network_open/ten_paper_review_summary.md`.

**Totals across all 10 papers: 486 citation-instances checked — 404 (83.1%)
SUPPORTED, 56 (11.5%) PARTIALLY_SUPPORTED, 15 (3.1%) UNSUPPORTED, 11 (2.3%)
NOT_EVALUABLE.** Flagged rate among evaluable citations: 71/475 = 14.9%.
Not a population estimate — first 10 of a 100-paper frame, solo review,
abstract-only (no Gate 2 full-text follow-up performed in this pass).

### 2 more real pipeline bugs found and fixed (papers 3-4 of this batch)

- **Placeholder abstracts** (`"[Figure: see text]."`) — some
  Circulation/AHA-family journal records have only a graphical abstract
  indexed as the "abstract" text across all 3 metadata sources, and `if
  text:` treated it as real content. Fixed in `add_reference.py`:
  `_is_placeholder_abstract()` rejects `[...]`-only or <20-char text and
  falls through to the next source. Verified live against the actual DOI
  (`10.1161/HYPERTENSIONAHA.121.17570`) — correctly skipped PubMed's
  placeholder and found Crossref's real text. This *rescued* a flag from
  NOT_EVALUABLE to SUPPORTED (paper 3, PMC11718558).
- **F-statistic bracket notation misread as citation** —
  `"(F[4,163] = 9.93; P < .001)"` was parsed as citing references 4 and 163.
  Ref 163 correctly fell through as nonexistent, but ref 4 (a real,
  unrelated citation) was silently checked against the paper's own
  statistical result. Fixed via negative lookahead in `CITATION_RE`:
  `(?!\s*=)` — statistical notation is essentially always followed by `=`,
  a real citation marker never is. Verified the fix doesn't reject real
  citations like `[24]`. Paper 4 (PMC11742521) went from 70 to 69 real
  citation-check items after the fix.

### New issues found, logged but NOT fixed this session

- **Bracketed sample-size counts misread as citations** — e.g. `"0.2%
  [12]"` where `[12]` is a per-site admission count (n=12), not a citation
  to reference 12. No reliable distinguishing suffix like the F-statistic
  case (no trailing `=`); a real fix needs a smarter heuristic (e.g.
  checking whether the token immediately before the bracket is a
  percentage). Found in paper 6 (PMC11742536).
- **Corrupted/garbled Crossref abstracts** — some publisher deposits
  contain heavily duplicated, JATS-markup-mangled text (paper 6's ASCCP
  guidelines reference, cited 3 times). Confirmed via direct PubMed/
  OpenAlex re-fetch that no clean fallback exists — a source data-quality
  problem, not a pipeline bug. Marked NOT_EVALUABLE rather than guessed.
- **Author-byline-only / boilerplate "abstract" fields** — Crossref
  sometimes returns just the author list (paper 7), website cookie-notice
  text (paper 8), or a bare table of contents for a pre-1980s economics
  article (paper 8) instead of a real abstract. Same treatment: NOT_EVALUABLE.
- **Complete abstract unavailability across all 3 sources** — paper 9's
  primary MR-exposure GWAS (Nagel et al., cited 5 times) has no abstract
  anywhere, confirmed via live re-fetch of all three sources. Missing
  upstream metadata, not a bug.
- **High unresolved-reference rate for non-biomedical DOIs** — paper 8 (14
  of 37 refs unresolved) mixes economics/marketing citations with clinical
  ones; the 3-source backfill seems less reliable for older/non-biomedical
  DOIs. Worth checking across the full n=100 run if the pattern recurs.
- **Internally inconsistent study-count citations for one reused
  reference** — paper 9 cites the same source (Chida 2008) with 3
  different study counts across the manuscript (16, 142, vs. the
  abstract's actual 165). Logged for a full-text check later; could be
  legitimate subgroup citations or transcription errors by the original
  authors.

### Strongest miscitation candidate from this batch (not yet Gate-2-verified)

Paper 10 (PMC11780478), a semaglutide-vs-tirzepatide weight-loss trial
(Rodriguez et al.) cited for a standardized-mean-difference statistical-
methods claim — the cited abstract has zero connection to SMD/propensity-
score balance diagnostics. Good first candidate for Gate 2 once the API key
is available.

## 2026-07-01 — Phase 3 prep: JAMA Network Open n=100 sample frozen, JATS retrieval built

Follow-up to the 3-paper calibration. User asked to prepare a 100-paper run
on "JAMA open papers." Two decisions needed clarifying first (asked via
AskUserQuestion, both went with the recommended option):

1. **JAMA vs. JAMA Network Open.** Went with JAMA Network Open — fully OA,
   ~5000+ articles/yr, clean sampling frame. Flagship JAMA is mostly
   paywalled with only a partial OA subset, which would have made "n=100"
   a much messier inclusion problem. Left the door open to a flagship-JAMA
   follow-up sample later (noted as deferred in the pre-registration doc).
2. **PDF-to-Markdown vs. PMC JATS XML for full text.** Went with JATS XML.

Before touching any data, flagged that this project's own
`docs/adjudication-criteria.md` (written same day, during the 3-paper
calibration) explicitly left "primary outcome" and "second reviewer" as
"not yet decided, update before Phase 3 begins" — and a 100-paper run is
exactly Phase 3. Asked and locked both before pulling any sample:
- **Primary outcome:** confirmed-miscitation rate *among flagged citations*
  (not an overall population miscitation rate) — matches the original
  handoff's non-negotiable requirement and the 3-paper calibration's own
  finding that many PARTIALLY_SUPPORTED flags were synthesis citations or
  abstract-only limitations, not real miscitations.
- **Second reviewer:** solo review for this run. Logged explicitly as a
  limitation to carry into the eventual manuscript, not silently absorbed.

### Why JATS XML instead of continuing with PDF-to-Markdown

The 3-paper calibration's 8 bugs were almost all consequences of PDF
conversion destroying document structure (reference-list boundaries,
section headings, running headers, superscripts) and the pipeline having
to reverse-engineer that structure with regexes. PMC's JATS XML has real
structure — a `<ref-list>` with unambiguous entries, `<xref
ref-type="bibr" rid="...">` tags that ARE the citation markers (no bracket-
regex guessing needed), and reference entries that frequently carry the
cited paper's DOI directly (`<pub-id pub-id-type="doi">`), letting
`ref_resolver.py`'s Crossref search be skipped for those references
entirely — a resolver that never has to guess can't introduce a resolver
bug.

Built `jats_parser.py`: `fetch_and_parse(pmcid)` -> `{title, doi, pmid,
pmcid, body, refs}`. `body` is paragraphs joined by blank lines with `[n]`
citation markers already inserted (converted from `<xref>` tags using our
own reference-list numbering, not the visible superscript text, which can
be inconsistent). Table/figure/formula subtrees are skipped entirely while
walking the body — directly preventing the "Table 2 dumped into a
sentence" bug found in Kang 2022's PDF conversion.

Wired into `check_claims.py` via a new `--pmcid` argument (mutually
exclusive with the existing manuscript-path argument). Added a
`known_dois: Dict[int, str]` short-circuit in the main loop: when JATS
already gave a DOI for a reference, `ref_resolver.resolve_reference()` is
skipped for that reference and the DOI is used directly (tagged
`"source": "jats_xml_direct"` in the resolution record for traceability).

**Smoke-tested on 3 real sampled JAMA Network Open articles** (PMC11707628,
PMC11707635, PMC11718558): reference-list parse rate 100%/100%/100%
(38/38, 47/47, 40/40) — vs. 59-95% on the PDF-converted 3-paper calibration
set. 93-100% of references per article had a DOI given directly in the
XML. The two flags produced (one `no_abstract_found`, one
`unresolved_reference`) were both legitimate — a 1975 single-page article
genuinely absent from every metadata source, and a ClinicalTrials.gov
registration entry (not a journal article, correctly unresolvable) — not
pipeline bugs.

### Sample pulled, and a real sampling-bias bug caught before freezing it

Built `sample_jama_network_open.py`: PMC search for `"JAMA Netw
Open"[Journal]` within a publication-date window, filtered on the JATS
`<subj-group subj-group-type="heading"><subject>` text equal to "Original
Investigation" — **not** the `article-type` attribute, which is
`"research-article"` for both Original Investigations and Research Letters
in this journal's JATS output and can't distinguish them. Also required
body >3000 chars and >=10 references to exclude stub records that slipped
past the heading filter.

Used a fixed calendar-year window (2025) rather than "most recent" — a
live check found only ~27% of the newest articles had PMC full text linked
yet (deposit lag), vs. consistent availability a year back.

**First run had a real, self-inflicted sampling-methodology bug**: to avoid
fetching and filtering all ~2169 candidate records, the script stopped
early once it found 4x the requested sample size. But `esearch` doesn't
return records in random order (relevance/uid), so stopping early while
walking that order meant every record in the unfetched remainder had zero
probability of selection — not a valid random sample of the population,
even though `random.sample()` was correctly called on whatever had been
fetched. Caught this before treating the first output as final. Fixed by
shuffling the full candidate-ID list (same seed) *before* any batch
fetching begins, which makes any prefix of the shuffled list itself a
valid uniform random sample — so early-stopping after the shuffle is fine.
Re-ran and froze the corrected sample (429 qualifying candidates found
before the 4x-margin early stop, 100 sampled, seed 42).

Wrote the formal pre-registration doc:
`data/preregistration/2026-07-01_jama-network-open-100.md`, referencing the
frozen sample list `jama_network_open_sample_2025_100.json`. Both files are
dated and meant to stay authoritative even if `sample_jama_network_open.py`
gets bug-fixed later — a fixed script producing a different sample doesn't
retroactively change what was pre-registered.

### What's left before the n=100 run can actually execute

Only `ANTHROPIC_API_KEY`. Nothing else in the pipeline, sample, or
pre-registration is a known blocker as of this entry.

## 2026-07-01 — FLAG_TYPE taxonomy, 2-gate cascade, and 3-paper manual calibration

Follow-up to the same-day check_claims.py build. Two things drove this
session: (1) user asked "which ones are falsely cited," which surfaced that
the existing flag report only had dry-run structural data, no real
verdicts — prompted the first manual interactive review (me reading claim/
abstract pairs directly, standing in for the uncalled LLM); (2) user then
asked for a finer-grained flag taxonomy mirroring how a human reviewer
actually works: unrelated topic vs. abstract contradicts numbers vs. not
mentioned in abstract, with a full-text pull as a second gate when unclear.

### Taxonomy + cascade

Extended `SYSTEM_PROMPT` with a `FLAG_TYPE` field (TOPIC_MISMATCH /
NUMBER_CONTRADICTION / NOT_MENTIONED / NONE), required whenever VERDICT
isn't SUPPORTED. Built `fulltext_fetch.py`: Unpaywall OA lookup -> download
-> `pdf_to_md.pdf_to_markdown()` -> cached by DOI. `check_claims.py` now
runs gate 2 automatically whenever gate 1 (abstract) comes back non-
SUPPORTED, with a second LLM call scoped to the full text
(`SYSTEM_PROMPT_FULLTEXT`). Every check entry now carries both
`abstract_verdict` and (if gate 2 ran) `fulltext_verdict`, plus a
`final_verdict`/`final_gate` pair recording which gate's judgment counts.

Also added a "pipeline never writes to a 'manual'-named path" guard in
`check_claims.py`'s output logic, and a `provenance` field
(`"automated_pipeline"`) on every flags/*.json file — hard separation from
the manual-preview files, per user's earlier provenance concern.

### 3-paper manual calibration (Jia 2023 already done; added Kang 2022, Karabulut 2020)

Picked the two smallest remaining TEMP/ files rather than cherry-picking
easy ones. Result: full findings in
`audit/results/preview/three_paper_review_summary.md` (condensed) and the
three `*.manual-preview.json` files (full detail, one row per checked
citation, `"provenance": "manual_human_review"`, `"pipeline_version": null`).

**8 real pipeline bugs found and fixed**, all triggered by actual failures
on actual papers:
1. Ref resolver only checked Crossref's #1 candidate (already fixed same
   day, listed here for completeness — see prior entry).
2. Reference-list boundary contamination — last ref in a list swallows
   trailing correspondence/abbreviations/Supporting-Info text (Jia ref 28,
   2020 chars captured for a ~150-char reference). Two-tier truncate-vs-
   delete fix; had to redo once after v1 wrongly truncated a *mid-reference*
   splice (Jia ref 21) and lost real journal/year/page data.
3. Author-affiliation superscripts read as citation markers (already fixed
   same day).
4. Running headers/footers spliced mid-sentence (already fixed same day).
5. **Bold markdown headings not matched** — `"## **REFERENCES**"` didn't
   match `^#+\s*references\s*$` at all. Kang 2022 parsed **zero**
   references before the fix; every one of its 75 citations fell through
   as "reference not in list." Fixed both `ref_resolver.py` and
   `check_claims.py`'s heading regexes to tolerate `*`/`_` wrapping.
6. **IQR ranges misread as citation ranges** — `"15 [13-41] vs. 85
   [30.50-195] days"` is a median/interquartile-range statistic; the range-
   expansion logic in `expand_marker()` treated `[13-41]` as citing
   references 13 through 41, generating 19 fake missing-reference flags for
   Kang 2022. Fixed: reject any "[a-b]" range wider than 15 (real citation
   ranges in clinical papers are essentially never that wide).
7. **Book-chapter citations falsely resolved** — Karabulut's ref 1 ("Walsh
   PC... In: Walsh PC, Retik AB... Campbell's Urology 7th Edition 1998")
   resolved "successfully" to a *different* same-author, same-year journal
   article ("Anatomic Radical Prostatectomy," J Urol 1998) whose title is
   similar enough to pass every confidence check. Root cause: the
   confidence bar checks textual similarity, not venue type, and can't
   distinguish "close enough" from "wrong paper by the same prolific
   author." Fixed: reject `"In: ... (Eds)"` citations outright rather than
   attempting resolution — verified by direct Crossref lookup that the
   resolved DOI's actual title was the wrong paper before writing the fix.
8. **Unit superscripts read as citations** (`"kg/m[2]"` -> read as citing
   ref 2) — same failure class as bug 3, different trigger. Found but
   **not yet fixed** — logged as an open item in STATUS.md rather than
   patched immediately, since it's rare and this session was already deep.

### Two verified findings (gate 2 actually run, not just designed)

- **Jia ref 13 (Bellangino) — CONFIRMED miscitation.** Full text (OA)
  fetched and read; discusses high-risk/large-prostate only as positive-
  surgical-margin predictors, never continence. Topic mismatch survives
  full-text review.
- **Jia ref 5 (Sridhar) — RESCUED, false positive.** Abstract doesn't say
  "only modifiable factor"; full text does, verbatim
  ("Surgical technique is the only modifiable factor among these").
  Concrete proof the abstract-only limitation is real, not just a
  theoretical concern — worth having built gate 2 for this alone.
- **Karabulut ref 13 (Steiner) — CONFIRMED miscitation, highest confidence
  finding across all 3 papers.** Cited for a clinical RCT (n=237 vs 97,
  3-month continence data); actual paper is a cadaver anatomy dissection
  study with zero patients. Verified the reference-list entry itself was
  parsed correctly (not a pipeline bug) by checking the raw source text —
  this is the *original authors'* citation error. The n=237 figure closely
  matches an unrelated paper (Patel 2009, appears in Kang 2022's reference
  list) — plausible the original authors intended a different citation
  number and this is a genuine reference-numbering slip in their manuscript.

### Numbers (do not overinterpret — 3-paper convenience sample)

71 citations resolved+checked across all three papers combined. 12 (17%)
UNSUPPORTED. Explicitly flagged in STATUS.md and the summary doc that this
is not a population estimate — three hand-picked papers from one folder is
nowhere near Phase 3's eventual sample frame.

## 2026-07-01 — check_claims.py built and structurally tested end-to-end

Before building, asked four blocking design questions, all answered
Recommended:
- LLM backend: Anthropic Claude (swappable via `llm_client.py`, one env var
  `LLM_BACKEND` to change later — no provider calls hardcoded elsewhere)
- Reference resolution: auto-resolve numbered ref-list entries to DOIs via
  Crossref bibliographic search, with a confidence bar; low-confidence top
  hits are flagged unresolved rather than accepted (never guess)
- Multi-citation sentences (e.g. "...[2,3]"): check each citation
  independently — a sentence citing 3 refs produces 3 separate flag-report
  entries, keeping the false-positive-rate denominator at "citations"
- Prompt design: 3-way classification (SUPPORTED / PARTIALLY_SUPPORTED /
  UNSUPPORTED) with a mandatory exact quote for anything not UNSUPPORTED —
  maps directly onto the pre-registration categories from the handoff

Built three new files in `audit/`:
- `llm_client.py` — `complete(system, user)` -> {text, model, backend}.
  Anthropic only for now, REST call via `requests` (no new SDK dependency).
  Requires `ANTHROPIC_API_KEY` env var; not set in this environment, so the
  live LLM call itself is untested — everything upstream of it is.
- `ref_resolver.py` — `parse_reference_list()` extracts {n: raw ref text}
  from a "## References" section (supports "- N ", "N.", "[N]" numbering
  styles, picks whichever yields the most matches). `resolve_reference()`
  queries Crossref bibliographic search (5 candidates) and accepts a
  candidate only if year matches AND first-author family name is a
  substring of the raw ref text AND >=70% of the candidate title's
  significant words appear in the raw ref text. Caches search results by
  query hash under `audit/cache/ref_resolution/`.
- `check_claims.py` — the main pipeline. Extracts sentences with [n]/[n,m]
  citation markers from the manuscript body (trims the title/author/
  affiliation block and structured-abstract summary by starting from the
  first Introduction/Background heading — see bug note below), resolves
  each cited reference to a DOI, fetches its abstract (library.csl.json
  first, else live Crossref+PubMed+OpenAlex merge — same code path as
  add_reference.py, but never writes to library.csl.json), and runs the
  LLM support check per (sentence, citation) pair. Every LLM call is cached
  by sha256(model+system+user) under `audit/logs/llm_calls/`. Writes a full
  flag report to `audit/results/flags/<paper>.json` (counts + flagged
  subset + every check, so the false-positive-rate denominator is always
  reconstructable) and a run summary to `audit/logs/sessions/`.

### Two bugs caught by testing against the real Jia 2023 paper

1. **Ref resolver only checked Crossref's #1 hit.** For several refs (e.g.
   #1, #16), Crossref's top-ranked result was a "Re: <same title>"
   commentary/reply article — different DOI, different authors, sometimes
   different year — not the original paper. The confidence bar correctly
   rejected it, but since only the top hit was checked, the reference was
   marked unresolved even when a later candidate might have been right.
   Fixed: iterate all returned candidates, accept the first one that clears
   the bar. (Tested with rows bumped 3->5 afterward too — for refs #1 and
   #16 specifically, *no* candidate in the top 5 was the real paper; Eur
   Urol's guideline/systematic-review articles apparently attract enough
   "Re:"/"Reply to" commentary that the original gets crowded out of
   Crossref's bibliographic-search ranking. Correctly left unresolved.)

2. **Claim extraction picked up author-affiliation superscripts as citation
   markers.** The PDF-to-Markdown conversion leaves the title/author block
   as plain prose-looking text: "Zepeng Jia[1], Zeyu Chen[2], ...". Since
   `[1]`, `[2]` are indistinguishable in isolation from real citation
   markers, the extractor treated author affiliations as citations 1-3,
   attached to a nonsense "sentence" (the whole affiliation block). Fixed:
   `split_body_and_refs()` now starts extraction from the first
   Introduction/Background heading, skipping the title/author block and
   the structured-abstract summary (Objective/Methods/Results/Conclusion),
   neither of which normally carries real citations anyway. Documented as
   a known limitation — journals without that heading, or with a
   differently-named one, fall back to the untrimmed body and re-expose
   this failure mode.

### Validation run (dry-run, no LLM calls, real data)

Jia 2023.md: 28 references parsed, 37 claim sentences found, 57 total
(sentence, citation) checks. **52 resolved to a DOI with high confidence,
5 correctly left unresolved** — inspected all 5 manually:
- Refs #1, #16: genuine Crossref search limitation (see bug note above)
- Refs #24, #28: Crossref's best candidate was a completely unrelated paper
  (one was a pediatric cardiac-surgery video unrelated to urology/prostate
  cancer) — `title_word_overlap` of 0.11-0.31, correctly rejected. This is
  exactly the failure mode the confidence bar exists to prevent; a naive
  "take the top hit" resolver would have silently attached the wrong
  abstract to a real clinical claim.

This validates the resolver's core design choice (flag, don't guess) — the
5 unresolved cases are real "needs a human to find the DOI" cases, not
resolver bugs.

### Not yet tested

The LLM call itself (`llm_client.complete()` -> `check_claim()` ->
parsing VERDICT/QUOTE/GAP) has no live test — no `ANTHROPIC_API_KEY` in
this environment. Structurally verified (prompt construction, response
parsing regex, cache read/write path) but not run against a real model
response. First live run should sanity-check the parser against actual
Claude output before trusting flag reports.

## 2026-07-01 — PDF-to-Markdown conversion vendored for manuscript ingestion

User pointed to `C:\Users\Hung\Desktop\Research\Toolbox\convert_pdf_to_md.py`
as the tool for turning published-paper PDFs into Markdown (needed for Phase
2's manuscript parsing). That script is a thin wrapper around a shared
`doctools` package (also handles docx/pptx/xlsx/OCR/merging — general
document tooling, not audit-specific).

Asked user: reference the shared `doctools` package via sys.path, or vendor
a minimal standalone copy. Chose **vendor standalone** — reasons: (1)
citation-pipeline is going to GitHub per the handoff, and a hard dependency
on an absolute local Toolbox path breaks on any other machine or fresh
clone; (2) doctools' PDF-to-MD piece is a ~10-line pymupdf4llm call plus a
cleanup regex — not worth dragging in the OCR/LibreOffice/spreadsheet
machinery this project will never use.

Created `audit/pdf_to_md.py` — self-contained, CLI (`python pdf_to_md.py
paper.pdf [--output out.md | --out-dir dir/] [--overwrite]`), same
extraction (pymupdf4llm, margins=0, no images) and header/footer/page-number
cleanup logic as the original. Smoke-tested against a real PDF, output
verified non-empty and sane. No dependency on Toolbox/doctools.

If `doctools` gets a bug fix later (e.g. better multi-column handling),
that fix won't automatically propagate here — accepted tradeoff for
portability. Revisit if this becomes a real maintenance burden.

## 2026-07-01 — Abstract retrieval merged into core pipeline, not a separate script

User relocated the project to `C:\Users\Hung\Desktop\citation-pipeline` and
asked to extend citation retrieval itself (not a standalone audit script) to
pull title + abstract from all three sources — Crossref, PubMed, OpenAlex —
standardized, deduped, and backfilled between sources.

This supersedes the original Phase 1 plan (`fetch_abstracts.py` +
`data/library_abstracts.json`). Implemented directly in `add_reference.py`:

- `fetch_pubmed_record(pmid)` — efetch XML, parsed for title/abstract
  (respecting structured Background/Methods/Results/Conclusions labels)/
  journal/year/authors. Cached to `raw_pubmed/<pmid>.xml`.
- `fetch_openalex(doi)` — works record by DOI, abstract reconstructed from
  the inverted index. Cached to `raw_openalex/<doi>.json`.
- `clean_crossref_abstract()` — strips JATS tags from Crossref's abstract
  field when present.
- `merge_metadata()` — first-non-empty-wins backfill per field, not
  blended: title/authors/journal/year prefer Crossref → PubMed → OpenAlex;
  abstract prefers PubMed → Crossref → OpenAlex (PubMed abstracts are
  cleanest and most often structured).
- `abstract` and `OPENALEX-ID` are now real fields on CSL JSON records in
  `library.csl.json` (OPENALEX-ID follows the same non-standard-extension
  convention already used for PMID).
- `registry.csv` gained `has_abstract`/`abstract_source`/`openalex_id`
  columns. `append_registry()` now migrates the header in place if it's
  stale, so old rows don't end up column-misaligned with new ones.

Tested against the DOI already in the library (10.1111/bju.15956) via direct
function calls (no library write), and end-to-end via `main()` against a
second DOI (10.1056/NEJMoa1011967) in an isolated `CITATION_DIR` — both
resolved all three sources, abstract came from PubMed in both cases.

Did not touch `format_jama.py` or `validate_citations.py`. Did not backfill
the existing library entry (duplicate-DOI check in `add_reference.py` skips
already-added DOIs) — flagged as an open decision in STATUS.md.

`audit/cache/abstracts/` and `audit/data/library_abstracts.json` from the
original scaffold are now stale/unused for this purpose — left in place, not
deleted, in case a project-specific override need comes up later.

## 2026-07-01 — Project scaffolding created

Created `audit/` as a subproject inside the existing citation-pipeline toolbox,
kept separate from `add_reference.py` / `format_jama.py` / `validate_citations.py`
per instruction not to touch the existing three scripts.

Reviewed context handoff. Core question: of citations in recently published
clinical papers, what fraction have at least one citation where the abstract
doesn't support the claim as made in the citing sentence. Tool is secondary —
finding is the paper.

Directory backbone laid down (see MANIFEST.md for the map). No retrieval or
claim-checking code written yet — waiting on sign-off for:
- Phase 1 (abstract retrieval): PubMed efetch primary, CrossRef abstract field
  fallback, OpenAlex inverted-index reconstruction last resort.
- Phase 2 (`check_claims.py`): flags only, must quote supporting text or else
  flags as unsupported, swappable LLM backend, every call logged + cached by hash.

## Open questions (unresolved — see handoff doc)

- PubMed API key: get one now, or start without? (3 req/sec unauthenticated)
- PDF parsing robustness needed before Phase 3 — guess is "robust enough for
  one journal's typical format," not universal. Confirm which journal first.
- LLM prompt design for support-checking: need 2-3 variants proposed, user
  picks.
- Abstract-only vs full-text where legitimately open-access — flag per case,
  don't decide unilaterally.
- Phase 3 sample frame not yet chosen (single top-tier journal vs mid-tier vs
  stratified vs AI-disclosed papers only). Do not run at scale until this and
  the pre-registration doc are settled.

## Conventions for this log

- Append, don't rewrite history. If a decision changes, add a new entry noting
  the reversal and why — don't edit the old entry.
- Anonymize only in the eventual paper. Keep full identifying detail here.
