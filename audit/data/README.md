# data/

- `library_abstracts.json` — parallel abstract store keyed by citekey (mirrors
  `library.csl.json` citekeys but lives separately, per the decision to avoid
  bloating the bibliography — confirm this call still stands before Phase 1 build).
- `manuscripts/` — input papers being audited: Markdown with `@citekey`, or
  PDF/DOCX of published papers (audit uses published papers, so PDF parsing
  matters here).
- `preregistration/` — dated `.md` files defining supported/partially-supported/
  unsupported criteria, adjudication process, second-reviewer involvement, and
  primary outcome. Required before any full-sample Phase 3 run. Do not skip.
