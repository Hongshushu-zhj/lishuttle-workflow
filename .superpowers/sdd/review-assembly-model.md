# Scoped review: assembly recovery and pure workflow model

## Verdict

No critical or important actionable findings in the reviewed scope. Spec compliance: pass for the standalone assembly recovery and pure state model. Code quality: pass; state transitions and request outcomes are explicit, and the model remains dependency-free and separate from runtime session ownership.

## Scope and evidence

Reviewed the implementation plan, both implementation reports, `.superpowers/sdd/assembly-review.diff` (the frozen application/backend/test snapshot), `platform/frontend/workflow-state.js`, and `tests/test_workflow_state.cjs`. Application conclusions refer only to the snapshot, not concurrent integration edits. No tests were rerun; reported verification is supplied by the implementation reports, not independently reproduced here.

## Requirement assessment

- Ordinary render API errors and `schema_ok=false` return `retryable_error`; the confirmation handler clears its pending flag in `finally` and recomputes availability, preserving a current preview for retry.
- `PREVIEW_STALE` and network/JSON response failure produce invalidating outcomes. Revision, captured context, record identity, project epoch, and invocation-time checks prevent obsolete responses/handlers from applying old requests.
- Confirmation is excluded from generic runtime-disabled restoration. Its availability derives from preview validity, local submission pending state, and authoritative backend occupancy. Busy/idle polling therefore cannot restore invalid previews or preserve an obsolete disabled bit. API-level `RUNTIME_BUSY` handling applies returned backend runtime state.
- Pure model permits executable reuse without a compiler, while compilation independently accepts a valid unapplied build draft. Assembly/run remain blocked until the applied build is ready.
- Semantic fingerprint changes invalidate assembly; successful XML/CSV content changes preserve assembly and invalidate preflight through a separate content revision. Canonical snapshots avoid property-order false changes and clone supplied contexts.
- Runtime facts are supplied externally; the model neither fabricates occupancy nor owns sid/result context. Runtime stage identity prevents compilation from being presented as a simulation run.

## Integration boundaries

The pure model deliberately requires complete semantic snapshots and current backend/readiness facts. It does not reject obsolete asynchronous replies itself. Its report documents both obligations, so wiring those facts and response guards remains part of the root integration review rather than a defect in this scoped implementation. Existing captured handlers are rendered inert by guards rather than literally removed; this satisfies the stale-handler safety requirement.
