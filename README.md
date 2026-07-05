# Citation Validator

Tools for maintaining a verified, citation-checked reference library for manuscripts. The core rule: **no citekey, DOI, author, journal, year, or title is ever invented** — every reference comes from CrossRef, PubMed, or OpenAlex via `add_reference.py`.

See [CLAUDE.md](CLAUDE.md) for the authoritative rules Claude Code follows in this repo.

## Requirements

- Python 3
- `requests`
- (optional, for `audit/`) `pymupdf4llm`, `ANTHROPIC_API_KEY` env var for LLM-backed claim checking
- (optional, for `audit/`'s multi-format ingestion) `pandoc` on PATH (docx/LaTeX/HTML manuscripts); a locally-run [GROBID](https://github.com/kermitt2/grobid) service for higher-fidelity PDF conversion (`GROBID_URL`, default `http://localhost:8070` — falls back automatically to the `pymupdf4llm` path if unreachable); `CORE_API_KEY` to enable the CORE fallback in reference resolution

## Core workflow (CSL-JSON / `@citekey` manuscripts)

```bash
# 1. Add a reference by DOI — the only permitted way to add a citekey
python add_reference.py 10.1111/bju.15956

# 2. Verify every @citekey in a manuscript exists in the library
python validate_citations.py paper.md

# 3. Render the manuscript with pandoc + citeproc
pandoc paper.md --citeproc \
  --bibliography library.csl.json \
  --csl vancouver.csl \
  --reference-doc reference.docx \
  -o paper.docx
```

### `add_reference.py`
Looks up a DOI and merges metadata from three sources into one standardized record:
- **CrossRef** — primary bibliographic data (title, authors, journal, volume/issue/page)
- **PubMed efetch** — primary abstract source, PMID
- **OpenAlex** — fallback for whatever CrossRef/PubMed are missing

A source missing a field is skipped in the backfill chain — never guessed. Writes/updates:

| File | Purpose |
|---|---|
| `library.csl.json` | Pandoc-compatible bibliography |
| `registry.csv` | Human-readable audit log (not a metadata source — don't parse it) |
| `raw_crossref/<doi>.json` | Raw CrossRef response (audit trail) |
| `raw_pubmed/<pmid>.xml` | Raw PubMed efetch response (audit trail) |
| `raw_openalex/<doi>.json` | Raw OpenAlex response (audit trail) |

Do not hand-edit `library.csl.json` or the `raw_*` cache directories.

### `validate_citations.py`
Checks that every `@citekey` referenced in one or more Markdown files exists in `library.csl.json`. Exit code `0` = all valid, `1` = missing citations found.

```bash
python validate_citations.py manuscript.md
python validate_citations.py *.md
python validate_citations.py --dir path/to/manuscripts/
```

## Numbered reference lists (JAMA style)

For projects that use a numbered `refs_master.json` instead of `@citekey` style:

```bash
python format_jama.py --refs path/to/project/refs_master.json --output refs_jama.txt
```

Each entry needs an `"n"` (number) and either a `"doi"` (auto CrossRef lookup, cached in `raw_crossref/`) or a `"manual"` pre-formatted citation. Keep each project's `refs_master.json` inside that project's own folder — the CrossRef cache under `raw_crossref/` is shared across projects. Use `--no-fetch` to render from cache only, with no network calls.

## Repo layout

```
add_reference.py       add a reference by DOI (CrossRef + PubMed + OpenAlex merge)
validate_citations.py  verify @citekeys against library.csl.json
format_jama.py          render a numbered JAMA-style reference list
library.csl.json        the citation library (edit only via add_reference.py)
registry.csv             human-readable audit log
raw_crossref/            cached CrossRef API responses
raw_pubmed/              cached PubMed efetch responses
raw_openalex/            cached OpenAlex API responses
reference.docx           pandoc reference doc for Word output
audit/                   separate sub-project: LLM-assisted citation-accuracy
                         auditing of published papers (see audit/STATUS.md
                         and audit/MANIFEST.md); format_router.py normalizes
                         PDF/docx/LaTeX/HTML/JATS input, ref_resolver.py +
                         citation_registry.py + fallback_sources.py do
                         hardened, deduped, never-guess reference resolution
docs/                    supporting docs (e.g. adjudication criteria)
```

## `audit/` subsystem

A separate, in-progress sub-project that checks whether a paper's in-text claims are actually supported by the papers it cites. Current status, phase, and known issues are tracked in `audit/STATUS.md`; the file/script inventory is in `audit/MANIFEST.md`; decision history is in `audit/NOTES.md`. Requires `ANTHROPIC_API_KEY` for the LLM-backed steps.

```bash
python audit/check_claims.py "paper.md"                 # .md handled directly
python audit/check_claims.py "paper.pdf"                # GROBID, or pymupdf4llm fallback
python audit/check_claims.py "paper.docx"                # any of docx/tex/html/xml, via pandoc/format_router
python audit/check_claims.py --pmcid 11707628            # PMC structured JATS XML
```

**Ingestion — `format_router.py`:** normalizes any manuscript format to one standard shape before claim-checking. Dispatches by file suffix: `.xml` (JATS) passthrough; `.pdf` via `grobid_client.py` (falls back automatically to the existing `pdf_to_md.py`/pymupdf4llm path, tagged lower-confidence, if GROBID isn't reachable); `.docx`/`.tex`/`.html` via `pandoc_convert.py` (pandoc's JATS writer, with a structural fallback for manuscripts whose reference list was never citation-linked). `.md` is handled directly by `check_claims.py`, not routed through here — it has its own long-tuned parsing logic. GROBID's table/figure detection is tagged as low-confidence (`low_confidence_spans`) but not read for content; there's no dedicated table/figure agent yet.

**Reference resolution — `ref_resolver.py`:** resolves a numbered reference-list entry to a DOI through an escalating, never-guess cascade: a DOI already in the text is validated directly (a dead DOI is flagged `doi_invalid`, distinct from `unresolved`); a `citation_registry.py` ledger (`audit/data/citation_registry.json`) dedupes against every prior resolution attempt, in this or any prior run, before any network call; exact-title, then fuzzy-title (with an ambiguity-gap rule — two comparably-scored candidates are left unresolved rather than guessed between) Crossref search; then an escalating fallback (`fallback_sources.py`): Semantic Scholar → DataCite → arXiv/bioRxiv/medRxiv → CORE (needs `CORE_API_KEY`, skipped cleanly without one). Every attempt's outcome, resolved or not, is recorded to the ledger with a `resolution_method` for traceability. `citation_registry.json` is separate from `library.csl.json` — the audit subsystem never writes to the manuscript bibliography.

## File rules

- Never manually edit `library.csl.json` — use `add_reference.py`.
- Never manually edit `raw_crossref/`, `raw_pubmed/`, or `raw_openalex/` — they are API caches.
- `registry.csv` is an audit log for humans, not a metadata source to parse.
