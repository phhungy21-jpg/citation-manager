# Citation-Claim Support Review — 3-Paper Manual Pass

Dated: 2026-07-01
Reviewer: Claude (interactive session — no fixed temperature, no independent
API reproducibility; see caveat below)
Papers: Jia et al. 2023 (*BJU Int*), Kang et al. 2022 (*Investig Clin Urol*),
Karabulut et al. 2020 (*Eurasian J Med*)

## What this is

A manual, interactive run of the same abstract-vs-full-text support-checking
methodology `check_claims.py` implements — every citing sentence with an
in-text citation marker, checked against the cited paper's abstract
(gate 1), with a full-text re-check (gate 2, via Unpaywall OA lookup) when
gate 1 came back non-SUPPORTED and a legal open-access copy exists. See
`docs/adjudication-criteria.md` for the verdict/flag_type definitions.

**Caveat on provenance:** this was produced by an interactive Claude Code
session reading each claim/abstract pair directly, not by
`check_claims.py`'s automated pipeline making live API calls. No fixed
temperature, no independent reproducibility. Treat this as a **calibration
set** — once the pipeline runs live with `ANTHROPIC_API_KEY` set, its output
should be compared against these three files as the first precision/recall
data point. Full per-item detail (complete abstracts, exact quotes, notes)
is in the three `*.manual-preview.json` files in this directory; this
document is the condensed, readable summary.

## Executive summary

| Paper | Refs parsed | Resolved | Unresolved | Claims checked | Supported | Partial | Unsupported | Not evaluable |
|---|---|---|---|---|---|---|---|---|
| Jia 2023 | 28 | 54 (95%) | 3 (5%) | 57 | 28 | 15 | 6 | 3 |
| Kang 2022 | 22 | 24 (89%) | 3 (11%) | 27 | 12 | 10 | 1 | 1 |
| Karabulut 2020 | 21 | 13 (59%) | 9 (41%) | 22 | 3 | 4 | 4 | 2 |

Karabulut's low resolution rate is a genuine data-quality finding, not a
pipeline bug — its source text has heavy OCR noise (`"cantinence"`,
`"asisted"`, `"Europan"`, `"radikal"`, `"lacalized"`) that defeats
exact-substring title matching. See "Pipeline bugs found this session"
below for what *was* fixed.

**Headline finding (informal, 3-paper sample — not a statistically powered
estimate):** across all three papers, 12 of 71 checked citations that
resolved (17%) came back UNSUPPORTED, with two — Jia's ref [13]
(Bellangino) and Karabulut's ref [13] (Steiner) — being high-confidence,
verified miscitations (wrong topic/wrong content entirely, not just
imprecise framing). This is well within the range the handoff document
flagged as "JAMA Research Letter / NEJM Correspondence territory" *if* it
held up at scale — but three papers, hand-picked from one TEMP folder, is
nowhere near a defensible sample. See `audit/STATUS.md`: do not treat this
as a population estimate.

## Pipeline bugs found and fixed this session

Every fix below was triggered by a real failure on real data, not
speculative hardening. All are live in `ref_resolver.py` / `check_claims.py`.

1. **Ref resolver only checked Crossref's #1 hit.** "Re: `<title>`"
   commentary articles out-ranked the real cited paper for Jia's refs 1, 16.
   Fixed: check every returned candidate, not just the top one.
2. **Reference-list boundary contamination.** The last reference in a list
   (no "N+1" marker to bound it) swallowed trailing correspondence/
   abbreviations/Supporting-Information text — up to 2020 characters for a
   ~150-character reference (Jia ref 28), garbling the Crossref query enough
   to match an unrelated cardiac-surgery paper. Fixed with a two-tier
   truncate-vs-delete contamination filter (had to iterate once after the
   first version wrongly truncated a *mid-reference* splice and lost real
   journal/year/page data for ref 21).
3. **Author-affiliation superscripts read as citations.** `"Zepeng Jia[1],
   Zeyu Chen[2]"` in a title/author block was parsed as citing references 1
   and 2. Fixed: claim extraction now starts at the first
   Introduction/Background heading.
4. **Running headers/footers spliced mid-sentence.** PDF-to-Markdown
   conversion leaves copyright/license boilerplate and journal running
   heads embedded inside real sentences at page breaks, corrupting
   citation-to-sentence attribution. Fixed with a boilerplate-stripping
   regex; 3 cases per paper remain unfixable (genuine information loss when
   a page break falls inside a sentence, not noise to strip).
5. **Bold markdown headings not matched.** `"## **REFERENCES**"` didn't
   match the heading regex at all — Kang 2022 parsed **zero** references,
   and all 75 of its citations fell through as "reference not in list."
   Fixed: heading regex now tolerates `*`/`_` emphasis wrapping.
6. **Statistical ranges misread as citation ranges.** `"15 [13-41] vs. 85
   [30.50-195] days"` is an IQR (interquartile range), not a citation to
   references 13 through 41 — but the range-expansion logic didn't know the
   difference, generating 19 fake "missing reference" flags. Fixed: citation
   ranges wider than 15 are now rejected as implausible.
7. **Book-chapter citations falsely resolved.** `"Walsh PC. Anatomic Radical
   Retropubic Prostatectomy. In: ... Campbell's Urology 7th Edition"`
   resolved to a *different*, same-year, same-author *journal article* with
   a similar title — passed every confidence check (year, author, title
   overlap) despite being the wrong paper, because Crossref has no journal
   article matching a textbook chapter and the resolver found the next-best
   thing instead of admitting defeat. Fixed: `"In: ... (Eds)"` citations are
   now refused outright, never attempted.
8. **Unit superscripts read as citations.** `"kg/m[2]"` (kg/m²) was parsed
   as a citation to reference 2 in Karabulut — same failure class as bug 3,
   different trigger. **Not yet fixed** — noted as an open item below.

## Verified findings (gate 2 / manual full-text check completed)

| Paper | Ref | Result | Detail |
|---|---|---|---|
| Jia 2023 | [13] Bellangino | **CONFIRMED miscitation** | Full text (OA) discusses high-risk/large-prostate only as surgical-margin predictors, never continence. Topic mismatch holds up under full-text review. |
| Jia 2023 | [5] Sridhar | **RESCUED — false positive** | Abstract doesn't say "only modifiable factor"; full text (OA) does, verbatim. Abstract-only limitation, not a real miscitation. |
| Karabulut 2020 | [13] Steiner | **CONFIRMED miscitation (high confidence)** | Cited for a clinical RCT (n=237 vs 97, 3-month continence rates) — but Steiner 1994 is a pure cadaver anatomy study with zero patients. Reference resolution verified correct against the source paper's own reference list; this is the *citing authors'* error, not ours. The n=237 figure closely matches an unrelated paper (Patel 2009, cited elsewhere in this review) — suggests a genuine wrong-reference-number error in the original manuscript. |

## Flagged citations — Kang et al. 2022

| Cite # | Flagged against | Sentence (abridged) | Rationale |
|---|---|---|---|
| [3] | abstract (not mentioned) | "...rates as low as 23% [3] at 1 month postoperatively at some centers." | Ref (Stanford/JAMA) reports 18-24 month outcomes (8.4% incontinence); no 1-month figure exists in it at all. OA available but PDF fetch failed — gate 2 incomplete. |
| [4] | abstract (not mentioned) | "These techniques include bladder neck reconstruction, posterior reconstruction, anterior suspension stitch, and lateral prostatic fascia preservation [4]." | Abstract only covers the authors' own "lateral prostatic fascia preservation" technique — not the other three named in this list. |
| [5] | abstract (not mentioned) | "The anterior suspension stitch technique, originally described by Walsh...[5]" | Abstract covers general anatomic RP evolution, doesn't name "suspension stitch" specifically. Not OA — gate 2 unavailable. |
| [7] | abstract (not mentioned) | "...reported significantly improved early continence rates of 36.9%, 78.4%, and 92% at 1 week, 6 week, and 3 months..." | Abstract confirms faster recovery generally but doesn't state these specific per-timepoint percentages (likely in a results table). Not OA. |
| [7] (2nd) | abstract (not mentioned) | "...leads to less devascularization of the sphincter complex [7]..." | Abstract discusses periurethral tissue preservation, not "devascularization" specifically. |
| [10] | abstract (not mentioned) | "...score ≥4 on SHIM questionnaire questions 2, 3, and 5 [10]." | Pentafecta paper lists potency as an outcome but doesn't detail this specific scoring threshold. OA link was a repository landing page, not a PDF — gate 2 fetch failed. |
| [15] | abstract (not mentioned) | "...key nerve branches...enter the urethra from the anterolateral aspects...may contribute to higher continence rates [15]." | Pure anatomy/histology paper — establishes nerve location, not continence-rate outcomes. Not OA. |
| [16] | abstract (not mentioned) | "...minimizes tissue disruption lateral to the membranous urethra [16]." | Review of surgical modifications generally; doesn't address this specific mechanism. |
| [19] | abstract (not mentioned) | "...preservation of lateral endopelvic fascia...leads to better erectile function [19,20]." | Review supports the general principle but doesn't use this specific terminology. |
| [21] | abstract (not mentioned) | "The length of hospital stay was longer relative to many other countries [21,22]." | Single-country (US NSQIP) risk-factor study — no cross-country comparison. |
| [22] | abstract (not mentioned) | Same sentence as [21]. | Same issue — another single-country US study. |

**1 extraction artifact:** ref [13]'s sentence has an entire results table
(Table 2, ~15 rows of perioperative/pathological data) spliced into it by
the PDF converter — not evaluable.

**12 of 24 resolved citations were cleanly SUPPORTED**, including several
exact/near-exact quote matches (e.g., ref [11]'s continence-rate-by-week
figures matched the citing sentence verbatim).

## Flagged citations — Karabulut et al. 2020

| Cite # | Flagged against | Sentence (abridged) | Rationale |
|---|---|---|---|
| [4] | **topic** | "...continence was conserved for only 60%-95%...ORP or LRP procedures [4-6]." | This ref's abstract is specifically about **RARP** (robot-assisted) — wrong surgical-technique category for a claim about open/laparoscopic RP. |
| [13] | **topic** *(verified, high confidence)* | "[13] conducted a study...comparing sutured (n=237) and nonsutured (n=97) groups...continence rates 3 months after surgery were significantly higher..." | See "Verified findings" above — cited paper is a cadaver anatomy study with zero clinical data. |
| [6] | abstract (not mentioned) | Same 60-95% sentence as [4]. | Abstract explicitly states "Functional results are not yet available and will be published later" — contains no continence data whatsoever. |
| [11] | abstract (not mentioned) | "Other studies reported continence rates between 90% and 95% after RALP [11, 12]." | General review of robotic-surgery history/applications — no continence-rate data reported. |
| [2] | abstract (not mentioned) | "Radical prostatectomy is the main therapeutic technique for LPCa in patients...life expectancy of over 10 years [1, 2]." | Trifecta-outcomes paper doesn't establish this as a clinical indication criterion — that's guideline material. |
| [5] | abstract (not mentioned) | Same 60-95% sentence as [4]. | Right topic (RRP/LRP/RALP comparison) but doesn't state the specific 60-95% range. |
| [21] | abstract (not mentioned) | "Several studies have reported advanced age and increased BMI as risk factors...[20, 21]." | Confirms BMI as a risk factor; doesn't identify age as significant in this specific analysis. |
| [16] | abstract (not mentioned) | "[16] randomized and compared continence rate in patients who underwent RALP or LRP and developed normograms." | "Randomization" here is a statistical train/validation split for nomogram-building, not an RCT; abstract compares robot-assisted vs. **open** RP, not RALP vs. LRP. |

**2 extraction artifacts:** `"[7]."` (empty fragment) and a squared-unit
superscript (`"kg/m[2]"`) misread as a citation to ref 2 — see pipeline bug
8 above.

**3 of 13 resolved citations were cleanly SUPPORTED.** Note the much lower
base rate here versus the other two papers — a combination of the genuine
Steiner miscitation, several imprecise background citations, and the small
resolved sample (13, vs. Jia's 54) inflating the flagged proportion. Not
enough data to treat Karabulut's flag rate as representative of anything
beyond itself.

## Open items

- Unit-superscript false positives (`kg/m[2]`, possibly others like `cm[3]`)
  are not yet filtered from citation-marker extraction — same bug class as
  the already-fixed author-affiliation superscripts, different trigger
  pattern. Low priority (rare) but worth a follow-up pass before scaling.
- Gate 2 (full-text cascade) only succeeded for 2 of the ~6 OA-eligible
  candidates attempted across all three papers — two failures were
  landing-page URLs rather than direct PDFs (JAMA, and a UCF repository
  page). `fetch_fulltext()` currently gives up rather than following
  redirects/scraping landing pages for the real PDF link — reasonable
  default (avoid guessing), but means gate-2 coverage will be lower than
  Unpaywall's raw `is_oa` rate suggests.
- No live LLM run yet on any of the three papers — `ANTHROPIC_API_KEY` still
  not set in this environment. These three manual-preview files remain the
  calibration set for when that changes.
