# Workflow layout implementation report

Scope: Task 3 HTML/CSS and static layout test only. No app.js, README, engine, configuration or input data edits. No commits.

Six native collapsible stages now follow project → build → inputs → assembly → check → run. Existing controls are moved, not duplicated; every original HTML ID is preserved exactly once. Build actions and build selection share one card. Map/task catalogs, task/function identity, CSV and XML inputs share the input stage; CSV editing is a native details disclosure. Parameters and preflight share the check stage. Start and results share the final stage. Log, stop and export live in a shared details panel outside stages.

Styles retain parameter tables, CSV grid and results. Old tab hiding selectors are removed. Navigation is sticky on desktop and a compact three-column grid at <=720px. Input catalogs/settings use two columns on wide screens and stack on narrower screens. Path/status text wraps. No new fonts, frameworks or network assets.

## Integration hooks

- `workflow-nav` is intentionally empty for root's shared stage definitions. `workflow-main` is the main landmark. Stage IDs are `stage-project`, `stage-build`, `stage-inputs`, `stage-assembly`, `stage-check`, `stage-run`, with matching `data-stage` values and `stage-KEY-status` spans.
- Bind `btn-show-operation` to open/focus `operation-panel`; update `operation-title` for the active operation. Existing `run-console`, `btn-stop`, `btn-export-log` are inside that panel.
- Bind `btn-use-executable` to existing executable reuse. Existing `build-summary` stays inside the program stage and can report executable/path status.
- Fill `assembly-summary`, `schema-apply-status` (polite status), and `build-action-reason`, `assembly-action-reason`, `check-action-reason`, `run-action-reason`. Action buttons reference these reasons with aria-describedby.
- `csv-editor` disclosure contains the original CSV controls. Bind `csv-dirty-status` and `btn-csv-discard` (initially hidden); root must keep `csv-path` synchronized to `engineering-path` and handle unsaved changes.
- All four old tab wrapper IDs and hidden data-tab buttons remain compatibility hooks. Root should route switchTab calls to stage/disclosure navigation; wrapper `.tab` visibility rules no longer exist.
- Existing `workflow-steps` remains a hidden compatibility list; root should render the actual stage navigation/status rather than rely on its old guide.
- Script entry remains `app.js` unchanged. Primary function emphasis will be bound by root.

## Verification

`node tests/test_workflow_layout.cjs` first failed because six ordered stages were absent, then passed after implementation. It checks unique IDs, stage order and native summaries, control co-location, status semantics and log controls outside stage cards. `node --check tests/test_workflow_layout.cjs` and `git diff --check` passed. A generation-time comparison also confirmed every original HTML ID remains present exactly once.

No screenshots or browser/engine runs in this task. Root owns behavior integration and final desktop/narrow-screen browser verification.
