# Workflow documentation report

Owned changes: README.md and this report only. No code/tests, dependencies, configuration, real inputs, engine runs or commits.

Read the approved design and implementation plan plus existing assembly recovery, workflow model/layout, preflight and result validation reports. README now describes the ordered project → build → inputs → assembly → check → run workspace, same-card build selection/executable application, optional compilation, shared logs, explicit CSV save/discard, semantic assembly invalidation versus content-only preflight invalidation, and fixed sid/output attribution. Existing XML preview/confirmation distinguishes retryable failure, runtime occupancy, stale preview and uncertain network write outcome; template assembly remains a summary/generation branch. Preserved source XML, resource-copy, backup and historical result semantics.

Added a planned module responsibility table for api-client.js, workflow-state.js, project-build.js, task-assembly.js, editors.js, runtime-session.js and app.js bootstrap. It explicitly labels migration progress as code-dependent rather than claiming all extraction is finished.

Verification: reviewed README diff against design and reports; git diff --check -- README.md passed. Documentation only: no application tests or engine execution. Root owns final behavior/wording alignment with integration and module extraction.
