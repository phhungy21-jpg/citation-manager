# TEMP_02 audit — findings summary

Two files reviewed at your request, using two different (user-approved) methodologies.

## File 1: `12879_2026_13284_OnlinePDF (1).pdf`
**Le et al., "Valve involvement in infective endocarditis among intravenous drug users: a systematic review and meta-analysis," BMC Infectious Diseases (2026).**

Full 2-gate claim audit (same methodology as the JAMA Network Open sample, corrected mid-review to actually run Gate 2 — see note below): 39 references resolved to DOIs via Crossref, abstracts fetched via Crossref/PubMed/OpenAlex, 64 citation-instances checked across the Introduction, Rationale, Methods, and Discussion sections. Full detail: `results/preview/external/TEMP_02_IVDU-endocarditis-BMC.manual-preview.json`.

**Counts (after Gate 2): 32 SUPPORTED, 26 PARTIALLY_SUPPORTED, 3 UNSUPPORTED, 3 NOT_EVALUABLE.**

**Process note — Gate 2 was initially skipped, then run properly.** My first pass only checked claims against abstracts (Gate 1) and left 35 items sitting at "not confirmable from abstract." That's a real process gap: the project's own methodology says any non-SUPPORTED Gate-1 verdict should trigger an Unpaywall full-text lookup before being reported as a flag. Once I ran Gate 2, full text was retrievable for 4 of the 13 references behind the flagged claims (Clarelin, Leungsuwan, Shmueli, Parashar), and **10 of those items got upgraded from PARTIALLY_SUPPORTED to SUPPORTED** — most notably, all 7 flagged claims tied to the Clarelin reference (surgery rates, 5-year survival, embolism risk, pathogen breakdown, trend framing) turned out to be exact matches to that paper's Results tables, just not present in its abstract. That's a clean demonstration of why Gate 2 exists — abstract-only checking would have produced 7 false "unsupported" flags on citations that were actually precise. The remaining 9 references couldn't get Gate 2 treatment (5 aren't open access at all; 2 are OA per Unpaywall but the direct-PDF fetch hit a bot-check/landing page; 2 have PMC records with only front-matter metadata, no body text) — those items remain at their Gate-1 verdict, clearly marked as such in the JSON.

**Notable findings (survive Gate 2):**
1. **Two duplicate reference-list entries.** Ref 4 and ref 34 are the identical paper (Clarelin et al., *Sci Rep* 2021), and ref 26 and ref 32 are the identical paper (Huang et al., *Infection* 2020) — each cited under two different numbers in the same reference list. Confirmed by resolving both to the same DOI independently.
2. **One likely wrong-reference-number citation.** "The incidence of IE among IVDUs has increased substantially in parallel with the opioid epidemic [4]" cites Clarelin et al., a cross-sectional registry comparison with no trend/opioid-epidemic content. Ref 1 (Khayata et al.)'s abstract opens with almost the identical sentence ("IE is associated with...and parallels the opioid pandemic") — strong evidence the citation number should be 1, not 4.
3. **One internally contradicted claim.** The Emara et al. citation (ref 36) is used to support "greater rates of multi-organ failure" alongside mortality/recurrence findings that do match — but the abstract explicitly reports "no significant difference in heart failure incidence" (RR 1.02, p=0.82), the closest reported outcome, pointing the opposite direction.
4. The RSIE *S. aureus* "up to 85%" figure — initially flagged as a mismatch against the Clarelin abstract's 88% — turned out to be an **exact match** to that paper's own Results table (85%/46%, vs. the abstract's rounded 88%/48%). Resolved by Gate 2; the citing paper cited the underlying data correctly. Several claims tied to the Moss & Munt 2003 reference (e.g., the "14% left-sided" figure) remain unconfirmed — that source has no structured abstract and its PMC record has no retrievable full-text body, only front matter.

## File 2: `manuscript-methods-results-v2.md` (your meta-analysis draft, EPUP vs non-EPUP continence)

Per your choice, I checked only the `[I-1]`–`[I-8]` included-study claims against their source papers (not `[24]`, `[25]`, `[N-2]`–`[N-7]`, since this excerpt has no reference list for those). I identified all 8 named studies from context clues in the draft (technique names, ROBINS-I risk-of-bias groupings) and searched PubMed/Crossref for each:

| Code | Study | Found? |
|---|---|---|
| I-1 | Bianchi 2018 ("collar" technique) | Yes — PMID 29402756 |
| I-2 | Hamada 2014 (MULP vs PRAS) | Yes — PMID 24739066 |
| I-3 | Heo 2020 (MULP + BNP) | Yes — PMID 31929596 |
| I-4 | Hoeh 2022 (FFLU) | Yes — PMID 37783172 |
| I-5 | Jia 2023 (SFUR, RCT) | Already in your library from earlier calibration work |
| I-6 | Ko 2020 (MUL surgical maximization) | Yes — PMID 32647641 |
| I-7 or I-8 | Bragayrac 2020 | **Not found** — no PubMed/Crossref match with several search variants; may be a conference abstract, non-indexed source, or differently-spelled author name |
| I-7 or I-8 | Karabulut 2020 | Already known from earlier calibration work |

**The one finding worth flagging directly: your draft mischaracterizes what "PRAS" stands for.**

Your Results section says (§3.4, "At one month"):
> "The extreme estimate from Hamada 2014 [I-2] reflects an unusual comparator — the prostatic rhabdosphincter-assisted surgery (PRAS) technique rather than standard RARP"

Hamada et al. 2014's actual abstract (PMID 24739066, "Early return of continence in patients undergoing robot-assisted laparoscopic prostatectomy using modified maximal urethral length preservation technique") defines PRAS as **"posterior urethral Reconstruction and Anterior bladder Suspension"** — a continence-preserving reconstruction technique, not "prostatic rhabdosphincter-assisted surgery." The study actually compares three groups: PRAS alone (worst continence: 10%/23.3%/53.3% at 1/3/6 months), MULP+PRAS combined (90%/96.7%/100%), and MULP alone (70%/90%/96.7%... continence improves with MULP). Their conclusion is literally "MULP rather than PRAS confers higher postoperative CR" — i.e., PRAS is the standard/older technique and MULP is the improvement, which is the opposite framing from calling PRAS the "unusual comparator."

This looks like a genuine factual error in the draft (an incorrect expansion of the PRAS acronym, and a likely mischaracterization of which arm is the "unusual" one) rather than a citation-support gap — worth fixing before this goes further, and worth double-checking whether the specific RR=7.00 figure attributed to Hamada 2014 was extracted from the correct group comparison.

**Not independently verified** (would require full-text tables, not abstracts, to check exact RR/CI/percentage extractions): the specific numeric values attributed to Bianchi, Heo, Hoeh, Ko, and Bragayrac (e.g., Hoeh's "86% vs 51%" NVB preservation figure, Heo's RR=1.22 at catheter removal, Ko's PSA-screening-era-change explanation). These weren't contradicted by anything I found, but abstracts alone don't contain that level of table-level detail, so I'm not calling them confirmed either.

## Recommended next step
For the draft manuscript, if you want the `[24]`, `[25]`, `[N-2]`–`[N-7]` methodology citations checked too, share the full reference list (or the complete manuscript) and I'll run the same audit on those.
