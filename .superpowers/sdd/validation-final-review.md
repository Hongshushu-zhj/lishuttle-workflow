# Result validation repair review

Reviewed `p0-brief.md`, the repair appendix in `validation-report.md`, the original `validation-review.md`, `validation-final-review.diff`, current validator/tests, and the exact active engine sources in `D:/workspace/LAB/Lab20261013`. This is a read-only review except for this report. No engine execution, real-data changes or commits. The reported 65 tests were read but not rerun. Four new synthetic probes used the current test fixture helpers and cleaned up their temporary files.

## Verdicts

- **Spec compliance: changes required.** The five original triggers have been addressed, but three Important defects remain in calibration artifact verification and partial-result classification.
- **Code quality: changes required.** The explicit model-kind units and source-based outcome handling improve the contract. However, model parsing currently treats arbitrary XML names as engine models, cells persistence is not associated with the claimed updated objects, and an empty model follows a different error/classification path from a malformed model. Current positive fixtures use name-only XML, which conceals the first two weaknesses.
- **Remaining findings:** 0 Critical, 3 Important. The additional runtime recovery patch has no new Important finding from this focused inspection.

## Original five findings

| Original finding | Repair assessment |
| --- | --- |
| XML filename used as calibration report prefix | Closed: `_candidates` uses `task_name` at validator lines 46–49; `_calibration` uses it at 598–605. The fixture now separates `different-config.xml` and `demo`, and missing `task_name` stays uncertain. |
| Common-model save failure ignored | Original trigger closed: current completion/failure/save messages are evaluated at 643–679 and the named general model is checked; cells success plus explicit common save failure becomes partial. Model structural integrity still has the separate F2 gap below. |
| General/scene updates counted as no update | Closed: `model_kinds.cells/general/scenes` carry separate units/outcomes; `_aggregate_model_kinds` at 552–575 derives the aggregate without adding unlike units. Source scene completion/failure is handled at 683–720. |
| Stale floor directories above the configured cap imposed extra layers | Closed: validator 339–344 derives a known cap; 395–402 excludes out-of-cap and unchanged historical artifacts before extending a region stack. Old in-cap directories cannot expand it either. |
| Unchanged unrelated malformed XML poisoned the current result | Closed for the original trigger: `_current_model_entries` filters by applicable paths and changed content before parsing (523–548). An unchanged unrelated historical XML is not parsed as a mandatory current model. |

## Important remaining findings

### F1. Any changed cells model can confirm all claimed site updates without object association

**Code:** `result_validation.py:623–629`; `_current_model_entries(..., 'cells')` at 526–528 searches every cells XML. The test is only `any(entry.get('model_names') ...)`, followed by `cells['updated'] = updated`. No expected cell identity, site membership, report model identity or per-object save evidence is checked.

**Source:** `CorrectCalculator.cpp:307–308` takes the logged site name from `cellData->GetTrasceiver()->siteName`; 341–351 constructs one saved model per transceiver and sets its `ModelName` to `tran->cells.front()->cellID`. `CellCorrectionData.cpp:175–184` emits `m_transceiver->name` in the summary's `cell` field and the accepted model's features thereafter. These are three distinct identity fields: merely comparing the summary first column to the site name or saved cellID would invent a relationship. A trustworthy mapping is needed, or the result must stay unconfirmed.

**Independent new probe:** current report `cell,model_id,update` / `a,site-model,yes`, current site `a` success Y/update Y, and a changed `cells/city.xml` containing only `ModelName=unrelated_old_cell`. The XML was deliberately shaped like the source format: `ModelVersion=0`, `PropagationCategory name="LiShuttleModel"`, `Model ID="1"` and all six K coefficient elements. Actual result: `verdict=success`, `cells.updated=1`, no issues. A simpler name-only XML gives the same result. Thus this is independent of F2.

**Required change:** Verify expected saved objects using source-derived cell/transceiver/site mappings from the fixed engineering input context, plus current reports. Preserve the distinctions `siteName` → transceiver `name` → first cell `cellID`; pin any input mapping to the run rather than reading an unrelated current selection. Confirm all claimed updates or report their verified subset; if the mapping is unavailable, retain unconfirmed rather than attributing every update to one unrelated changed file. Add disjoint-identity and incomplete-save regression cases.

### F2. Arbitrary XML containing ModelName is accepted as a usable engine model

**Code:** `_xml` at 424–438 checks only XML well-formedness, presence of at least one root element, and any descendant `ModelName`. The general and scene checks then treat matching names as successful persistence (666–673, 697–707). No model format/version, category, Model ID or required numerical model parameters are recognized.

**Source:** the source saves sibling `ModelVersion` and `PropagationCategory` nodes; `LiShuttleCellModel.cpp:279–295` checks/writes version 0 and 234–253 writes `PropagationCategory(name=LiShuttleModel)`. `PropagationModel.cpp:56–66` requires an integer Model ID. `LiShuttlePropagationModel.cpp:170–210` requires the correct category and six numerical coefficients (`K0/Knear/Kfar` and the corresponding nlos values); 283–304 writes these values. Scene models have their own version/category/parameter layout. Multi-root support must be retained, but XML syntax alone is insufficient evidence of an engine-loadable model.

**Independent new probe:** current reports/clean grid, site success Y/update N, `CalNewModelName=new_general`, general-completed log, and top-level `LiShuttleModel.xml` containing only `<Anything><ModelName>new_general</ModelName></Anything>`. Actual result: `verdict=success`, business success, no issues. The engine cannot recognize this as the saved propagation model.

**Required change:** Recognize the reviewed model structures and validate the mandatory fields/finite values for the relevant kind before calling persistence usable. Known broken reviewed structures should be invalid; unsupported structures/versions should remain unconfirmed. Update the healthy fixtures to actual minimal source-compatible model fragments so arbitrary XML cannot serve as positive evidence.

### F3. An empty cells model loses the model-kind error and defeats partial-result preservation

**Code:** `_xml` calls `check.file` at 425 before attaching `model_kind` to a parsing error at 437. For an empty file, `check.file` emits an untagged `EMPTY_FILE` and returns None at 171–173. The cells path therefore records uncertainty (`NO_CURRENT_MODEL`) rather than a definite cells artifact failure; the general model may still be verified successfully. `validate` at 755–758 cannot preserve partial because the hard error lacks `model_kind`.

**Independent new probe:** current valid calibration reports, verified changed general model with general-completed log, site success Y/update Y, but changed `cells/city.xml` is zero bytes. Actual result: `verdict=failed`, business unconfirmed; issues `EMPTY_FILE` without a model kind and `NO_CURRENT_MODEL(model_kind=cells)`. The equivalent nonempty malformed cells XML is intentionally classified as partial by the new test at `tests/test_result_validation.py:537–543`. An empty/truncated model is the same category-specific persistence failure, not a shared-report failure.

**Required change:** Carry model-kind attribution through empty/read/integrity failures and return an invalid candidate outcome so the relevant kind is failed. Preserve confirmed updates in other kinds as partial, while keeping shared report/clean-grid failures global. Cover empty and unreadable current model files alongside malformed XML.

## Additional requested checks

- **clean_grids capability:** current default service context has no trusted binary capability flag. Validator 462–465 leaves a missing file unconfirmed with the exact path, preventing false success; a known supported capability makes it required. Existing files are streamed and checked against the reviewed header/data layout, accepting the source's Windows NUL terminators. Source `CalibrationParams.h:106` defaults `isUpdateDtFiles=true`; `PMCorrectionData.cpp:225–235` writes the header and selected records. No invented XML setting was found.
- **3d empty base:** validator 365–382 inspects all required base metrics before deciding an entire region has no usable base evidence. Only the all-empty case avoids imposing an unobserved full upper cube and remains unconfirmed; a single empty BESTSERVER companion still fails. Unknown/no-participation evidence cannot become success. Existing source-supported height cap and region-specific lazy expansion are retained.
- **floor current scope:** only changed applicable elevated products extend a region's requirements, and intermediate layers are then checked only for that region. Historical directories do not extend the stack or appear in the returned current file list. An unknown actual building stack remains explicitly uncertain when only base evidence exists.
- **BESTSERVER 0:** retained as invalid. This agrees with the source's short conversion; no relaxation is requested.
- **runtime monitor-start recovery:** current `core.py:947–964` retains `recover_pump` if monitor creation and initial termination both fail. `stop` at 977–995 retries termination and invokes recovery outside the runner lock; the pump confirms tree exit before releasing the lease and setting `done_event`. `shutdown` waits for that event. The new focused test at `tests/test_runtime_lifecycle.py:166–188` exercises this path. No test rerun or engine run was needed for this static follow-up.

## Verification limits

New probes exited 0 and produced the stated results using temporary synthetic artifacts. They do not assess numerical/physical propagation accuracy. Existing reported suite results are attributed to the implementation report, not independently reasserted here. Approval remains blocked by F1–F3; the original five fixes and runtime follow-up can otherwise stand.

## Final F1–F3 follow-up review

This section supersedes the earlier blocked verdict for the latest implementation. The reviewer read the latest diff, the final repair appendix in `validation-report.md`, the 83-test repair set and the three additional general-model compatibility regressions. Existing reported suites were not rerun. Five focused post-repair probes used actual `snapshot()` baselines rather than the test helper's synthetic empty baseline; a sixth probe checked the additional source-compatibility correction. No engine or real data was used.

- **Spec compliance: approved for the reviewed artifact-validation scope.** F1, F2 and F3 are closed. No remaining Critical or Important finding identified in this follow-up.
- **Code quality: approved for the reviewed scope.** The fixes preserve explicit uncertainty when evidence is missing and retain separately verified model outcomes. The minor item-state consistency follow-up is closed below.
- **Remaining severity:** 0 Critical, 0 Important; no pending item-state follow-up in this review.

### F1 closure: a pinned three-domain identity chain

`snapshot()` now copies the preflight records into `baseline.engineering_records` (`result_validation.py:88–91`). `_cell_identity_evidence` uses that captured list, refuses to backfill an old baseline from execution-time context, detects context drift and ambiguous/duplicate identities, and requires a unique **current changed** summary record with `cell=transceiver_name, update=yes` plus a validated saved model with `ModelName=cell_id` (`:662–714`). The count of verified sites is separate from the raw update-log count, and incomplete object sets remain unconfirmed.

This matches the actual source domains: `CellLoader.cpp:1017` reads `siteName` from the configured SiteId field; the ordinary CSV branch sets `transceiver.name=cell.cellID` at 1138, while the validator still represents these as explicit distinct fields. `CorrectCalculator.cpp:307–308` logs siteName and 341–351 saves models named from each transceiver's first cellID. No equality between site names and cell names is invented.

**Fresh independent probes:** with fixed `site-S → trans-T → cell-C`, a current matching summary and full source-compatible `cell-C` model produced success and one verified site; replacing the saved identity with `other-cell` produced unconfirmed, zero verified sites and `NO_CURRENT_MODEL`. Both used a real prelaunch snapshot. This closes the original unrelated-model false success.

### F2 closure: recognized model structures and source-compatible historical general sets

`_xml` now distinguishes unsupported formats/versions from known malformed models and validates `ModelVersion`, the reviewed category, Model IDs, names and all six finite float32-range coefficients (`:439–524`). Scenes additionally require their source metadata and validate any present training statistics. Positive fixtures now contain actual sibling-root structures; name-only XML is no longer positive evidence.

**Fresh independent probe:** `<Anything><ModelName>new_general</ModelName></Anything>` with a current general-completed log now produces unconfirmed with `MODEL_FORMAT_UNKNOWN` and `NO_CURRENT_GENERAL_MODEL`, never aggregate success.

The follow-up also found and corrected an overly strict general ModelName uniqueness rule. `PMCorrectionEngine.cpp:315–317` passes `overwrite=false`; `LiShuttlePropagationModel.cpp:307–347` appends a fresh Model ID, and factory loading indexes the category/ID (`PropagationModelFactory.cpp:130–153`). Thus repeated general names with distinct IDs are legal historical saved sets. Current validator lines 490–495 allow that only for general models, while preserving duplicate-ID rejection for every kind and conservative identity checks for cells/scenes. The three new regressions cover legal repeated general names, illegal repeated IDs, and duplicate cells/scenes names.

**Fresh independent probe after this correction:** complete general XML with the same `new_general` name at IDs 1 and 2 changed from general failure/global partial to success with no issues. The reviewer confirmed the source save and load rules independently; no algorithm code was changed.

### F3 closure: integrity errors retain their model category

`_xml` passes `model_kind` into `check.file` and returns an invalid candidate for an empty/unreadable current model (`:439–446`). `_Check.changed` routes new or observably modified unreadable models through that attributed failure path, while avoiding promotion of unchanged historical files (`:142–165`). Shared report and clean-grid failures remain global.

**Fresh independent probes:** an empty current cells model plus a verified healthy general model produced partial with `EMPTY_FILE(model_kind=cells)`; a synthetic PermissionError reading a new cells model produced partial with `ARTIFACT_READ(model_kind=cells)`. Both had cells updated=0 and a definite cells failure, rather than treating missing persistence as an uncertain unclassified global error. These close the original empty-file classification gap and its unreadable-file variant.

### Minor output-contract follow-up: closed

During the final read, general `items` still classified an `entry.unconfirmed` as success and used a persistence-confirmed reason, although both the general-kind and overall verdict were correctly unconfirmed. The implementation now emits failed for invalid entries, unconfirmed for unsupported/unconfirmed entries or unmatched identity, and success only for confirmed matching identity, with matching reasons. The reviewer inspected this final branch and the new assertions in both arbitrary-format and unknown-version regressions.

Four fresh independent probes used actual prelaunch `snapshot()` baselines and temporary artifacts. Unknown XML and version 99 each produced overall/kind/item unconfirmed with an uncertainty reason; a valid matching general model produced success at all three levels; a reviewed model missing a coefficient produced failed kind/item with overall partial, preserving the separate cells no-update result. The final four-case probe exited 0. The first draft of the probe incorrectly expected a global failure for the last case; its expectation was corrected to the established partial-preservation contract before this final run. No implementation, algorithm, engine or real-data file was changed by the review, and no previously reported suite was rerun. This closes the minor presentation inconsistency without reopening F1–F3.

The parent reports the transient preflight failures mentioned in the implementation report were corrected and its 72 preflight tests pass. Preflight was outside this final repair review, and that result is not independently reasserted here. Full service regression and any isolated real-engine acceptance remain the parent's separate verification work.
