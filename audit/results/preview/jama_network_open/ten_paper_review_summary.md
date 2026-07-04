# JAMA Network Open n=100 sample — first-10 manual adjudication summary

Manual/interactive review (abstract-only, Gate 1 equivalent), done before
`ANTHROPIC_API_KEY` was available. All 10 papers are drawn in order from the
frozen, pre-registered, seed-42 random sample of 100 JAMA Network Open
"Original Investigation" articles published in 2025
(`data/preregistration/jama_network_open_sample_2025_100.json`). Not a
population estimate — see caveats at the end.

## Papers reviewed

| # | PMCID | Title | Items | SUPPORTED | PARTIAL | UNSUPPORTED | NOT_EVAL |
|---|-------|-------|------:|----------:|--------:|-------------:|---------:|
| 1 | PMC11707628 | Surgeon Recommendation and Outcomes of Decompression With vs Without Fusion in Patients With Degenerative Spondylolisthesis | 53 | 46 | 4 | 3 | 0 |
| 2 | PMC11707635 | Mental Health Care Utilization and Prescription Rates Among Children, Adolescents, and Young Adults in France | 44 | 30 | 10 | 4 | 0 |
| 3 | PMC11718558 | Trends in Ethnic Disparities in Stroke Care and Long-Term Outcomes | 53 | 45 | 6 | 2 | 0 |
| 4 | PMC11742521 | Neural Variability and Cognitive Control in Individuals With Opioid Use Disorder | 69 | 64 | 5 | 0 | 0 |
| 5 | PMC11742528 | Anthropometric Trajectories in Children Prior to Development of Inflammatory Bowel Disease | 45 | 36 | 5 | 4 | 0 |
| 6 | PMC11742536 | Delivering Guideline-Concordant Care for Patients With High-Risk HPV and Normal Cytologic Findings | 46 | 27 | 15 | 1 | 3 |
| 7 | PMC11751744 | Travel Time as an Indicator of Poor Access to Care in Surgical Emergencies | 58 | 56 | 1 | 0 | 1 |
| 8 | PMC11774089 | Pharmacy Subscription Program and Medication Refills, Days' Supply, and Out-of-Pocket Costs | 25 | 18 | 5 | 0 | 2 |
| 9 | PMC11780474 | Sensitivity to Environmental Stress and Adversity and Lung Cancer | 31 | 22 | 4 | 0 | 5 |
| 10 | PMC11780478 | Health Care Resource Use and Costs After Hospitalization With Multiple Organ Dysfunction in Children | 62 | 60 | 1 | 1 | 0 |
| **Total** | | | **486** | **404** | **56** | **15** | **11** |

Rates (of 486 total citation-instances checked): 83.1% SUPPORTED, 11.5%
PARTIALLY_SUPPORTED, 3.1% UNSUPPORTED, 2.3% NOT_EVALUABLE (data-quality
artifacts, not support judgments).

Of the 475 evaluable citation-instances (excluding NOT_EVALUABLE), flagged
(non-SUPPORTED) rate is 71/475 = **14.9%**.

## Pipeline bugs found and fixed this batch (papers 5-10; papers 1-4 covered in NOTES.md)

1. **Placeholder abstracts** (`"[Figure: see text]."`) treated as real content
   — fixed in `add_reference.py`'s `merge_metadata()` with
   `_is_placeholder_abstract()`, falls through to next source. (Paper 3.)
2. **F-statistic bracket notation misread as citation** (`F[4,163] = 9.93`)
   — fixed via negative lookahead in `CITATION_RE` rejecting `[n,m]` followed
   by `=`. (Paper 4.)

## New issues found this batch, NOT fixed (logged as open items)

3. **Bracketed sample-size counts misread as citations** — e.g. `"0.2%
   [12]"` where `[12]` is a per-site admission count, not a citation to
   reference 12. Unlike the F-statistic bug, there's no reliable
   distinguishing suffix (no trailing `=`). Affects paper 6, index 25.
   Needs a smarter heuristic (e.g. checking whether the preceding token is a
   percentage/count) before it can be fixed without new false negatives.
4. **Corrupted/garbled Crossref abstracts** — some publisher deposits contain
   heavily duplicated, JATS-markup-mangled text (e.g. paper 6's ASCCP
   guidelines reference, cited 3 times, all NOT_EVALUABLE). Confirmed via
   direct PubMed/OpenAlex re-fetch that no clean fallback abstract exists —
   this is a source data-quality problem, not a pipeline bug.
5. **Author-byline-only "abstract" fields** — Crossref occasionally returns
   just the author list as the "abstract" (paper 7, Tominaga et al.) or
   website boilerplate/cookie-notice text (paper 8, a JAMA Viewpoint) or a
   bare table of contents for a pre-abstract-era 1976 economics article
   (paper 8, Adams & Yellen). All marked NOT_EVALUABLE.
6. **Complete abstract unavailability across all 3 sources** — paper 9's
   primary exposure GWAS (Nagel et al., cited 5 times) has no abstract in
   Crossref, PubMed, or OpenAlex, confirmed via live re-fetch. Not a bug —
   genuinely missing metadata upstream.
7. **High unresolved-reference rate for non-biomedical DOIs** — paper 8 (14
   of 37 references unresolved) cites economics/marketing literature
   alongside clinical literature; the Crossref/PubMed/OpenAlex backfill
   appears less reliable for older or non-biomedical DOIs. Worth a
   dedicated look if it recurs across the full n=100 run.
8. **Internally inconsistent study-count citations for a reused reference**
   — paper 9 cites the same source (Chida 2008 meta-analysis) with three
   different study counts across the manuscript (16, 142, and the
   abstract's actual 165). Could be legitimate subgroup citations or could
   be citation/number transcription errors in the source manuscript — flagged
   for a closer look at the full text if the pattern recurs.

## Notable CONFIRMED-style findings from this batch (abstract-level, not yet full-text verified)

- **Paper 6, index 25** (Tosteson/PROSPR miscited via bracket-sample-size
  bug) — a pipeline artifact, not a real miscitation by the paper's authors.
- **Paper 10, index 49** (Rodriguez semaglutide-vs-tirzepatide trial cited
  for a standardized-mean-difference statistical-methods claim) — a genuine
  topic mismatch; the cited paper's abstract has zero connection to the
  claim it supports. This is the strongest single miscitation candidate
  found in papers 5-10 and would be a good first target for Gate 2
  (full-text) verification once the API key is available.
- Several PARTIALLY_SUPPORTED flags across papers 6, 8, and 9 are numeric
  mismatches where the citing sentence states a specific figure (a
  percentage, study count, or statistic) that doesn't appear in the cited
  abstract — consistent with the project's expectation that many flags will
  be "not verifiable from abstract" rather than outright contradictions.

## Caveats (same as prior calibration rounds)

- **Abstract-only (Gate 1 equivalent).** No full-text (Gate 2) follow-up was
  performed in this manual pass, so PARTIALLY_SUPPORTED/UNSUPPORTED verdicts
  here are "not supported by the abstract," not "confirmed miscitations."
  Per the pre-registered primary outcome, only a subset of these would
  survive full-text review as CONFIRMED (see the 3-paper calibration's
  finding that 2 of 3 flags examined with Gate 2 were RESCUED, not
  CONFIRMED).
- **Solo review**, no second reviewer, per the pre-registration doc.
- **First 10 of 100** — not a population estimate. Rates above describe this
  convenience subsample only.
- All output written under `provenance: "manual_human_review"`, kept
  strictly separate from automated-pipeline output per project convention.
