# Adjudication Criteria — Citation-Claim Support Audit

Dated: 2026-07-01 (written before any full-sample run — see `audit/STATUS.md`
for what "full-sample" means here and why nothing has been sampled yet).

This document exists to be written *before* results are scored, so criteria
can't be accused of emerging post-hoc from what the tool happened to find.
If a rule changes after this date, add a new dated section below — do not
edit the original text out from under it.

## Scope: what this audit measures

Every automated verdict in this pipeline is **abstract-only**. The LLM in
`check_claims.py` is explicitly instructed to judge whether a citing
sentence's claim is supported by the cited paper's *abstract text* — not by
the cited paper as a whole. This is a real limitation, not a technicality:
structured abstracts routinely omit secondary findings (subgroup analyses,
QoL sub-scores, safety data) that exist in the full text.

Consequence: **"UNSUPPORTED" from this pipeline means "not supported by
the abstract," never "not supported by the paper."** Every automated check
entry carries `"verdict_basis": "abstract_only"` for exactly this reason.
When reporting results (in the paper, in any summary), use "abstract-
unsupported" or equivalent precise language — not bare "unsupported."

Full-text verification of flagged citations, where the paper is accessible,
is a manual adjudication step (see below), not something the automated
pipeline attempts.

## Verdict categories

- **SUPPORTED** — the abstract directly and specifically supports the claim
  as stated, with an exact quoted span backing it.
- **PARTIALLY_SUPPORTED** — the abstract supports part of the claim, a
  weaker/different version of it (different magnitude, different
  population, correlation vs causation), or the claim is more specific than
  the abstract can back up. Also used for "overstated" claims — abstract
  says X, citing sentence says a stronger version of X.
- **UNSUPPORTED** — the abstract does not address the claim's actual
  content, or the claim asserts something the abstract contradicts or
  doesn't mention. Includes topic mismatches (cited paper measures a
  different outcome entirely) and specific numeric claims not found in the
  abstract.

A verdict of PARTIALLY_SUPPORTED or SUPPORTED always requires an exact
quoted substring from the abstract. A model or reviewer that can't produce
a quote can't claim support — this is enforced in the LLM prompt and should
be enforced identically by human adjudicators.

## Co-cited references (multi-citation sentences)

The pipeline checks each citation in a multi-reference marker (e.g.
`[2,3]` or `[12,21,25]`) **independently** against the same sentence — a
sentence citing 3 references produces 3 separate check entries, not one
group verdict. This was a deliberate design choice (see
`audit/NOTES.md`, 2026-07-01) to keep the false-positive-rate denominator
at "citations," not "sentences."

This has a known side effect: **synthesis citations** — where a sentence
cites multiple sources whose individual findings only jointly support the
claim (e.g., "effects are mixed [12,21,25]" citing one positive trial, one
negative trial, and one review) — will often score each reference as
PARTIALLY_SUPPORTED or UNSUPPORTED individually, even though the citation
practice is legitimate and the group of sources together supports the
sentence.

**Adjudication rule:** when reviewing a flagged citation, check whether it's
part of a multi-citation marker where the other co-cited references, taken
together, substantiate the claim. If so, adjudicate the *group* as
supported-by-synthesis and do not count the individual flags as confirmed
miscitations — unless one or more of the individual abstracts is actually
irrelevant or contradictory to the claim (in which case that specific
reference is still a legitimate flag; a bad citation inside a
mostly-reasonable group is still a bad citation).

This rule exists because per-citation independent checking is a deliberate
methodological simplification for automation, not a claim that every
citation must independently prove the whole sentence.

## Confirmed vs. plausible flags — the primary outcome

Per the handoff's non-negotiable requirement: **report the false-positive
rate on flagged citations** ("of citations flagged by automated check, X%
were confirmed unsupported on manual review"), not an extrapolated
population rate.

Adjudication categories for a flagged (non-SUPPORTED) automated verdict:

- **CONFIRMED** — manual review agrees the claim is not supported by the
  cited paper (checked against full text where available, not just the
  abstract). This is the number that counts toward the headline rate.
- **SYNTHESIS** — see above; part of a legitimately joint citation, not
  counted as a confirmed miscitation on its own.
- **ABSTRACT-LIMITED** — the abstract genuinely doesn't support the claim,
  but full-text review shows the paper does. Counts as a false positive of
  the automated abstract-only check, not a true miscitation by the citing
  author. Track separately — this number tells you how much the
  abstract-only limitation costs in practice, which matters for deciding
  whether Phase 3 needs full-text retrieval.
- **REJECTED** — manual review disagrees with the flag; the abstract does
  support the claim and the automated check was simply wrong (LLM error).

## Second reviewer

**Decided 2026-07-01, before the JAMA Network Open n=100 run:** solo review.
No second reviewer is available for this run. This is a real limitation —
log it explicitly in the eventual manuscript's limitations section, not
just here. Expect peer reviewers to ask "how do you know these are real
errors and not your own misreading" — the honest answer for this run is
"single-rater adjudication, no kappa available." If a second reviewer
becomes available before submission, retroactively sample 20-30% of
CONFIRMED flags for independent re-adjudication and report agreement.

## Primary outcome

**Decided 2026-07-01, before the JAMA Network Open n=100 run:**

> Of citations flagged by the automated pipeline (gate 1 abstract check,
> escalated to gate 2 full-text check where OA text was fetchable) as
> PARTIALLY_SUPPORTED or UNSUPPORTED, the percentage that are adjudicated
> CONFIRMED (true miscitation) on manual review.

This is a rate **among flags**, not a population-wide miscitation rate —
per the handoff's original non-negotiable requirement (see above) and
consistent with the 3-paper calibration pass. Explicitly NOT the primary
outcome: "% of all checked citations that are miscitations" — that
framing was considered and rejected because it requires trusting every
non-SUPPORTED verdict as meaningful without adjudication, which the
calibration pass showed is not warranted (many PARTIALLY_SUPPORTED flags
in the calibration set were synthesis citations or abstract-only
limitations, not miscitations).

**Secondary/descriptive outcomes** (not the headline number, but worth
reporting): overall flagged-citation rate (% of all checked citations
flagged, pre-adjudication); breakdown of CONFIRMED miscitations by
FLAG_TYPE (TOPIC_MISMATCH / NUMBER_CONTRADICTION / NOT_MENTIONED);
resolution rate (% of citations successfully mapped to a DOI); ABSTRACT-
LIMITED rate (how often gate 2 rescues a gate-1 flag — this is the number
that justifies the two-gate design's cost).

## Sample frame

**Decided 2026-07-01:** JAMA Network Open, original research articles only
(excludes editorials, viewpoints, letters, research letters, reviews,
comments), n=100, most recently PubMed-indexed as of the pull date. Full
frozen sample specification and PMID/DOI list: see
`audit/data/preregistration/2026-07-01_jama-network-open-100.md`. The
sample list is pulled and frozen (written to disk, dated) before any
citation-checking begins — per "write the criteria down before looking at
results."
