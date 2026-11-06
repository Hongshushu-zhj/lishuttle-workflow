# Final broad P0 integration review

Reviewed `p0-brief.md` (requirements rather than its stale progress ledger), README, `whole-change.diff`, current implementation and focused review reports. Inspected the runtime guard, Windows process ownership, lifecycle/error recovery, all API routes, fixed launch/session context, result endpoints, configuration read changes, and frontend launch/recovery/result flows. Sampled the current preflight/validator integration and their regressions; detailed model-format acceptance remains the separate validation review's scope. No engine execution, engine/source/input edits, implementation edits or commits were performed. This report is the only checkout file written by this reviewer.

## Verdict

**Specification and code quality approved for the broad integration scope, with one nonblocking Minor finding. No new Critical or Important finding.** The separately assigned detailed validation re-review must supply its own final verdict; this report does not supersede it or claim numerical engine acceptance.

The lease is reserved before preflight and mutating configuration work, handed off by token to the session, and retained through managed-tree exit and finalization. The mutating API routes use the outer reservation; idle-only implicit configuration work is also reserved, while busy reads use nonpersistent configuration interpretation. Windows roots are suspended until assigned to their job, and job activity rather than root exit determines release. Stop, retryable termination errors, monitor recovery, and shutdown keep the session accountable. No additional writer bypass or stale-token release was found.

Run context and results are copied and bound to the original sid. Session results avoid current-project lookup; directory browsing is explicitly unassociated. The frontend separates exit, artifact integrity, and business usability, handles missing sessions after restart, restores an active sid across tabs, and does not promote exit zero or historical directory markers to current-run success. Reviewed mode/context/help changes preserve raw mode parsing and the ground/actual-floor/3d/indoor/calibration distinctions. Unknown function/index support remains explicitly unconfirmed where inspected; no unsupported format was reported as a newly established broken supported format in this review.

## Minor: restored builds skip normal build-status refresh

**Location:** `platform/frontend/app.js:1173`; normal build completion behavior at `:1077`–`:1082`.

**Trigger:** refresh the page or open another tab while a build is active, let runtime recovery attach its console, then let that build complete. Recovery calls `attachConsole` without `onDone`. The normal initiating build path supplies a callback that POSTs `build_status` and calls `applyBuildStatus`; recovery never reconstructs that callback. The console can therefore show successful completion while the build guide/summary retains its pre-completion `built` value, and that page does not request normal executable/configuration synchronization.

**Independent evidence:** an isolated Node VM used the actual current frontend, restored build sid 42 with an existing `S.buildWorkflow.built=false`, and delivered a done/exit-zero build output. The complete request list was `/api/output?sid=42&since=0` followed by `/api/runtime_state?...`; no `build_status` request occurred. The polling timer cleared, but `S.buildWorkflow.built` remained false. No real build or application data was involved.

**Suggested repair:** when a restored session's fixed context identifies `operation='build'`, refresh build status once completion is observed, applying it only to the matching project/revision with the existing draft-preservation rules. Cover the restored-build path as well as the initiating-build callback. This is nonblocking because execution ownership, cancellation and conservative run-result reporting remain correct.

## Independent verification

- `python -m unittest discover -s tests -p test_runtime*.py`: **37 tests passed**, exit 0.
- `node tests/test_runtime_ui.cjs`: **passed**, exit 0.
- The additional restored-build VM probe produced the concrete Minor evidence above.
- `git diff --check`: exit 0; only the existing LF/CRLF conversion notice for `tests/test_project_defaults.py` was printed.

The parent's reported full Python/JS suites, preflight suite, validator suite and real isolated acceptance records were not independently repeated here. No new claims about binary/source parity, physics accuracy, unsupported model versions, or real-engine success are made.

## Restored-build follow-up: Minor closed

Inspected the narrow repair in `attachConsole` (`platform/frontend/app.js:1297`, completion branch at `:1344`) and the new restored-build regression in `tests/test_runtime_ui.cjs`. The console attachment now captures the project, project epoch and sent draft. A completed restored session with fixed `context.operation='build'` requests `build_status` and passes its result through `applyBuildStatus`. It checks the original epoch and matching session project before requesting, checks the epoch again after the response, and preserves the existing initiating-build callback path. Passing the captured draft retains the existing protection for later draft edits.

Independently reran `node tests/test_runtime_ui.cjs`: **passed**, exit 0, including the new sid-42 restored-build regression. The parent's reported project-workflow and run-log suites were not rerun in this narrow follow-up. No engine execution or implementation edits were performed.

**Superseding broad integration verdict: specification approved; code quality approved. Remaining Critical: zero; Important: zero; Minor: zero.** The detailed validator review remains independently scoped.
