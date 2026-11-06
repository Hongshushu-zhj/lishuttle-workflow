# Final integration review

Reviewed the frozen `.superpowers/sdd/integration-review.diff`, design and implementation plan, prior assembly/editor reports, and the composed frontend modules. This is a review of the frozen integration candidate, not certification of subsequent concurrent fixes. No existing suites were rerun; reported passes are not independent review evidence. Browser verification and full Python verification were still pending at review time.

## Findings

### P2 — Applying an existing executable silently drops unrelated project drafts

`platform/frontend/project-build.js:380` calls `applyProjectState(result, {preserveMachineDraft:true})`. The request deliberately sends saved non-build values, but `applyProjectState` then replaces the entire project draft and preserves only machine fields. Reproduce by typing an unsaved MAP_ROOT or OUT_ROOT, selecting a different preset with an already detected executable, then clicking 使用已识别程序. The resource text disappears without being saved or explicitly discarded. Keep the unrelated project draft, touched/manual metadata, and valid task selections when applying only build selection, or explicitly block applying until those drafts are resolved. This conflicts with the independent draft boundaries and returning to prior stages without erasing unrelated selections.

### P2 — Saving project configuration discards unsaved CSV/XML edits

`platform/frontend/app.js:129-139` checks polling/pending requests, but not CSV/XML dirtiness, before applying the returned project state. `applyProjectState` clears the parameter view, and `renderTasks` calls `clearCsvEditor`, which clears both dirty flags and `parameterDrafts`. Reproduce by editing a CSV cell without saving, then opening project configuration and saving. The table is replaced and its draft disappears without the required explicit save/discard decision. A failed XML autosave is similarly discarded. Guard this mutation and protect edits made during its request. The root independently identified this and reports a fix in progress.

### P2 — Changing the engineering CSV clears unrelated failed XML drafts

`platform/frontend/task-assembly.js:199-213` checks only `guardCsvChanges()` before calling `clearCsvEditor`; `clearCsvEditor` at line 193 also clears `parameterDrafts` and `S.xmlDirty`. Reproduce with an assembled job, a failed XML parameter save, and then selection of another engineering CSV from either selector. The failed XML value remains visually in the old parameter DOM but is no longer tracked as dirty; subsequent render/reload loses it. Do not clear XML draft state as part of CSV-only replacement, and guard selection while an XML draft or write is pending. The root was notified while fixes were underway.

## Other review conclusions

- Deterministic plain-script module ordering is coherent: definitions precede the final app bootstrap, with no new runtime dependencies.
- Assembly confirmation's captured request/context, structured outcomes, runtime-state recalculation, and backend PREVIEW_STALE contract match the previously reviewed repair.
- Workflow identity prevents a newly selected function/CSV from launching an old assembled job. Content revision invalidates preflight separately; async preflight uses a full workflow fingerprint, including content revision.
- Compiler-free reuse has a distinct action and does not require compiler readiness. Backend runtime and sid context remain authoritative.
- The six stage layout and shared operation panel are present; visual/browser assessment belongs to the pending browser QA.

## Acceptance

Resolve the draft-loss findings and review the resulting focused tests before accepting the integration. The root also reported concurrent fixes for filter rerender/draft loss and default-write races; these are outside this frozen review verdict and require final verification against the updated files.

## Focused re-review of live fixes

Read `review-fixes-report.md`, the complete `test_project_draft_guards.cjs`, and affected live handlers, plus editor pending-write/filter/retry-discard logic, cleanup availability, and unconfirmed assembly handling. All three original synchronous reproductions are addressed. Existing-executable application now preserves unrelated drafts and inputs through build-only application. Engineering selection preserves dirty XML. Configuration submission refuses preexisting dirty editors. Cleanup's explicit record supersedes WeakMap restoration, and an uncertain assembly no longer leaves an old assembly runnable. Root reports all Node suites and 357 Python tests passing; no full suites were repeated during this review.

### Remaining P2 — Configuration response can discard edits begun after submission

`platform/frontend/app.js:155-157` still applies project state unconditionally after awaiting `save_project_config`. The new dirty guard runs only before the request. `api-client.js` increments `pendingRequests` but does not lock editor input; `applyRuntimeState` locks inputs only after a backend busy observation, which need not arrive before a delayed configuration response (the backend may already be idle). Reproduce: load a clean CSV; submit project configuration; delay that response; edit a table cell; release the successful response. `applyProjectState → renderTasks → clearCsvEditor` clears the newly dirty table without explicit save/discard. An XML edit begun in the same window also loses its view/context. The added regression only tests dirty-before-submit, so it does not cover this case. Protect the local destructive-application interval, or preserve edits created during it; do not rely on periodic backend busy polling to prevent client-side draft loss. This is the remaining review blocker; final browser QA remains separately pending.

## Final focused acceptance

The residual delayed-response race is resolved in the latest live code. `withInputTransition` establishes a local lock before invoking project save/switch, executable application, or toolkit startup and releases it in `finally`. Runtime rendering computes effective input locking from backend busy OR that local transition, so an idle poll cannot release it. Raw XML controls and CSV contenteditable cells are covered, as are direct dirty callbacks and duplicate project actions. Backend runtime ownership remains separately stored; the local lock does not fabricate a backend session.

Inspected the extended deferred-response regression for save/switch/reuse on both success and network failure, intrinsic disabled-state restoration, idle-poll retention, direct-callback refusal, and the effective-busy mutation control. This directly covers the outstanding reproduction. No additional actionable blockers found in this focused re-review. All findings recorded above are now resolved. Code-review acceptance is **pass**, with the final browser rerun and root's final verification report remaining separate acceptance evidence. No tests were executed in this re-review.

### Toolkit startup occupancy follow-up

Reviewed the final three-line change: both successful `Api.toolkit` response branches now return `core.RUNTIME.snapshot()`, and `toolkitTransition` applies that snapshot immediately after validating its response and before attaching the console/releasing the local transition. This matches the established run response contract, preserves backend authority, and closes the initial polling window for long-running tool operations. An already-finished operation may correctly return idle. No new review concern; acceptance remains **pass**. The focused Python assertion checks response presence; root is rerunning final verification. Root reports the preceding final browser scenario suite passed 11 checks.
