# cache/

Raw API responses, cache-first (same pattern as `raw_crossref/` in the parent
pipeline — check cache before hitting network, never edit these files by hand).

- `abstracts/pubmed/` — raw efetch responses, keyed by PMID. Primary abstract source.
- `abstracts/crossref/` — CrossRef responses with an abstract field, keyed by DOI.
  Fallback only; CrossRef abstract coverage is inconsistent.
- `abstracts/openalex/` — raw OpenAlex works responses (inverted index), keyed by
  DOI or OpenAlex ID. Last resort; requires index reconstruction to get plain text.
