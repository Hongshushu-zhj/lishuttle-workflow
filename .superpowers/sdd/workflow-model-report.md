# Workflow state model interface

Owned files: `platform/frontend/workflow-state.js`, `tests/test_workflow_state.cjs`, this report. No app/layout/engine/input edits or commits.

Plain browser script exports `globalThis.WorkflowState`; Node `require` returns the same API. No dependencies. All transitions return state without mutating the previous state. JSON snapshots and assembly/report payloads are cloned; keys are sorted recursively so property order does not change fingerprints. Arrays retain order. Supply JSON data only.

## Integration

```js
let workflow = WorkflowState.create({project: projectId, build: appliedBuild,
  inputs: {func, map, task, csv, xml, path, identity, copyPolicy}});
workflow = WorkflowState.update(workflow, currentSemanticSnapshot, '地图已改变，请重新装配');
workflow = WorkflowState.markAssembled(workflow, job);
workflow = WorkflowState.contentChanged(workflow, 'CSV 内容已保存，请重新检查');
workflow = WorkflowState.markPreflight(workflow, {ok: result.ok, issues: result.issues});
const status = WorkflowState.getStatus(workflow, facts);
runButton.disabled = status.actions.run.disabled;
```

Pass a COMPLETE semantic snapshot to `update`, including project identity/configuration relevant to assembly, applied build directory/preset, function, map, task, CSV/XML source, area/paths, copy strategy, task identity. Do not include navigation, search, editor expansion, unrelated global tool configuration, or runtime sessions. `update` increments `revision` only for a changed canonical fingerprint. Existing assembly identity is retained but becomes stale. A switch-project integration may replace the model with `create` to clear the old project's presentation.

`markAssembled` stores `{snapshot,fingerprint,revision,context}` and clears preflight. `contentChanged` increments `contentRevision`, keeping assembly untouched; use only after successful XML/CSV content save. `markPreflight` records current draft/content revisions and a cloned report (normalize success to `ok: true`). Async handlers must reject obsolete responses before invoking these methods; the model does not own request cancellation/tokens.

## Facts supplied by integration

- `project: {ready, reason}`: selected valid project; do not bundle unrelated resource/tool requirements into readiness.
- `build: {ready, reason, selectionReady, selectionReason, executableReady, executableReason, compilerReady, compilerReason}`: `ready` means applied target usable by assembly/run. `selectionReady` means valid compilation target draft; omitted falls back to `ready`. Compilation may therefore apply a new draft target. Existing executable reuse never requires compiler readiness.
- `inputs: {ready, reason}`: actual input validity from existing app/backend; no engine rules duplicated.
- `pending: {csvDirty, xmlDirty, saveProjectReason, assembleReason, preflightReason, runReason}`: dirty editor flags block assembly/check/run. Optional per-action reason strings express existing specific guards.
- `runtime: {busy, reason, cancellable, stage, completed, failed}`: actual backend occupancy plus explicit stage ID for active operation. Runtime sid/context stays in the runtime controller, outside this draft model. `completed`/`failed` describe run outcome only, not compile outcome.

`getStatus` returns `{assemblyCurrent, preflightCurrent, preflightPassed, actions, stages}`. `actions` has `saveProject`, `compile`, `assemble`, `preflight`, `run`, `cancel`; every value is `{disabled,reason}`. `stages` are ordered `project/build/inputs/assembly/check/run`, each `{id,title,status,reason}`; statuses are `pending/ready/active/complete/stale/failed`. Preflight success is required for front-end run availability, while backend remains authoritative and rechecks at launch. Missing facts default to unavailable, not presumed valid. Checks require assembly; compiler is independent of run readiness. Display actions' reasons beside buttons.

## Verification

Tests written first and observed red on missing model. A further red regression proved compilation must not mark simulation stage active; another proved draft build choice must compile without being already applied. Final `node tests/test_workflow_state.cjs` passes, covering semantic invalidation fields, project/build changes, canonical order, immutable input/assembly contexts, content-only preflight invalidation, compiler-free executable reuse, draft compilation, dirty edits, backend busy/cancel, six stages and browser export. `node --check platform/frontend/workflow-state.js` and focused `git diff --check` pass.
