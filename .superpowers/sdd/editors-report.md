# Editors integration report

Implemented platform/frontend/editors.js as a plain-script module. Existing app.js editor definitions intentionally remain for the parent integration step.

- CSV drafts are tracked independently with S.csvDirty, guarded before replacement/navigation/write-through column operations, and explicitly discarded through a successful server reload. Failed reloads retain drafts.
- CSV requests validate project epoch, path, request identity, and local edit revision. Successful saves preserve newer edits and invalidate preflight through workflowContentChanged; assembly context is untouched.
- XML input is dirty immediately, autosaves on change, retains failures, and updates saved data without rerendering other parameter inputs. CSV-backed radius rejects saving while CSV draft exists.
- Default restoration rejects XML drafts and runtime busy; finally cannot enable its button during runtime busy. Search/scope and asynchronous parameter reloads preserve pending XML inputs.
- Existing direct onclick=loadCsv is safe: only literal true enables the discard path, never a MouseEvent.

Validation: node --test tests/test_editor_workflow.cjs: 8 passed, 0 failed. node --check platform/frontend/editors.js passed. git diff --check for module/tests passed. Tests first failed against baseline missing draft APIs; click-event regression separately failed 1 !== 0 before its strict-discard fix.

Integration requirements: Remove app.js parameterRequest-through-setColumn definitions (retain esc); load editors.js in production manifest; bind explicit discard button to discardCsvChanges; call guardCsvChanges before input/project switches/launch and reject navigation while S.xmlDirty; provide globals $, S, get, post, toast, esc, attr, FUNC_INFO, workflowContentChanged, refreshWorkflow, focusStage. The latter includes rendering's pre-existing attr/FUNC_INFO dependencies. No install, engine, configuration, or real data writes performed.

## Integration follow-up

CSV dirty status now updates csv-dirty-status, shows/hides btn-csv-discard, and opens csv-editor details when a guarded action is blocked. Parameter filter/search changes are explicitly blocked while dirty or saving and restore the control's prior value with save/discard guidance; renderParams itself rejects dirty input replacement.

Added savePendingParameters() to retry unchanged failed values and discardParameterChanges() to reload actual server state, clearing drafts only after successful current-job/current-project/current-revision response. Discard failures and edits arriving during reload retain drafts. Root binds btn-params-save/btn-params-discard.

Parameter saves and defaults increment S.parameterWrites before the request and decrement in finally. Default responses never rerender over a newer dirty draft, including a draft entered during their follow-up reload; runtime busy still controls the final button state. Root uses S.parameterWrites to block check/run while these writes remain in flight.

Evidence: five added integration tests failed against prior module (8 passed, 5 failed), then passed after fixes. Final editor suite: 15 passed, 0 failed; node --check and git diff --check passed. Only module, editor tests, and this report changed for follow-up.
