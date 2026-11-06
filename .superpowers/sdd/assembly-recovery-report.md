# Task 1: assembly preview and submission recovery

Implemented only platform/frontend/app.js and tests/test_assembly_recovery_ui.cjs (plus this report). No commit, engine, real input or configuration writes.

## Interfaces
- Existing doRender(), invalidateSchemaPreview(), applyRuntimeState() names retained.
- New internal state: schemaPreview record {revision, context, body, token}, schemaSubmissionPending; existing schemaPreviewRevision retained.
- New helpers schemaPreviewContext(), schemaPreviewCurrent(record), refreshSchemaApplyState(). Context compares project epoch/revisions, saved/draft configuration, selected city/task/function, input values/checkboxes and local path overrides. Snapshot task/body is deep copied.
- submitRender(body, previewRecord = null) now returns {status}: applied, retryable_error, preview_stale, outcome_unknown, runtime_busy. Optional preview record guards asynchronous replies against input/project changes. Existing template callers remain compatible.
- Confirmation button is excluded from generic runtimeDisabled save/restore. Its enabled state is derived from current preview validity, local submission and S.runtime.busy. Direct invocation also guards these conditions.
- Ordinary errors and schema_ok=false retain valid previews. PREVIEW_STALE and unknown network write outcomes clear previews. RUNTIME_BUSY stays disabled until runtime idle. Success clears preview via existing taskIdentityChanged invalidation.

## Verification
Red: node tests/test_assembly_recovery_ui.cjs failed against original app at 'idle must preserve a valid preview' (true !== false).
Green: same test passes busy-preview-idle, retryable error, schema failure, invalidation-busy-idle, old handler, direct task mutation, network interruption, PREVIEW_STALE, RUNTIME_BUSY, duplicate invocation and successful clear/job update.
Existing tests passing: test_engineering_ui.cjs, test_runtime_ui.cjs, test_project_runtime_ui.cjs.
node --check platform/frontend/app.js and scoped git diff --check pass.

## Integration notes
Root may now edit app.js. Context helper currently computes its own minimal fingerprint; it can be connected to pure workflow revision model during integration. No dependencies or export changes. Unknown network outcome deliberately requires manual repreview and never retries writes. Runtime ownership remains server authoritative. Preview network errors are caught and displayed as repreview instructions.
