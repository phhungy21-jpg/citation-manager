# Citation Pipeline — Claude Code Instructions

Toolbox location: `C:\Users\Hung\Desktop\Research\Toolbox\citation-pipeline\`

## Core rule
Never invent citations, DOIs, PMIDs, authors, journals, years, or titles.
Only use citekeys that exist in `library.csl.json`.

## When writing manuscript text
- Insert only citekeys present in `library.csl.json` using `@citekey` syntax
- If a citation is needed but absent, write `[CITATION NEEDED: topic]` — never fabricate
- Run `validate_citations.py` before any manuscript export

## When adding references
- Use `add_reference.py <DOI>` — the only permitted source of new citekeys
- DOI lookup via CrossRef is mandatory; title-only searches are not permitted
- If CrossRef returns a 404, flag it explicitly rather than guessing metadata
- Metadata (including abstract) is merged from Crossref, PubMed efetch, and
  OpenAlex, with a fixed backfill priority per field — see the docstring in
  `add_reference.py`. A source missing a field is skipped, never guessed.

## When asked "what papers support X"
- Search PubMed or CrossRef and return DOIs
- Do not invent author names, journal names, or publication years
- User adds to library first, then cites

## File rules
- Do not edit `raw_crossref/`, `raw_pubmed/`, or `raw_openalex/` files
  manually — they are API caches (CrossRef, PubMed efetch, OpenAlex)
- Do not edit `library.csl.json` manually; use `add_reference.py`
- `registry.csv` is a human-readable audit log; do not parse it for metadata
  (it now also records `has_abstract`, `abstract_source`, `openalex_id`)

## Project-specific refs (numbered reference lists)
For projects using a numbered `refs_master.json` (not @citekey style):
- `format_jama.py --refs path/to/refs_master.json` renders JAMA-style output
- Keep each project's `refs_master.json` inside the project folder, not here
- The CrossRef cache in `raw_crossref/` is shared across all projects

## Build workflow (citeproc / pandoc)
```
python add_reference.py <DOI>            # add reference → updates library.csl.json
python validate_citations.py paper.md   # verify all @citekeys exist
pandoc paper.md --citeproc \
  --bibliography library.csl.json \
  --csl vancouver.csl \
  --reference-doc reference.docx \
  -o paper.docx
```

## Build workflow (numbered JAMA list)
```
python format_jama.py \
  --refs path/to/project/refs_master.json \
  --output refs_jama.txt
```
