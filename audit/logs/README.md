# logs/

Audit-trail layer. This is what makes the eventual paper's methods section
defensible under reviewer scrutiny — everything here must be reproducible from
the cache alone, no re-running against live APIs required to verify a claim.

## llm_calls/

One file per LLM call, named by a hash of the input (model + prompt + claim +
abstract text). Fields: model version, full prompt, full input, full output,
timestamp. Rerunning the same input must hit this cache, not the API — keeps
reruns free and keeps the audit trail stable across sessions.

## sessions/

One file per script invocation (e.g. `check_claims.py` run against a paper):
what ran, args, start/end time, papers processed, counts (flagged/unflagged/
errored). Not a substitute for llm_calls/ — this is the run-level summary.
