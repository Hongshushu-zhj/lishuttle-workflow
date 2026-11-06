# Final review fixes verification

Scope: final-review.md draft-loss findings. No engine run, dependencies, commits, or real configuration changes.

## Fixes verified

- Project configuration submission refuses dirty CSV and failed XML drafts before posting or resetting their state.
- Engineering CSV selection refuses a failed XML draft, retaining parameterDrafts and restoring both engineering selectors.
- Existing executable reuse now applies build-only saved values through applyBuildStatus rather than resetting the project. It preserves independent resource drafts, their exact touched/manual metadata, and selected city/task references while invalidating the old assembly. The request sends saved resource values, so unrelated drafts are not accidentally persisted. Reuse succeeds with a detected selected executable even when the prior active build reports built:false; it sends no compiler request.

## Regression evidence

Added tests/test_project_draft_guards.cjs using the composed frontend source and a minimal VM/DOM fixture. Before the additional executable fix, it failed at `equal-value touched metadata survives` (false !== true). After the fix it passes. The suite additionally mutates each of the three protections in memory and verifies the corresponding regression fails, without editing application files for those negative controls.

Executed successfully:

- node tests/test_project_draft_guards.cjs — PASS, including three mutation regressions.
- node tests/test_project_workflow_ui.cjs — PASS.
- node tests/test_project_runtime_ui.cjs — PASS.

These are focused in-memory UI regressions; they do not certify browser layout or run the engine. Root is handling final whole-suite/browser verification and other concurrent fixes.

## Deferred project-response draft race

Added a separate local `S.inputTransition` boundary shared by project save/switch, existing-executable application and toolkit startup. It locks raw XML inputs, CSV contenteditable cells and mutation controls during the whole request/application interval, while keeping backend runtime ownership and cancel eligibility authoritative. Idle polling cannot release this local lock. A finally path releases it on success and network failure; intrinsic disabled controls stay disabled. Duplicate/direct project mutation handlers and editor dirty/write callbacks refuse the transition. Navigation and log/result controls are not locked.

Deferred-response regressions cover save, switch and executable reuse, each with success and network failure; they assert raw-editor locking, idle-poll retention, direct-callback refusal and eventual unlocking. Removing the local effective-busy expression in memory makes the regression fail (four mutation controls total). No real backend requests were made.

Re-ran successfully: test_project_draft_guards.cjs, test_runtime_ui.cjs, test_project_runtime_ui.cjs, test_project_workflow_ui.cjs and syntax checks for all five affected frontend modules.
